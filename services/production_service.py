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
    return {name:next(iter(table[normalized(name)])) for name in names
            if len(table.get(normalized(name),set()))==1}


def compile_plan(event,raw_parts,aliases=None,show_transitions=False):
    aliases=aliases or {}
    if not str(event.get('event_name','')).strip() or not str(event.get('venue','')).strip():
        raise ValueError('イベント名と会場名を確認してください。')
    try: event_date=dt.date.fromisoformat(event.get('event_date',''))
    except (TypeError,ValueError) as exc: raise ValueError('開催日をYYYY-MM-DDで確認してください。年を推測せず入力してください。') from exc
    if not 1<=len(raw_parts)<=6: raise ValueError('制作する部を1〜6部選択してください。')
    if sum(len(p.get('rows',[])) for p in raw_parts)>MAX_ROWS: raise ValueError('AIおまかせ制作は合計100出演行以内で選択してください。')
    overview_order=[aliases.get(n,n) for n in event.get('artists',[]) if str(n).strip()]
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
    draft=ProjectDraft(title=event['event_name'].strip(),subtitle=str(event.get('subtitle') or ''),event_date=event_date,
        venue_name=event['venue'].strip(),venue_url=str(event.get('venue_url') or ''),
        open_time=first['open_time'],start_time=first['start_time'],goods_start_offset=0,
        tickets=[TicketDraft.from_dict(t) for t in event.get('tickets',[])],
        ticket_notes=[event['ticket_common_note']] if event.get('ticket_common_note') else [],
        free_texts=[FreeTextDraft(title=str(t.get('title') or ''),content=str(t.get('body') or '')) for t in event.get('free_texts',[])],
        settings={'tt_font':'keifont.ttf','grid_font':'keifont.ttf','tt_columns':2,KEY:cfg},
        grid_settings={'order':build_grid_order_from_rows(rows),'rows':5,'row_counts_str':'5,5,5,5,5',
                       'layout_mode':'レンガ (サイズ統一)','alignment':'中央揃え'})
    return draft,rows


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


def render_package(draft,rows,background=None,logo=None):
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
    font=font_service.ensure_font_path('keifont.ttf')
    if not font: raise ValueError('日本語フォントを準備できませんでした。')
    bg=open_image(background) if background else None
    logo_image=open_image(logo) if logo else title_logo(project.title,font)
    sources={};failures=[]
    cfg=project.settings[KEY]
    if cfg['enabled']:
        for variant in ('grid','tt'): sources[variant]=event_format_service.render(project,variant,failures=failures)
    else:
        artists=artist_service.resolve_artists_in_order(build_grid_order_from_rows(rows),failures=failures)
        sources['grid']=generate_grid_image(artists,'',font_path=font,row_counts=[5]*20,failures=failures)
        sources['tt']=generate_timetable_image(build_tt_gen_list_from_rows(rows,project.open_time,project.start_time),font_path=font,columns=2,failures=failures)
    styles={e.short_key:e.default for e in FLYER_KEY_REGISTRY if e.persist}
    styles.update(logo_scale=min(1.65, 235/(432*logo_image.height/logo_image.width)),logo_pos_y=0.0,footer_pos_y=600,subtitle_size=38,date_size=56,
                  venue_size=32,time_size=36,ticket_name_size=30,ticket_note_size=17,
                  ticket_gap=8,note_gap=4,area_gap=22,free_viewing_size=50,free_note_size=24,free_notice_size=17)
    results={};metadata={}
    for variant,source in sources.items():
        if source is None: raise ValueError('出演者の画像を生成できませんでした。')
        # Fit the image into the content area without stretching faces or type.
        width_pct=min(94,max(10,round(480*source.width/(1080*source.height)*100)))
        height_pct=width_pct
        target_h=source.height*(1080/source.width)*(height_pct/100)
        # Put the main image below header; ticket block starts independently at 1100.
        position=round(675-(590+target_h/2))
        styles.update({f'{variant}_scale_w':width_pct,f'{variant}_scale_h':height_pct,f'{variant}_pos_y':position})
        render_styles={**styles,'event_multipart':cfg['enabled'],'event_free_viewing':cfg.get('free_viewing',False),
            'event_free_text':cfg.get('free_text',''),'event_free_notices':cfg.get('free_notices',''),
            'content_scale_w':width_pct,'content_scale_h':height_pct,'content_pos_y':position}
        for key in list(render_styles):
            if key.endswith('_font'):render_styles[key]=font_service.ensure_font_path(render_styles[key]) or font
        args=dict(bg_source=bg,logo_source=logo_image,main_source=source,styles=render_styles,
            date_text=format_event_date(project.event_date,'EN'),venue_text=project.venue_name,subtitle_text=project.subtitle,
            open_time=project.open_time,start_time=project.start_time,ticket_info_list=[t.to_dict() for t in project.tickets],
            common_notes_list=project.ticket_notes,system_fallback_filename=font,failures=failures)
        _,meta=create_flyer_image_shadow(**args)
        for field,y in (('subtitle',300),('date',365),('venue',455),('time',510)):
            if field in meta:
                offset=round(meta[field]['base_y']-y)
                render_styles[field+'_pos_y']=offset
                styles[field+'_pos_y']=offset
        _,meta=create_flyer_image_shadow(**args)
        ticket_shift=round(meta['ticket_name']['base_y']-1100)
        render_styles.update(ticket_name_pos_y=ticket_shift,ticket_note_pos_y=ticket_shift)
        styles.update(ticket_name_pos_y=ticket_shift,ticket_note_pos_y=ticket_shift)
        image,meta=create_flyer_image_shadow(**args)
        results[variant]=png(image)
        metadata[variant]=meta
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
    return dict(draft=project,rows=deepcopy(rows),images=results,background=background,logo=logo_data,
                text=text,failures=failures,metadata=metadata,asset_ids={})


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
