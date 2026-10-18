"""Versioned production recipes inside existing flyer_templates JSON; no event data."""
from copy import deepcopy
import json
import math

from models.flyer_keys import FLYER_KEY_REGISTRY

META='_production'
VERSION=1


def decode(value):
    try: data=json.loads(value) if isinstance(value,str) else deepcopy(value)
    except (ValueError,TypeError): raise ValueError('制作テンプレートを読み取れません。')
    if not isinstance(data,dict):raise ValueError('制作テンプレートの形式が不正です。')
    styles={e.short_key:data[e.short_key] for e in FLYER_KEY_REGISTRY if e.persist and data.get(e.short_key) is not None}
    for entry in FLYER_KEY_REGISTRY:
        if entry.short_key not in styles:continue
        v=styles[entry.short_key]
        if isinstance(entry.default,bool): valid=isinstance(v,bool)
        elif isinstance(entry.default,(int,float)):
            valid=isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)
            if valid and entry.widget_min is not None:valid=entry.widget_min<=v<=entry.widget_max
        else:valid=isinstance(v,str) and len(v)<=256
        if not valid:raise ValueError('テンプレートの設定値を確認してください：'+entry.short_key)
        if isinstance(entry.default,int) and not isinstance(entry.default,bool):styles[entry.short_key]=round(v)
    meta=data.get(META,{})
    if not isinstance(meta,dict) or meta.get('version',VERSION)!=VERSION:raise ValueError('制作テンプレートのバージョンが未対応です。')
    return {**styles,META:meta}


def capture(project,raw_images=None,default=False):
    """Capture appearance only: never copy dates, ticket text, names or part rows."""
    data=decode(project.flyer_settings)
    grid={k:deepcopy(v) for k,v in project.grid_settings.items() if k in ('rows','row_counts_str','layout_mode','alignment')}
    source_images=raw_images or {}
    zones={}
    for variant in ('grid','tt'):
        source=source_images.get(variant)
        zones[variant]=dict(width=min(1020,round(1080*data.get(variant+'_scale_w',95)/100)))
        if source is not None:
            w=1080*data.get(variant+'_scale_w',95)/100
            h=source.height*1080/source.width*data.get(variant+'_scale_h',100)/100
            y=675-h/2-data.get(variant+'_pos_y',0)
            zones[variant]=dict(top=max(20,round(y)),bottom=min(1330,round(y+h)),width=min(1020,round(w)))
    from models.event_format import KEY,active_parts,grid_layout
    cfg=project.settings.get(KEY,{})
    part_designs=[]
    if cfg.get('enabled'):
        for part in active_parts(cfg):
            value=grid_layout(part)
            part_designs.append(dict(color=part.get('color'),grid=dict(rows=value['rows'],
                row_counts_str=value['row_counts'],layout_mode=value['layout_mode'],alignment=value['alignment'],font=value.get('font',''))))
    data[META]=dict(version=VERSION,default=bool(default),grid=grid,part_designs=part_designs,
        timetable={k:deepcopy(project.settings[k]) for k in ('tt_font','tt_columns','tt_style','grid_font') if k in project.settings},
        zones=zones)
    return data


def apply(project,rows,payload):
    from models.event_format import KEY,active_parts
    from models.timetable import build_grid_order_from_rows
    from models.timetable_style import normalize_style
    data=decode(payload);meta=data[META]
    result=deepcopy(project)
    result.flyer_settings={k:v for k,v in data.items() if k!=META}
    settings=meta.get('timetable',{})
    if not isinstance(settings,dict):raise ValueError('タイムテーブル設定が不正です。')
    for k in ('tt_font','grid_font','tt_style','tt_columns'):
        if k in settings:result.settings[k]=deepcopy(settings[k])
    if result.settings.get('tt_columns') not in (1,2):raise ValueError('列数は1列または2列で保存してください。')
    result.settings['tt_style']=normalize_style(result.settings.get('tt_style'))
    grid=meta.get('grid',{})
    if not isinstance(grid,dict):raise ValueError('グリッド設定が不正です。')
    if grid.get('layout_mode') not in (None,'レンガ (サイズ統一)','両端揃え (拡大縮小)'):raise ValueError('グリッドの配置方式が不正です。')
    result.grid_settings.update({k:deepcopy(grid[k]) for k in ('rows','row_counts_str','layout_mode','alignment') if k in grid})
    # Keep roughly the template's card density while adapting the number of rows.
    def layout(count,override=None,part_count=1):
        current=override or grid
        try: recipe=[int(x) for x in str(current.get('row_counts_str','5,5,5,5,5')).split(',')]
        except (TypeError,ValueError):raise ValueError('各行の枚数を確認してください。')
        if not recipe or any(n<1 or n>100 for n in recipe):raise ValueError('各行の枚数を確認してください。')
        if sum(recipe)==count:return recipe
        # Target grid aspect comes from the human's saved content frame.
        zone=meta.get('zones',{}).get('grid',{})
        aspect=part_count*zone.get('width',1000)/max(150,zone.get('bottom',1100)-zone.get('top',500))
        candidates=[]
        for nr in range(1,min(20,count)+1):
            base,rem=divmod(count,nr)
            counts=[base]*(nr-rem)+[base+1]*rem
            if max(counts)>8:continue
            predicted=max(counts)*1.4/nr
            score=abs(math.log(max(.01,predicted/aspect)))+.05*abs(max(counts)-max(recipe))
            candidates.append((score,counts))
        return min(candidates,key=lambda c:c[0])[1] if candidates else [count]
    order=build_grid_order_from_rows(rows)
    counts=layout(max(1,len(order)))
    result.grid_settings.update(order=order,rows=len(counts),row_counts_str=','.join(map(str,counts)))
    cfg=result.settings.get(KEY,{})
    if cfg.get('enabled'):
        designs=meta.get('part_designs',[])
        for index,part in enumerate(active_parts(cfg)):
            design=designs[min(index,len(designs)-1)] if designs else {}
            per_grid=design.get('grid') or grid
            if design.get('color'):part['color']=design['color']
            count=sum(not r.get('IS_GRID_HIDDEN') and not r.get('IS_HIDDEN') for r in part['rows'])
            counts=layout(max(1,count),per_grid,len(active_parts(cfg)))
            part['grid_settings']=dict(rows=len(counts),row_counts=','.join(map(str,counts)),
                layout_mode=per_grid.get('layout_mode','レンガ (サイズ統一)'),alignment=per_grid.get('alignment','中央揃え'),
                font=per_grid.get('font') or result.settings.get('grid_font','keifont.ttf'))
    return result


def save(name,payload,make_default=False):
    """Explicit single transaction; creates a new recipe and changes only default flags."""
    from database import SessionLocal
    from repositories import template_repo
    from services.template_service import _now
    if not name.strip():raise ValueError('制作テンプレート名を入力してください。')
    data=decode(payload);data[META]['default']=bool(make_default)
    db=SessionLocal()
    try:
        if template_repo.get_by_name(db,name.strip()) is not None:raise ValueError('同名のテンプレートがあります。別の名前で保存してください。')
        if make_default:
            for item in template_repo.list_templates(db):
                try:old=decode(item.data_json)
                except ValueError:continue
                if old[META].get('default'):
                    old[META]['default']=False
                    template_repo.update_data(db,item.name,json.dumps(old,ensure_ascii=False),_now())
        template_repo.create(db,name.strip(),json.dumps(data,ensure_ascii=False),_now())
        db.commit()
    except Exception:
        db.rollback();raise
    finally:db.close()
