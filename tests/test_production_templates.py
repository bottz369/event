"""Appearance-only recipes and real glyph-based fitting; no paid API or DB writes."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image
from models import ProjectDraft,TicketDraft,TimetableRowDraft
from models.event_format import KEY,new_part
from services import production_templates as recipes,production_layout as layout,production_service as production


def recipe():
    return dict(date_font='keifont.ttf',time_font='keifont.ttf',date_size=56,time_size=36,
        subtitle_size=38,venue_size=32,ticket_name_size=30,ticket_note_size=17,footer_pos_y=600,
        subtitle_pos_y=0,date_pos_y=7,date_pos_x=-230,venue_pos_y=40,venue_pos_x=-230,
        time_pos_y=140,time_pos_x=265,ticket_name_pos_y=-500,ticket_note_pos_y=-500,
        logo_scale=1.1,logo_pos_y=0.,ticket_gap=-30,
        **{recipes.META:dict(version=1,default=True,
            grid=dict(rows=5,row_counts_str='5,5,5,6,6',layout_mode='両端揃え (拡大縮小)',alignment='中央揃え'),
            timetable=dict(tt_font='keifont.ttf',grid_font='keifont.ttf',tt_columns=2,
                           tt_style=dict(artist_font=120,time_font=90,goods_font=95)),
            zones=dict(grid=dict(top=500,bottom=1180,width=1000),tt=dict(top=500,bottom=1180,width=1000)))})


def project(count=27,free=False):
    from datetime import date
    rows=[TimetableRowDraft(artist_name=f'Artist {i}',duration=20,goods_duration=60) for i in range(count)]
    p=ProjectDraft(title='NEW EVENT',subtitle='サブタイトルTEST0123',event_date=date(2026,11,21),
        venue_name='上野恩賜公園野外ステージ',open_time='10:20',start_time='10:30',
        tickets=[TicketDraft('Sチケット','¥6,000','前方エリア、指定グループ静止画撮影可能'),
                 TicketDraft('Aチケット','¥2,000','撮影不可'),TicketDraft('当日','各+¥1,000','')],
        ticket_notes=['※各ドリンク代別'],settings={'tt_font':'keifont.ttf','grid_font':'keifont.ttf','tt_columns':2,
            KEY:dict(enabled=False,free_viewing=free,free_text='ステージ前',free_notices='※時間変更あり\n※場所取り禁止')},
        grid_settings=dict(order=[r.artist_name for r in rows],rows=5,row_counts_str='5,5,5,5,5',layout_mode='レンガ (サイズ統一)',alignment='左揃え'))
    return p,rows


def test_capture_contains_no_event_facts_and_keeps_full_visual_recipe():
    p,rows=project();p.flyer_settings=recipe();before=deepcopy(p)
    data=recipes.capture(p,{'grid':Image.new('RGBA',(2400,1800))})
    encoded=json.dumps(data)
    assert 'NEW EVENT' not in encoded and 'Artist 0' not in encoded and '¥6,000' not in encoded
    assert data['date_font']=='keifont.ttf'
    assert data[recipes.META]['grid']['layout_mode']=='レンガ (サイズ統一)'
    assert 'grid' in data[recipes.META]['zones']
    assert p==before


@pytest.mark.parametrize('count',[6,12,27,40])
def test_apply_adapts_counts_but_preserves_design_and_new_event_data(count):
    p,rows=project(count);before=deepcopy(p)
    out=recipes.apply(p,rows,recipe())
    counts=[int(n) for n in out.grid_settings['row_counts_str'].split(',')]
    assert sum(counts)==count and all(n>0 for n in counts)
    assert out.grid_settings['layout_mode']=='両端揃え (拡大縮小)'
    assert out.settings['tt_style']['artist_font']==120
    assert out.title==p.title and out.tickets==p.tickets and out.grid_settings['order']==p.grid_settings['order']
    assert p==before
    if count==27:assert counts==[5,5,5,6,6]


def test_multipart_recipe_copies_only_grid_style_never_part_performers_or_times():
    p,rows=project(12)
    parts=[new_part(0,'10:20','10:30',[r.to_legacy_dict() for r in rows[:6]]),
           new_part(1,'16:00','16:30',[r.to_legacy_dict() for r in rows[6:]])]
    p.settings[KEY].update(enabled=True,count=2,parts=parts)
    out=recipes.apply(p,rows,recipe())
    for original,part in zip(parts,out.settings[KEY]['parts']):
        assert part['rows']==original['rows'] and part['start_time']==original['start_time']
        assert part['grid_settings']['layout_mode']=='両端揃え (拡大縮小)'
        assert sum(map(int,part['grid_settings']['row_counts'].split(',')))==6


@pytest.mark.parametrize('field,value',[('date_size',None),('time_size',999),('logo_scale',float('nan')),('time_font',12)])
def test_invalid_recipes_never_reach_widgets(field,value):
    data=recipe();data[field]=value
    if value is None:assert field not in recipes.decode(data)
    else:
        with pytest.raises(ValueError):recipes.decode(data)


def test_default_switch_and_new_recipe_are_one_mocked_transaction(monkeypatch):
    import database
    from repositories import template_repo
    db=Mock();monkeypatch.setattr(database,'SessionLocal',lambda:db)
    monkeypatch.setattr(template_repo,'get_by_name',lambda *a:None)
    monkeypatch.setattr(template_repo,'list_templates',lambda *a:[SimpleNamespace(name='old',data_json=json.dumps(recipe()))])
    update=Mock();create=Mock();monkeypatch.setattr(template_repo,'update_data',update);monkeypatch.setattr(template_repo,'create',create)
    recipes.save('new',recipe(),True)
    assert json.loads(update.call_args.args[2])[recipes.META]['default'] is False
    assert json.loads(create.call_args.args[2])[recipes.META]['default'] is True
    db.commit.assert_called_once()
    create.side_effect=RuntimeError('failed')
    with pytest.raises(RuntimeError):recipes.save('another',recipe(),True)
    db.rollback.assert_called_once();assert db.commit.call_count==1


@pytest.fixture
def render_sources(monkeypatch):
    from services import font_service,artist_service
    from constants import FONT_DIR
    import logic_grid,logic_timetable
    path=str(Path(FONT_DIR)/'keifont.ttf')
    if not Path(path).exists():pytest.skip('font unavailable')
    monkeypatch.setattr(font_service,'ensure_font_path',lambda _:path)
    monkeypatch.setattr(artist_service,'resolve_artists_in_order',lambda names,**kw:names)
    grid=Mock(side_effect=lambda *a,**kw:Image.new('RGBA',(2400,max(300,len(kw['row_counts'])*330)),'gray'))
    monkeypatch.setattr(logic_grid,'generate_grid_image',grid)
    monkeypatch.setattr(logic_timetable,'generate_timetable_image',lambda *a,**kw:Image.new('RGBA',(3600,2400),'gray'))
    return grid


@pytest.mark.parametrize('count,free',[(6,False),(12,False),(27,False),(40,False),(12,True)])
def test_finished_recipe_geometry_is_valid_across_counts_and_free_banner(render_sources,count,free):
    p,rows=project(count,free)
    output=production.render_package(p,rows,template=recipe())
    for variant,meta in output['metadata'].items():
        assert not layout.issues(meta)
        assert output['layout_reports'][variant]['ok']
        assert 0<=meta['bounds']['main'][0]['top']<meta['bounds']['main'][0]['bottom']<=1350
    assert render_sources.call_args.kwargs['is_brick_mode'] is False
    assert output['draft'].flyer_settings['date_font']=='keifont.ttf'
    assert p.flyer_settings=={}


def test_layout_does_not_mark_overcrowded_image_complete(render_sources):
    p,rows=project(100)
    with pytest.raises(ValueError,match='読|小さ|収|文字'):production.render_package(p,rows,template=recipe())


def test_saved_manual_settings_reproduce_both_finished_variants(render_sources):
    from services import font_service
    from utils.flyer_generator import create_flyer_image_shadow
    from utils.flyer_helpers import format_event_date
    from services.image_studio import png
    from models.flyer_keys import FLYER_KEY_REGISTRY
    from PIL import ImageChops
    import io
    p,rows=project(40)
    package=production.render_package(p,rows,template=recipe())
    saved=package['draft'];font=font_service.ensure_font_path('keifont.ttf')
    counts=list(map(int,saved.grid_settings['row_counts_str'].split(',')))
    sources={'grid':Image.new('RGBA',(2400,max(300,len(counts)*330)),'gray'),
             'tt':Image.new('RGBA',(3600,2400),'gray')}
    for variant,source in sources.items():
        styles={e.short_key:saved.flyer_settings.get(e.short_key,e.default) for e in FLYER_KEY_REGISTRY if e.persist}
        for k in styles:
            if k.endswith('_font'):styles[k]=font
        cfg=saved.settings[KEY]
        styles.update(event_multipart=False,event_free_viewing=cfg.get('free_viewing',False),event_free_text=cfg.get('free_text',''),event_free_notices=cfg.get('free_notices',''),
            content_scale_w=styles[variant+'_scale_w'],content_scale_h=styles[variant+'_scale_h'],content_pos_y=styles[variant+'_pos_y'])
        image,_=create_flyer_image_shadow(None,Image.open(io.BytesIO(package['logo'])),source,styles,
            format_event_date(saved.event_date,'EN'),saved.venue_name,saved.subtitle,saved.open_time,saved.start_time,
            [t.to_dict() for t in saved.tickets],saved.ticket_notes,font)
        expected=Image.open(io.BytesIO(package['images'][variant]))
        assert ImageChops.difference(image.convert('RGB'),expected.convert('RGB')).getbbox() is None


def test_manual_recipe_save_load_keeps_event_and_legacy_timetable_state(monkeypatch):
    from streamlit.testing.v1 import AppTest
    from services import template_service
    item=SimpleNamespace(id=7,name='標準',data_json=json.dumps(recipe()))
    monkeypatch.setattr(template_service,'list_templates',lambda:[item])
    save=Mock();monkeypatch.setattr(recipes,'save',save)
    code='''
import streamlit as st
from models import ProjectDraft,TicketDraft,TimetableRowDraft
from models.flyer_keys import FLYER_KEY_REGISTRY
from services import session_manager
from views.production_templates import render
if 'draft_project' not in st.session_state:
    session_manager.set_draft_project(ProjectDraft(title='KEEP THIS EVENT',tickets=[TicketDraft('KEEP','123','')],settings={'tt_columns':2},grid_settings={'order':['A','B']}))
    session_manager.set_draft_rows([TimetableRowDraft(artist_name='A'),TimetableRowDraft(artist_name='B')])
    st.session_state['tt_artists_order']=['SENTINEL']
    st.session_state['grid_layout_mode']='両端揃え (拡大縮小)'
    st.session_state['grid_rows']=5
    st.session_state['grid_row_counts_str']='5,5,5,6,6'
    for e in FLYER_KEY_REGISTRY:
        if e.persist:st.session_state['flyer_'+e.short_key]=e.default
render()
'''
    at=AppTest.from_string(code).run()
    at.text_input(key='recipe_name').input('新しい制作設定').run()
    at.checkbox(key='recipe_default').check().run()
    at.button(key='btn_recipe_save').click().run()
    assert not at.exception
    save.assert_called_once()
    assert save.call_args.args[0]=='新しい制作設定' and save.call_args.args[2] is True
    captured=save.call_args.args[1]
    assert captured[recipes.META]['grid']['layout_mode']=='両端揃え (拡大縮小)'
    assert 'KEEP THIS EVENT' not in json.dumps(captured)
    at.button(key='btn_recipe_load').click().run()
    assert not at.exception
    assert at.session_state['draft_project'].title=='KEEP THIS EVENT'
    assert at.session_state['draft_project'].tickets[0].name=='KEEP'
    assert at.session_state['tt_artists_order']==['SENTINEL']
    assert at.session_state['grid_layout_mode']=='両端揃え (拡大縮小)'


def test_ai_wizard_uses_standard_recipe_and_invalidates_old_preview(monkeypatch):
    from streamlit.testing.v1 import AppTest
    from services import template_service,artist_service,asset_service,production_intake
    from views import auto_production as view
    # Reuse the ordinary intake fixture; API traffic and all writes stay mocked.
    from test_auto_production import result,png
    item=SimpleNamespace(id=7,name='標準制作',data_json=json.dumps(recipe()))
    monkeypatch.setattr(template_service,'list_templates',lambda:[item])
    monkeypatch.setattr(view,'_settings',lambda:('key','code'))
    monkeypatch.setattr(view.st,'file_uploader',lambda *a,**kw:SimpleNamespace(name='tt.xlsx',getvalue=lambda:b'fixture') if kw.get('key')=='autoprod_document' else None)
    monkeypatch.setattr(production_intake,'extract_document',lambda *a:'text')
    monkeypatch.setattr(production_intake,'analyze',lambda *a:result())
    monkeypatch.setattr(artist_service,'list_artists',lambda:[SimpleNamespace(name='A'),SimpleNamespace(name='B')])
    monkeypatch.setattr(asset_service,'list_assets_by_type',lambda *a:[])
    generate=Mock(side_effect=lambda draft,rows,*a,**kw:dict(draft=draft,rows=rows,images={'grid':png(),'tt':png()},text='event',asset_ids={},layout_reports={'grid':{'ok':True}}))
    monkeypatch.setattr(production,'render_package',generate)
    at=AppTest.from_string('from views.auto_production import render\nrender()').run()
    at.text_area(key='autoprod_overview').input('公演概要').run()
    at.button(key='btn_autoprod_analyze').click().run()
    assert at.selectbox(key='autoprod_1_template').value==7
    at.checkbox(key='autoprod_1_confirmed').check().run()
    at.selectbox(key='autoprod_1_bg_mode').select('指定なし').run()
    at.selectbox(key='autoprod_1_logo_mode').select('イベント名をロゴにする').run()
    at.button(key='btn_autoprod_preview').click().run()
    assert not at.exception
    assert generate.call_args.kwargs['template']['date_font']=='keifont.ttf'
    assert at.button(key='btn_autoprod_create').disabled is False
    at.selectbox(key='autoprod_1_template').select(0).run()
    assert at.button(key='btn_autoprod_create').disabled is True


def test_large_existing_background_is_sampled_without_mutating_source():
    import io
    data=io.BytesIO();Image.new('RGB',(3200,3200),'navy').save(data,format='PNG');original=data.getvalue()
    out=production.open_background(original)
    assert max(out.size)<=2700 and out.width<=2160
    assert Image.open(io.BytesIO(original)).size==(3200,3200)


def test_extremely_long_ticket_is_not_silently_marked_readable(render_sources):
    p,rows=project(12);p.tickets[0].note='条件が非常に長い場合の検査'*100
    with pytest.raises(ValueError,match='文字が小さ|検査'):production.render_package(p,rows,template=recipe())


def test_part_specific_grid_designs_are_saved_without_part_event_data():
    p,rows=project(12)
    a,b=new_part(0,rows=[r.to_legacy_dict() for r in rows[:6]]),new_part(1,rows=[r.to_legacy_dict() for r in rows[6:]])
    a['grid_settings']=dict(rows=2,row_counts='3,3',layout_mode='レンガ (サイズ統一)',alignment='左揃え',font='keifont.ttf')
    b['grid_settings']=dict(rows=1,row_counts='6',layout_mode='両端揃え (拡大縮小)',alignment='中央揃え',font='keifont.ttf')
    b['color']='#123456'
    p.flyer_settings=recipe();p.settings[KEY].update(enabled=True,count=2,parts=[a,b])
    captured=recipes.capture(p)
    assert 'Artist 0' not in json.dumps(captured)
    out=recipes.apply(p,rows,captured)
    parts=out.settings[KEY]['parts']
    assert parts[0]['grid_settings']['layout_mode']=='レンガ (サイズ統一)'
    assert parts[1]['grid_settings']['layout_mode']=='両端揃え (拡大縮小)'
    assert parts[1]['color']=='#123456'


def test_full_width_subtitle_is_not_mistaken_for_date_column(monkeypatch):
    """Real renderer baselines depend on earlier font heights; shrinking can cascade."""
    from utils import flyer_generator
    def render(**args):
        s=args['styles'];subtitle=s.get('subtitle_size',60);date=s.get('date_size',95);time=s.get('time_size',70)
        def box(x,y,w,h,size=30):return dict(left=x,top=y,right=x+w,bottom=y+h,font_size=size)
        bounds=dict(
            subtitle=[box(540-658*subtitle/60/2,277-s.get('subtitle_pos_y',0),658*subtitle/60,58*subtitle/60,subtitle)],
            date=[box(330-435*date/95/2,342+(subtitle-60)+(date-95)*.2-s.get('date_pos_y',0),435*date/95,65*date/95,date)],
            time=[box(628,342+(subtitle-60)+(date-95)-s.get('time_pos_y',0),317,113*time/70,time)])
        return Image.new('RGBA',(1080,1350)),dict(bounds=bounds)
    monkeypatch.setattr(flyer_generator,'create_flyer_image_shadow',render)
    args=dict(styles=dict(subtitle_size=60,date_size=95,time_size=70),main_source=Image.new('RGBA',(1000,600)))
    _,meta,styles,_=layout.fit(args)
    assert not layout.issues(meta)
    assert [styles[k+'_size'] for k in ('subtitle','date','time')]==[60,95,70]
    assert meta['bounds']['date'][0]['top']>=meta['bounds']['subtitle'][0]['bottom']+8
    assert meta['bounds']['time'][0]['top']>=meta['bounds']['subtitle'][0]['bottom']+8
    assert meta['bounds']['date'][0]['right']<meta['bounds']['time'][0]['left']
    assert abs(meta['bounds']['date'][0]['top']-meta['bounds']['time'][0]['top'])<2
