"""Compile a reviewed new-event production, render before saving, then insert atomically."""
from copy import deepcopy
import datetime as dt
import io
import math

from PIL import Image, ImageDraw, ImageFont

from models import ProjectDraft, TicketDraft, FreeTextDraft, TimetableRowDraft
from models.event_format import KEY, new_part, schedule
from models.timetable import build_grid_order_from_rows
from services.production_intake import normalized

MAX_ROWS = 100


def minute(value):
    try:
        t=dt.datetime.strptime(str(value),'%H:%M')
        return t.hour*60+t.minute
    except (ValueError,TypeError) as exc:
        raise ValueError('時刻はHH:MMで入力してください。不明な時刻は資料で確認してください。') from exc


def clock(value):
    n=minute(value)
    return f'{n//60:02d}:{n%60:02d}'


def duration(start,end):
    d=minute(end)-minute(start)
    if d<0: raise ValueError('終了が開始より前です。日付をまたぐ公演には未対応です。')
    return d


def match_names(names,registered):
    table={}
    for name in registered: table.setdefault(normalized(name),set()).add(name)
    exact=set(registered)
    return {name:(name if name in exact else next(iter(table[normalized(name)]))) for name in names
            if name in exact or len(table.get(normalized(name),set()))==1}


def compile_plan(event,raw_parts,aliases=None,show_transitions=False):
    from services.production_normalization import normalize_event,grid_order
    event=normalize_event(event)
    aliases=aliases or {}
    if not str(event.get('event_name','')).strip() or not str(event.get('venue','')).strip():
        raise ValueError('イベント名と会場名を確認してください。')
    try: event_date=dt.date.fromisoformat(event.get('event_date',''))
    except (TypeError,ValueError) as exc: raise ValueError('開催日をYYYY-MM-DDで確認してください。年を推測せず入力してください。') from exc
    if not 1<=len(raw_parts)<=6: raise ValueError('制作する部を1〜6部選択してください。')
    if sum(len(p.get('rows',[])) for p in raw_parts)>MAX_ROWS: raise ValueError('AIおまかせ制作は合計100出演行以内で選択してください。')
    overview_order,order_info=grid_order(event.get('artists',[]),
        [str(r.get('artist') or '').strip() for p in raw_parts for r in p.get('rows',[])],aliases)
    parts=[]
    for i,raw in enumerate(raw_parts):
        rows=raw.get('rows',[])
        if not rows: raise ValueError(f'{raw.get("name") or str(i+1)+"部"}の出演者を確認してください。')
        part=new_part(i,clock(raw.get('open_time')),clock(raw.get('start_time')))
        if minute(part['open_time'])>minute(part['start_time']): raise ValueError('OPENがSTARTより後になっています。')
        part.update(name=raw.get('name') or f'{i+1}部',note=str(raw.get('note') or ''),goods_offset=0,
                    hide_transitions=not show_transitions,transition_label=raw.get('transition_label') or '転換')
        if clock(rows[0].get('start'))!=part['start_time']:
            raise ValueError(f'{part["name"]}: STARTと最初の出演時刻が違います。資料を確認してください。')
        post_start,post_end=raw.get('post_start'),raw.get('post_end')
        if bool(post_start)!=bool(post_end): raise ValueError('終演後物販は開始・終了の両方を確認してください。')
        if post_start:
            part.update(post_start=clock(post_start),post_duration=duration(post_start,post_end))
            if not part['post_duration']: raise ValueError('終演後物販の長さは1分以上にしてください。')
        for j,raw_row in enumerate(rows):
            name=str(raw_row.get('artist') or '').strip()
            if not name or name in ('OPEN / START','開演前物販','終演後物販'):
                raise ValueError('出演者行にはアーティスト名を入力してください。')
            name=aliases.get(name,name)
            start,end=clock(raw_row.get('start')),clock(raw_row.get('end'))
            live=duration(start,end)
            if not live: raise ValueError(f'{name}: 出演時間が0分になっています。')
            change=duration(end,rows[j+1].get('start')) if j+1<len(rows) else 0
            post=raw_row.get('post_goods') is True
            if post and not post_start: raise ValueError(f'{name}: 終演後物販の開始・終了を確認してください。')
            gs,ge=raw_row.get('goods_start'),raw_row.get('goods_end')
            if bool(gs)!=bool(ge): raise ValueError(f'{name}: 物販の開始・終了の両方を確認してください。')
            add_start,add_end=raw_row.get('add_start'),raw_row.get('add_end')
            if bool(add_start)!=bool(add_end): raise ValueError(f'{name}: 追加物販の開始・終了を確認してください。')
            row=TimetableRowDraft(artist_name=name,duration=live,adjustment=change,is_post_goods=post,
                goods_start_time=clock(gs) if gs and not post else '',
                goods_duration=duration(gs,ge) if gs and not post else 0,place=str(raw_row.get('place') or ''),
                add_goods_start_time=clock(add_start) if add_start else '',
                add_goods_duration=duration(add_start,add_end) if add_start else None,
                add_goods_place=str(raw_row.get('add_place') or ''))
            part['rows'].append(row.to_legacy_dict())
        last_end=rows[-1]['end']
        if post_start:
            part['post_prepare']=duration(last_end,post_start)
        # Mechanical parity: every reviewed performance time must survive recalculation.
        computed,_=schedule(part)
        if [(r['start'],r['end']) for r in computed]!=[(clock(r['start']),clock(r['end'])) for r in rows]:
            raise ValueError('出演時刻をアプリの計算で再現できません。資料を確認してください。')
        names=[r['ARTIST'] for r in part['rows']]
        order=list(dict.fromkeys([n for n in overview_order if n in names]+names))
        for row in part['rows']: row['GRID_NO']=order.index(row['ARTIST'])+1
        parts.append(part)
    from services.timetable_pdf_service import normal_rows_from_part
    first=parts[0]
    if len(parts)==1 and first.get('post_duration') and not any(r['IS_POST_GOODS'] for r in first['rows']):
        raise ValueError('終演後物販枠がありますが対象アーティストが未指定です。「終演後」のチェックを確認してください。')
    rows=normal_rows_from_part(first)
    cfg=dict(enabled=len(parts)>1,initialized=len(parts)>1,count=len(parts) if len(parts)>1 else 2,
             parts=parts if len(parts)>1 else [new_part(0),new_part(1)],
             free_viewing=event.get('free_viewing') is True,free_text=str(event.get('free_text') or ''),
             free_notices=str(event.get('free_notices') or ''))
    count=len(build_grid_order_from_rows(rows))
    grid_rows=min(5,max(1,math.ceil(count/5)))
    per_row,remainder=divmod(count,grid_rows)
    row_counts=[per_row]*(grid_rows-remainder)+[per_row+1]*remainder
    draft=ProjectDraft(title=event['event_name'].strip(),subtitle=str(event.get('subtitle') or ''),event_date=event_date,
        venue_name=event['venue'].strip(),venue_url=str(event.get('venue_url') or ''),
        open_time=first['open_time'],start_time=first['start_time'],goods_start_offset=0,
        tickets=[TicketDraft.from_dict(t) for t in event.get('tickets',[])],
        ticket_notes=event['ticket_common_note'].splitlines() if event.get('ticket_common_note') else [],
        free_texts=[FreeTextDraft(title=str(t.get('title') or ''),content=str(t.get('body') or '')) for t in event.get('free_texts',[])],
        settings={'tt_font':'keifont.ttf','grid_font':'keifont.ttf','tt_columns':2,'production_order':order_info,KEY:cfg},
        grid_settings={'order':build_grid_order_from_rows(rows),'rows':grid_rows,'row_counts_str':','.join(map(str,row_counts)),
                       'layout_mode':'レンガ (サイズ統一)','alignment':'中央揃え'})
    return draft,rows


def read_default_logo():
    from services import asset_service
    assets=[a for a in asset_service.list_assets_by_type('logo')
            if a.name=='ROCKFIELD ULTRA LIVE - BASIC']
    if len(assets)!=1:
        raise ValueError('標準ロゴを一意に選択できません。アセットからロゴを選んでください。')
    return asset_service.read_image_asset(assets[0].id)


def title_logo(title,font_path):
    image=Image.new('RGBA',(2000,400))
    draw=ImageDraw.Draw(image)
    size=260
    while size>30:
        font=ImageFont.truetype(font_path,size)
        if draw.textbbox((0,0),title,font=font)[2]<1900: break
        size-=5
    draw.text((1000,200),title,font=font,fill='white',anchor='mm')
    return image


def open_background(data):
    """Downsample large existing backgrounds for composition, keeping the asset intact."""
    import warnings
    from PIL import UnidentifiedImageError
    if not data or len(data)>20*1024*1024:raise ValueError('背景は20MB以下で選択してください。')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error',Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                if image.format not in ('PNG','JPEG','WEBP') or image.width*image.height>40000000:
                    raise ValueError('背景はPNG・JPEG・WebPの4000万画素以下で選択してください。')
                image.draft('RGB',(2160,2700))
                image.thumbnail((2160,2700),Image.Resampling.LANCZOS)
                return image.convert('RGBA')
    except (UnidentifiedImageError,OSError,Image.DecompressionBombWarning,Image.DecompressionBombError) as exc:
        raise ValueError('背景画像を開けませんでした。') from exc


def render_package(draft,rows,background=None,logo=None,template=None):
    """Render both finished variants through existing renderers, without any persistence."""
    from services import font_service,artist_service,event_format_service
    from logic_grid import generate_grid_image
    from logic_timetable import generate_timetable_image
    from services.timetable_service import build_tt_gen_list_from_rows
    from models.flyer_keys import FLYER_KEY_REGISTRY
    from utils.flyer_generator import create_flyer_image_shadow
    from utils.flyer_helpers import format_event_date
    from services.image_studio import open_image,png
    from utils.text_generator import build_event_summary_text
    project=deepcopy(draft)
    if template is not None:
        from services.production_templates import apply
        project=apply(project,rows,template)
    font=font_service.ensure_font_path('keifont.ttf')
    if not font: raise ValueError('日本語フォントを準備できませんでした。')
    bg=open_background(background) if background else None
    logo_image=open_image(logo) if logo else title_logo(project.title,font)
    sources={};failures=[]
    cfg=project.settings[KEY]
    if cfg['enabled']:
        for variant in ('grid','tt'): sources[variant]=event_format_service.render(project,variant,failures=failures)
    else:
        artists=artist_service.resolve_artists_in_order(build_grid_order_from_rows(rows),failures=failures)
        counts=[int(n) for n in project.grid_settings['row_counts_str'].split(',')]
        grid_font=font_service.ensure_font_path(project.settings.get('grid_font') or 'keifont.ttf')
        tt_font=font_service.ensure_font_path(project.settings.get('tt_font') or 'keifont.ttf')
        if not grid_font or not tt_font:raise ValueError('テンプレートのフォントを準備できませんでした。')
        sources['grid']=generate_grid_image(artists,'',font_path=grid_font,row_counts=counts,
            is_brick_mode=project.grid_settings.get('layout_mode')=='レンガ (サイズ統一)',
            alignment={'左揃え':'left','右揃え':'right'}.get(project.grid_settings.get('alignment'),'center'),failures=failures)
        tt_rows=build_tt_gen_list_from_rows(rows,project.open_time,project.start_time)
        sources['tt']=generate_timetable_image(tt_rows,font_path=tt_font,columns=project.settings.get('tt_columns',2),
            style=project.settings.get('tt_style'),failures=failures)
    styles={e.short_key:e.default for e in FLYER_KEY_REGISTRY if e.persist}
    styles.update(logo_scale=min(1.65, 235/(432*logo_image.height/logo_image.width)),logo_pos_y=0.0,footer_pos_y=600,subtitle_size=38,date_size=56,
                  venue_size=32,time_size=36,ticket_name_size=30,ticket_note_size=17,
                  ticket_gap=-30,note_gap=0,area_gap=22,free_viewing_size=50,free_note_size=24,free_notice_size=17)
    if template is not None:styles.update(project.flyer_settings)
    results={};metadata={};layout_reports={};final_args={}
    for variant,source in sources.items():
        if source is None: raise ValueError('出演者の画像を生成できませんでした。')
        # Fit the image into the content area without stretching faces or type.
        width_pct=min(94,max(10,round(560*source.width/(1080*source.height)*100)))
        height_pct=width_pct
        target_h=source.height*(1080/source.width)*(height_pct/100)
        # Put the main image below header; ticket block starts independently at 1100.
        position=round(675-(510+target_h/2))
        styles.update({f'{variant}_scale_w':width_pct,f'{variant}_scale_h':height_pct,f'{variant}_pos_y':position})
        render_styles={**styles,'event_multipart':cfg['enabled'],'event_free_viewing':cfg.get('free_viewing',False),
            'event_free_text':cfg.get('free_text',''),'event_free_notices':cfg.get('free_notices',''),
            'content_scale_w':width_pct,'content_scale_h':height_pct,'content_pos_y':position}
        if template is not None:
            render_styles.update({k:v for k,v in styles.items() if k in project.flyer_settings})
        for key in list(render_styles):
            if key.endswith('_font'):render_styles[key]=font_service.ensure_font_path(render_styles[key]) or font
        args=dict(bg_source=bg,logo_source=logo_image,main_source=source,styles=render_styles,
            date_text=format_event_date(project.event_date,styles.get('date_format','EN')),venue_text=project.venue_name,subtitle_text=project.subtitle,
            open_time=project.open_time,start_time=project.start_time,ticket_info_list=[t.to_dict() for t in project.tickets],
            common_notes_list=project.ticket_notes,system_fallback_filename=font,failures=failures)
        if template is not None:
            from services.production_layout import fit
            from services.production_templates import decode,META
            # Font families stay fixed. A missing template font must not silently change.
            for key,value in styles.items():
                if key.endswith('_font'):
                    resolved=font_service.ensure_font_path(value)
                    if not resolved:raise ValueError('テンプレートのフォントが見つかりません：'+str(value))
                    render_styles[key]=resolved
            cfg_meta=decode(template)[META]
            if cfg['enabled']:
                from models.event_format import active_parts,grid_layout,grid_row_counts
                parts=active_parts(cfg)
                columns=project.settings.get('tt_columns',2)
                count=sum(math.ceil(len(event_format_service.timetable_rows(p))/columns)+2 for p in parts)*columns
                grid_row_total=sum(len(grid_row_counts(grid_layout(p))) for p in parts)
            else:
                count=len(tt_rows);grid_row_total=project.grid_settings.get('rows',5)
            image,meta,fitted,report=fit(args,cfg_meta.get('zones',{}).get(variant),
                row_count=count if variant=='tt' else 0,columns=project.settings.get('tt_columns',2),
                grid_rows=grid_row_total if variant=='grid' else 0)
            for entry in FLYER_KEY_REGISTRY:
                key=entry.short_key
                if entry.persist and not key.endswith('_font') and key in fitted:styles[key]=fitted[key]
            for suffix in ('scale_w','scale_h','pos_y'):styles[f'{variant}_{suffix}']=fitted['content_'+suffix]
            results[variant]=png(image);metadata[variant]=meta;layout_reports[variant]=report;final_args[variant]=args
            continue
        _,meta=create_flyer_image_shadow(**args)
        for field,y in (('subtitle',300),('date',380),('venue',455),('time',380)):
            if field in meta:
                offset=round(meta[field]['base_y']-y)
                render_styles[field+'_pos_y']=offset
                styles[field+'_pos_y']=offset
        if not cfg['enabled']:
            render_styles.update(date_pos_x=-230,venue_pos_x=-230,time_pos_x=265)
            styles.update(date_pos_x=-230,venue_pos_x=-230,time_pos_x=265)
        _,meta=create_flyer_image_shadow(**args)
        ticket_shift=round(meta['ticket_name']['base_y']-1100)
        render_styles.update(ticket_name_pos_y=ticket_shift,ticket_note_pos_y=ticket_shift)
        styles.update(ticket_name_pos_y=ticket_shift,ticket_note_pos_y=ticket_shift)
        image,meta=create_flyer_image_shadow(**args)
        results[variant]=png(image)
        metadata[variant]=meta
    if template is not None:
        from services.production_layout import issues
        # Both variants share header/footer settings. Re-render after the stricter
        # variant has refined them so the saved manual editor reproduces both files.
        for variant,args in final_args.items():
            final={**args['styles'],**styles}
            for key in final:
                if key.endswith('_font'):final[key]=font_service.ensure_font_path(final[key]) or font
            final.update(content_scale_w=styles[variant+'_scale_w'],content_scale_h=styles[variant+'_scale_h'],content_pos_y=styles[variant+'_pos_y'])
            image,meta=create_flyer_image_shadow(**{**args,'styles':final})
            errors=issues(meta)
            if errors:raise ValueError('保存する配置の検査を通過しませんでした：'+'、'.join(errors[:3]))
            results[variant]=png(image);metadata[variant]=meta
    project.flyer_settings=styles
    # Store generated title as a logo too, so the saved normal editor reproduces it.
    logo_data=png(logo_image)
    text=build_event_summary_text(project.title,project.subtitle,project.event_date,project.venue_name,project.venue_url,
        project.open_time,project.start_time,[t.to_dict() for t in project.tickets],project.ticket_notes,
        list(dict.fromkeys(r['ARTIST'] for p in cfg['parts'] for r in p['rows'])) if cfg['enabled'] else build_grid_order_from_rows(rows),
        [f.to_dict() for f in project.free_texts])
    if cfg['enabled']:
        text+='\n\n■各部の時間\n'+'\n'.join(f'{p["name"]} OPEN {p["open_time"]} / START {p["start_time"]}' for p in cfg['parts'])
    if cfg.get('free_viewing'):
        text+='\n\n■観覧無料\n'+cfg.get('free_text','')+'\n'+cfg.get('free_notices','')
    from services.project_previews import KEY as PREVIEW_KEY, snapshot
    preview = snapshot(results)
    if preview: project.flyer_settings[PREVIEW_KEY] = preview
    return dict(draft=project,rows=deepcopy(rows),images=results,background=background,logo=logo_data,
                text=text,failures=failures,metadata=metadata,layout_reports=layout_reports,asset_ids={})


def persist_new_project(draft,rows):
    """Insert one new project and its rows in one transaction. No DELETE or overwrite."""
    from database import SessionLocal
    from repositories import project_repo,timetable_repo
    if draft.id is not None: raise ValueError('新規プロジェクト専用です。既存データは上書きしません。')
    db=SessionLocal()
    try:
        project=project_repo.stage_new_draft(db,draft)
        timetable_repo.add_new_project_rows(db,project.id,rows)
        db.commit()
        return project.id
    except Exception as exc:
        db.rollback()
        raise ValueError('新規プロジェクトの保存を確認できませんでした。自動再試行せず、プロジェクト一覧を確認してください。') from exc
    finally:db.close()
