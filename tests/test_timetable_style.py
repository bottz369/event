"""Typography geometry and shared normal/multipart draft controls, without writes."""
from unittest.mock import Mock
from PIL import Image, ImageDraw
import pytest
from models.timetable_style import DEFAULTS, normalize_style


def test_style_defaults_and_invalid_values_are_safe():
    assert normalize_style() == DEFAULTS
    assert normalize_style({'column_width':999,'time_font':'bad','goods_width':None})['column_width'] == 140
    assert normalize_style({'time_font':'bad'})['time_font'] == 100
    assert normalize_style({'custom_widths':'false'})['custom_widths'] is False
    assert normalize_style({'photo_cover':'true','blank_goods':1})['photo_cover'] is False
    assert normalize_style({'photo_cover':True,'blank_goods':True})['blank_goods'] is True


def test_photo_positions_are_bounded_independent_and_ignore_invalid_values():
    source = dict(photo_positions={'A': .35, 'B': 2, 'C': -1, 'D': float('nan'),
                                  'E': float('inf'), 'F': True, '': .2, 'G': None})
    style = normalize_style(source)
    assert style['photo_positions'] == {'A': .35, 'B': 1., 'C': 0.}
    style['photo_positions']['A'] = .9
    assert source['photo_positions']['A'] == .35
    assert normalize_style({'photo_positions': []}) == DEFAULTS


@pytest.mark.parametrize('blank,expected', [(False,'-'),(True,'')])
def test_absent_goods_can_stay_blank_without_hiding_real_goods(monkeypatch,blank,expected):
    import logic_timetable as logic
    captured=[]
    monkeypatch.setattr(logic,'draw_centered_text',lambda *a,**kw:captured.append(a[1]))
    image=Image.new('RGBA',(1740,150))
    for goods,place,wanted in [('', '', expected),('13:30 - 14:30','A','13:30 - 14:30 (A)')]:
        logic.draw_one_row(ImageDraw.Draw(image),image,0,0,
            ['13:00 - 13:30','終演後物販',goods,place],None,None,1740,140,2,
            style={'blank_goods':blank})
        assert captured[-1]==wanted


def test_cover_photo_fills_strip_and_skips_face_shrink_only_when_requested(monkeypatch):
    import io
    from PIL import ImageOps,ImageChops
    import logic_timetable as logic
    from services import face_framing
    photo=Image.new('RGB',(800,900),'white');data=io.BytesIO();photo.save(data,'PNG')
    monkeypatch.setattr(logic.requests,'get',lambda *a,**kw:Mock(status_code=200,content=data.getvalue()))
    protect=Mock(return_value=Image.new('RGBA',(1740,159),'black'))
    monkeypatch.setattr(face_framing,'fit_timetable',protect)
    cover=logic._load_and_fit_tt('fixture',1740,159,'artist.png',photo_cover=True)
    expected=ImageOps.fit(photo.convert('RGBA'),(1740,159),method=Image.Resampling.LANCZOS)
    assert ImageChops.difference(cover,expected).getbbox() is None
    protect.assert_not_called()
    logic._load_and_fit_tt('fixture',1740,159,'artist.png')
    protect.assert_called_once()


def test_cover_option_reaches_each_prefetched_photo(monkeypatch):
    import database
    import logic_timetable as logic
    db=Mock();artist=Mock(image_filename='artist.png')
    db.query.return_value.filter.return_value.first.return_value=artist
    monkeypatch.setattr(database,'get_image_url',lambda _: 'fixture')
    load=Mock(return_value=Image.new('RGBA',(100,50)))
    monkeypatch.setattr(logic,'_load_and_fit_tt',load)
    cache=logic._prefetch_tt_images([['10:00','A','','']],db,target_size=(100,50),photo_cover=True)
    assert cache['A'].size==(100,50)
    load.assert_called_once_with('fixture',100,50,'artist.png',photo_cover=True)


def test_vertical_cover_position_shows_upper_photo_without_narrowing_it(monkeypatch):
    import io
    import logic_timetable as logic
    photo = Image.new('RGB', (800, 900))
    draw = ImageDraw.Draw(photo)
    for y in range(900): draw.line((0,y,799,y), fill=(y//4,0,0))
    data=io.BytesIO();photo.save(data,'PNG')
    monkeypatch.setattr(logic.requests,'get',lambda *a,**kw:Mock(status_code=200,content=data.getvalue()))
    center=logic._load_and_fit_tt('fixture',800,150,photo_cover=True)
    upper=logic._load_and_fit_tt('fixture',800,150,photo_cover=True,photo_y=.35)
    photo_up=logic._load_and_fit_tt('fixture',800,150,photo_cover=True,photo_y=.55)
    assert center.size==upper.size==(800,150)
    assert upper.getpixel((400,75))[0] < center.getpixel((400,75))[0]
    assert photo_up.getpixel((400,75))[0] > center.getpixel((400,75))[0]
    assert upper.getchannel('A').getextrema()==(255,255)
    assert upper.getpixel((0,75)) == upper.getpixel((799,75))


def test_per_artist_position_does_not_move_other_timetable_photos(monkeypatch):
    import database
    import logic_timetable as logic
    db=Mock();db.query.return_value.filter.return_value.first.return_value=Mock(image_filename='artist.png')
    monkeypatch.setattr(database,'get_image_url',lambda _: 'fixture')
    load=Mock(return_value=Image.new('RGBA',(100,50)))
    monkeypatch.setattr(logic,'_load_and_fit_tt',load)
    logic._prefetch_tt_images([['10:00','A','',''],['10:20','B','','']],db,
        target_size=(100,50),photo_cover=True,photo_positions={'A':.35})
    assert load.call_args_list[0].kwargs==dict(photo_cover=True,photo_y=.35)
    assert load.call_args_list[1].kwargs==dict(photo_cover=True)


@pytest.mark.parametrize('columns,expected', [(1,(2800,420,2060,700)),(2,(1740,348,1198,522))])
def test_row_geometry_defaults_and_custom_text_widths(monkeypatch,columns,expected):
    import logic_timetable as logic
    width,time_w,goods_x,goods_w = expected
    captured=[]
    monkeypatch.setattr(logic,'draw_centered_text',lambda *a,**kw:captured.append((a,kw)))
    image=Image.new('RGBA',(width,150))
    logic.draw_one_row(ImageDraw.Draw(image),image,0,0,['10:00','終演後物販','12:00','B'],None,None,width,140,columns)
    assert captured[0][0][4] == time_w
    assert captured[2][0][2] == goods_x
    assert captured[2][0][4] == goods_w
    captured.clear()
    style=dict(DEFAULTS,custom_widths=True,time_width=25,goods_width=40,
               artist_font=150,time_font=80,goods_font=120)
    logic.draw_one_row(ImageDraw.Draw(image),image,0,0,['10:00','終演後物販','12:00','B'],None,None,width,140,columns,style=style)
    a,t,g=captured[1][0],captured[0][0],captured[2][0]
    assert t[2]+t[4] == a[2]
    assert a[2]+a[4] == g[2]
    assert a[7] == round(int(140*.45)*1.5)
    assert t[7] == round(int(140*.40)*.8)
    assert g[7] == round(int(140*.35)*1.2)


@pytest.mark.parametrize('columns,expected',[(1,2240),(2,2844)])
def test_renderer_adjusts_width_and_gap_for_all_rows(monkeypatch,columns,expected):
    import logic_timetable as logic
    import database
    db=Mock()
    monkeypatch.setattr(database,'SessionLocal',lambda:db)
    monkeypatch.setattr(logic,'st',None)
    monkeypatch.setattr(logic,'_prefetch_tt_images',lambda *a,**kw:{})
    calls=[]
    monkeypatch.setattr(logic,'draw_one_row',lambda *a,**kw:calls.append((a,kw)))
    rows=[['10:00','A','',''],['10:20','B','','']]
    style=dict(DEFAULTS,column_width=80,column_gap=60)
    result=logic.generate_timetable_image(rows,columns=columns,style=style,canvas_height=300)
    assert result.size == (expected,300)
    assert len(calls)==2
    assert all(c[1]['style']==style for c in calls)
    db.close.assert_called_once()


@pytest.mark.parametrize('multipart',[False,True])
def test_style_controls_persist_across_tabs_and_save_to_settings(app_test,monkeypatch,multipart):
    from tests.conftest import select_tab
    from views.workspace import TAB_TT,TAB_GRID
    from models.event_format import KEY,new_part
    from services import session_manager,project_service
    at=app_test.run()
    label=next(x for x in at.selectbox(key='ws_project_selector_label').options
               if x not in ('(選択してください)','➕ 新規プロジェクト作成'))
    at.selectbox(key='ws_project_selector_label').select(label).run()
    draft=at.session_state['draft_project']
    if multipart:
        part_rows=[r.to_legacy_dict() for r in at.session_state['draft_rows'] if not r.is_special_row]
        draft.settings[KEY]=dict(enabled=True,initialized=True,count=2,parts=[new_part(0,rows=part_rows),new_part(1)])
        at.session_state['draft_project']=draft
    select_tab(at,TAB_TT)
    at.slider(key='tt_style_artist_font').set_value(135).run()
    at.slider(key='tt_style_column_width').set_value(90).run()
    at.checkbox(key='tt_style_custom_widths').check().run()
    at.slider(key='tt_style_goods_width').set_value(40).run()
    at.checkbox(key='tt_style_photo_cover').check().run()
    photo_name=at.selectbox(key='tt_style_photo_artist').value
    at.slider(key='tt_style_photo_y_'+photo_name).set_value(35).run()
    at.checkbox(key='tt_style_blank_goods').check().run()
    assert not at.exception
    select_tab(at,TAB_GRID)
    select_tab(at,TAB_TT)
    assert at.slider(key='tt_style_artist_font').value==135
    assert at.slider(key='tt_style_goods_width').value==40
    assert at.checkbox(key='tt_style_photo_cover').value is True
    assert at.checkbox(key='tt_style_blank_goods').value is True
    def save_without_db():
        session_manager.sync_session_to_draft()
        return False  # Stop before image generation / actual persistence.
    monkeypatch.setattr(project_service,'save_active_project',save_without_db)
    at.button(key='btn_project_save').click().run()
    assert not at.exception
    style=at.session_state['draft_project'].settings['tt_style']
    assert style['artist_font']==135 and style['column_width']==90 and style['goods_width']==40
    assert style['photo_cover'] is True and style['blank_goods'] is True
    assert style['photo_positions'][photo_name]==.65
    at.button(key='btn_tt_style_reset').click().run()
    assert not at.exception
    assert at.session_state['tt_style']==DEFAULTS
