"""AI production: extraction, source-grounding, timing, insert-only persistence and UI."""
from copy import deepcopy
import datetime as dt
import io
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image

from models.event_format import KEY,schedule
from services import production_intake as intake,production_service as production


def event():
    return dict(event_name='rock field ULTRA LIVE',subtitle='TEST',event_date='2026-11-07',venue='TEST STAGE',venue_url='',
                open_time='10:00',start_time='10:30',tickets=[dict(name='VIP',price='¥5,000',note='限定100枚')],
                ticket_common_note='',free_texts=[dict(title='注意事項',body='場所取り禁止')],artists=['B','A'],
                free_viewing=True,free_text='ステージ前',free_notices='※時間変更の場合があります')


def part(name='1部',post=False):
    return dict(name=name,open_time='10:00',start_time='10:30',post_start='12:00' if post else '',post_end='13:00' if post else '',
                note='',transition_label='VIP入れ替え',rows=[
        dict(artist='A',start='10:30',end='10:50',goods_start='11:00',goods_end='12:00',place='A',post_goods=post,
             add_start='',add_end='',add_place='',evidence='10:30 - 10:50 A'),
        dict(artist='B',start='10:55',end='11:15',goods_start='',goods_end='',place='B',post_goods=False,
             add_start='',add_end='',add_place='',evidence='10:55 - 11:15 B')])


def result():return dict(event=event(),parts=[part()],questions=[],warnings=[])


def png():
    buf=io.BytesIO();Image.new('RGBA',(108,135),'navy').save(buf,format='PNG');return buf.getvalue()


def test_excel_extraction_keeps_columns_and_real_excel_times():
    from openpyxl import Workbook
    wb=Workbook();ws=wb.active;ws.title='1部'
    ws.append(['出演者','開始','終了','物販','控室'])
    ws.append(['A',dt.time(10,30),dt.time(10,50),'11:00 - 12:00','09:00 - 18:00'])
    data=io.BytesIO();wb.save(data);wb.close()
    text=intake.extract_document(data.getvalue(),'tt.xlsx')
    assert 'A\t10:30\t10:50\t11:00 - 12:00\t09:00 - 18:00' in text
    assert 'シート: 1部' in text


@pytest.mark.parametrize('encoding',['utf-8-sig','cp932'])
def test_csv_extraction_keeps_japanese_and_times(encoding):
    text='出演者,開始,終了\nグループA,10:30,10:50'
    assert intake.extract_document(text.encode(encoding),'tt.csv')==text


@pytest.mark.parametrize('data,name',[(b'', 'tt.pdf'),(b'bad','tt.xlsx'),(b'bad','tt.xls')])
def test_invalid_upload_is_rejected(data,name):
    with pytest.raises(ValueError):intake.extract_document(data,name)


def test_pdf_extraction_rejects_scans_and_encryption(monkeypatch):
    import pypdf
    reader=SimpleNamespace(is_encrypted=False,pages=[SimpleNamespace(extract_text=lambda **kw:'')])
    monkeypatch.setattr(pypdf,'PdfReader',lambda *a:reader)
    with pytest.raises(ValueError,match='画像だけ'):intake.extract_document(b'fixture','tt.pdf')
    reader.is_encrypted=True
    with pytest.raises(ValueError,match='パスワード'):intake.extract_document(b'fixture','tt.pdf')


@pytest.mark.parametrize('supplied',['','wrong'])
def test_analyze_checks_code_before_any_api_call(monkeypatch,supplied):
    post=Mock();monkeypatch.setattr(intake.requests,'post',post)
    with pytest.raises(ValueError):intake.analyze('overview','tt','key','secret',supplied)
    post.assert_not_called()


def test_analyze_is_one_structured_call_and_rejects_invented_evidence(monkeypatch):
    output=result()
    response=Mock(status_code=200)
    response.json.side_effect=lambda:{'choices':[{'finish_reason':'stop','message':{'content':json.dumps(output)}}]}
    post=Mock(return_value=response);monkeypatch.setattr(intake.requests,'post',post)
    text='10:30 - 10:50 A\n10:55 - 11:15 B'
    assert intake.analyze('overview',text,'key','secret','secret')['event']==event()
    payload=post.call_args.kwargs['json']
    assert payload['response_format']['json_schema']['strict'] is True
    assert payload['model']=='gpt-5-mini'
    output['parts'][0]['rows'][0]['start']='10:20'
    with pytest.raises(ValueError,match='根拠'):intake.analyze('overview',text,'key','secret','secret')
    assert post.call_count==2


def test_compile_preserves_reviewed_times_and_empty_goods_and_overview_grid_order():
    draft,rows=production.compile_plan(event(),[part()])
    assert draft.settings[KEY]['enabled'] is False
    assert rows[0].adjustment==5
    assert rows[0].goods_start_time=='11:00'
    assert rows[1].goods_duration==0
    assert draft.grid_settings['order']==['B','A']
    assert draft.tickets[0].price=='¥5,000'
    assert draft.event_date==dt.date(2026,11,7)


def test_multiple_selected_parts_remain_independent_and_names_preserved():
    a,b=part(),part('3部',post=True)
    b['open_time']='10:05'
    draft,rows=production.compile_plan(event(),[a,b],{'A':'Registered A'})
    cfg=draft.settings[KEY]
    assert cfg['enabled'] and cfg['count']==2
    assert [p['name'] for p in cfg['parts']]==['1部','3部']
    assert cfg['parts'][1]['open_time']=='10:05'
    assert cfg['parts'][0]['rows'][0]['ARTIST']=='Registered A'
    assert schedule(cfg['parts'][1])[0][0]['goods']=='12:00–13:00'
    assert cfg['parts'][0]['hide_transitions'] is True


@pytest.mark.parametrize('change',[
    lambda e,p:e.update(event_date=''),
    lambda e,p:p.update(start_time='10:20'),
    lambda e,p:p['rows'][1].update(start='10:40'),
    lambda e,p:p['rows'][0].update(end='10:30'),
    lambda e,p:p['rows'][0].update(goods_end=''),
    lambda e,p:p['rows'][0].update(post_goods=True),
    lambda e,p:p['rows'][0].update(add_start='14:00'),
])
def test_missing_or_inconsistent_fields_block_creation(change):
    e,p=event(),part();change(e,p)
    with pytest.raises(ValueError):production.compile_plan(e,[p])


def test_new_persistence_is_atomic_and_does_not_use_replace_or_delete(monkeypatch):
    import database
    from repositories import project_repo,timetable_repo
    draft,rows=production.compile_plan(event(),[part()])
    db=Mock();monkeypatch.setattr(database,'SessionLocal',lambda:db)
    stage=Mock(return_value=SimpleNamespace(id=99));insert=Mock()
    monkeypatch.setattr(project_repo,'stage_new_draft',stage)
    monkeypatch.setattr(timetable_repo,'add_new_project_rows',insert)
    replace=Mock(side_effect=AssertionError('replace forbidden'));monkeypatch.setattr(timetable_repo,'save_rows',replace)
    assert production.persist_new_project(draft,rows)==99
    db.commit.assert_called_once();db.close.assert_called_once();replace.assert_not_called()
    insert.side_effect=RuntimeError('failed')
    with pytest.raises(ValueError):production.persist_new_project(draft,rows)
    db.rollback.assert_called_once()
    assert db.commit.call_count==1


def test_insert_only_repository_preserves_zero_goods_and_cannot_replace_existing_rows():
    from repositories import timetable_repo
    from models import TimetableRowDraft
    db=Mock();query=db.query.return_value.filter.return_value;query.first.return_value=None
    timetable_repo.add_new_project_rows(db,99,[TimetableRowDraft(artist_name='A',goods_duration=0)])
    row=db.add_all.call_args.args[0][0]
    assert row.goods_duration==0
    assert timetable_repo._row_to_draft(row).goods_duration==0
    db.commit.assert_not_called()
    query.first.return_value=object()
    with pytest.raises(ValueError):timetable_repo.add_new_project_rows(db,99,[])
    assert db.add_all.call_count==1


def test_complete_package_uses_existing_renderers_and_contains_text(monkeypatch):
    from services import font_service,artist_service
    import logic_grid,logic_timetable
    from constants import FONT_DIR
    from pathlib import Path
    path=str(Path(FONT_DIR)/'keifont.ttf')
    if not Path(path).exists():pytest.skip('font unavailable')
    monkeypatch.setattr(font_service,'ensure_font_path',lambda _:path)
    monkeypatch.setattr(artist_service,'resolve_artists_in_order',lambda names,**kw:names)
    monkeypatch.setattr(logic_grid,'generate_grid_image',lambda *a,**kw:Image.new('RGBA',(1000,600),'gray'))
    monkeypatch.setattr(logic_timetable,'generate_timetable_image',lambda *a,**kw:Image.new('RGBA',(3600,2400),'gray'))
    draft,rows=production.compile_plan(event(),[part()])
    package=production.render_package(draft,rows,png())
    assert set(package['images'])=={'grid','tt'}
    assert Image.open(io.BytesIO(package['images']['grid'])).size==(1080,1350)
    assert 'VIP' in package['text'] and 'ステージ前' in package['text']
    assert package['draft'].id is None
    assert package['logo'] and package['asset_ids']=={}
    assert draft.flyer_settings=={}


@pytest.mark.parametrize('missing_times',[False,True])
def test_wizard_can_preview_without_any_project_or_writes_and_blocks_stale_save(app_test,monkeypatch,missing_times):
    from views import auto_production as view
    from services import artist_service,asset_service,template_service
    monkeypatch.setattr(template_service,'list_templates',lambda:[])
    monkeypatch.setattr(view,'_settings',lambda:('key','code'))
    original_uploader=view.st.file_uploader
    def uploader(*a,**kw):
        if kw.get('key')=='autoprod_document':return SimpleNamespace(name='tt.xlsx',getvalue=lambda:b'fixture')
        return original_uploader(*a,**kw)
    monkeypatch.setattr(view.st,'file_uploader',uploader)
    monkeypatch.setattr(intake,'extract_document',lambda *a:'10:30 - 10:50 A\n10:55 - 11:15 B')
    analyzed=result()
    if missing_times:analyzed['parts'][0].update(open_time='',start_time='')
    analyze=Mock(return_value=analyzed);monkeypatch.setattr(intake,'analyze',analyze)
    monkeypatch.setattr(artist_service,'list_artists',lambda:[SimpleNamespace(name='A'),SimpleNamespace(name='B')])
    monkeypatch.setattr(asset_service,'list_assets_by_type',lambda *a:[])
    persist=Mock();monkeypatch.setattr(production,'persist_new_project',persist)
    def render(draft,rows,*a):return dict(draft=draft,rows=rows,images={'grid':png(),'tt':png()},text='event',background=None,logo=None,failures=[],asset_ids={})
    generate=Mock(side_effect=render);monkeypatch.setattr(production,'render_package',generate)
    at=app_test.run()
    at.text_area(key='autoprod_overview').input('公演概要').run()
    at.text_input(key='autoprod_access').input('code').run()
    analyze.assert_not_called();persist.assert_not_called()
    at.button(key='btn_autoprod_analyze').click().run()
    assert not at.exception
    assert at.text_input(key='autoprod_1_part_0_open_time').value=='10:00'
    assert at.text_input(key='autoprod_1_part_0_start_time').value=='10:30'
    at.checkbox(key='autoprod_1_confirmed').check().run()
    at.selectbox(key='autoprod_1_bg_mode').select('指定なし').run()
    at.selectbox(key='autoprod_1_logo_mode').select('イベント名をロゴにする').run()
    at.button(key='btn_autoprod_preview').click().run()
    assert not at.exception
    generate.assert_called_once();persist.assert_not_called()
    assert at.button(key='btn_autoprod_create').disabled is False
    at.text_input(key='autoprod_1_venue').input('訂正した会場').run()
    assert at.button(key='btn_autoprod_create').disabled is True
    at.button(key='btn_autoprod_preview').click().run()
    assert at.button(key='btn_autoprod_create').disabled is False
    assert generate.call_count==2
    persist.assert_not_called()
    persist.return_value=99
    monkeypatch.setattr(view.session_manager,'reload_project',lambda _:False)
    at.button(key='btn_autoprod_create').click().run()
    assert not at.exception
    persist.assert_called_once()
    assert at.session_state[view.STATE]['project_id']==99
    at.run()
    persist.assert_called_once()

@pytest.mark.parametrize('mutate',[
    lambda r:r['parts'][0]['rows'].__setitem__(0,None),
    lambda r:r['parts'][0]['rows'][0].update(artist=''),
    lambda r:r.update(parts=[]),
    lambda r:r.update(questions='bad'),
])
def test_malformed_ai_output_cannot_reach_review_ui(monkeypatch,mutate):
    output=result();mutate(output)
    response=Mock(status_code=200)
    response.json.return_value={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(output)}}]}
    monkeypatch.setattr(intake.requests,'post',Mock(return_value=response))
    with pytest.raises(ValueError):intake.analyze('overview','10:30 - 10:50 A\n10:55 - 11:15 B','key','secret','secret')


def test_failed_commit_blocks_repeat_inserts_and_reuses_registered_assets(monkeypatch):
    from views import auto_production as view
    from services import asset_service
    draft,rows=production.compile_plan(event(),[part()])
    state={'preview_hash':'reviewed','package':dict(draft=draft,rows=rows,background=png(),logo=png(),
                                                asset_ids={'background':7})}
    monkeypatch.setattr(view.st,'session_state',{view.STATE:state})
    monkeypatch.setattr(view.st,'error',Mock())
    upload=Mock(return_value=SimpleNamespace(id=8));monkeypatch.setattr(asset_service,'upload_image_asset',upload)
    save=Mock(side_effect=ValueError('uncertain'));monkeypatch.setattr(production,'persist_new_project',save)
    view._create('reviewed')
    assert state['save_uncertain'] is True
    assert draft.flyer_settings['bg_id']==7 and draft.flyer_settings['logo_id']==8
    view._create('reviewed')
    upload.assert_called_once();save.assert_called_once()


def test_exact_spelling_wins_while_ambiguous_case_variants_still_require_review():
    registered=['One last bloom','One last Bloom','One Last Bloom']
    assert production.match_names(['One last bloom','ONE LAST BLOOM'],registered)=={'One last bloom':'One last bloom'}


def test_27_artist_input_keeps_overview_order_two_gaps_and_pre_live_goods():
    e=event();e['artists']=[f'Artist {i}' for i in range(27)]
    e['artists'][0]='Short name'
    p=part();p['rows']=[]
    minute=630
    for i in range(27):
        fmt=lambda n:f'{n//60:02d}:{n%60:02d}'
        row=deepcopy(part()['rows'][0])
        row.update(artist=f'Artist {i}',start=fmt(minute),end=fmt(minute+20),goods_start='09:00',goods_end='10:00')
        p['rows'].append(row)
        minute+=20+(5 if i in (8,16) else 0)
    draft,rows=production.compile_plan(e,[p],{'Short name':'Artist 0'})
    assert len(rows)==27
    assert [i for i,r in enumerate(rows) if r.adjustment]==[8,16]
    assert sum(r.adjustment for r in rows)==10
    assert draft.grid_settings['row_counts_str']=='5,5,5,6,6'
    assert draft.grid_settings['order']==[f'Artist {i}' for i in range(27)]
    assert rows[0].goods_start_time=='09:00'


def test_three_ticket_lines_and_drink_note_fit_finished_canvas(monkeypatch):
    from services import font_service,artist_service
    import logic_grid,logic_timetable
    import utils.flyer_generator as compositor
    from constants import FONT_DIR
    from pathlib import Path
    path=str(Path(FONT_DIR)/'keifont.ttf')
    if not Path(path).exists():pytest.skip('font unavailable')
    monkeypatch.setattr(font_service,'ensure_font_path',lambda _:path)
    monkeypatch.setattr(artist_service,'resolve_artists_in_order',lambda names,**kw:names)
    monkeypatch.setattr(logic_grid,'generate_grid_image',lambda *a,**kw:Image.new('RGBA',(1000,600),'gray'))
    monkeypatch.setattr(logic_timetable,'generate_timetable_image',lambda *a,**kw:Image.new('RGBA',(3600,2400),'gray'))
    original=compositor.draw_text_with_shadow
    captured=[]
    def draw(canvas,text,*args,**kwargs):
        bounds=kwargs.setdefault('layout_bounds',{})
        height=original(canvas,text,*args,**kwargs)
        if text=='※各ドリンク代別':captured.append(dict(bounds))
        return height
    monkeypatch.setattr(compositor,'draw_text_with_shadow',draw)
    e=event();e.update(free_viewing=False,ticket_common_note='※各ドリンク代別',tickets=[
        dict(name='Sチケット',price='¥6,000',note='前方エリア、指定グループ静止画撮影可能'),
        dict(name='Aチケット',price='¥2,000',note='撮影不可'),dict(name='当日',price='各+¥1,000',note='')])
    draft,rows=production.compile_plan(e,[part()])
    package=production.render_package(draft,rows)
    # Each variant is measured twice before its final rendering.
    for bounds in (captured[2],captured[5]):assert 1100<bounds['top']<bounds['bottom']<1330
    assert package['draft'].flyer_settings['ticket_gap']<0


def test_default_logo_uses_only_unique_exact_basic_asset(monkeypatch):
    from services import asset_service
    assets=[SimpleNamespace(id=1,name='ROCKFIELD ULTRA LIVE - BASIC'),SimpleNamespace(id=2,name='OTHER')]
    monkeypatch.setattr(asset_service,'list_assets_by_type',lambda kind:assets)
    read=Mock(return_value=b'original-logo');monkeypatch.setattr(asset_service,'read_image_asset',read)
    assert production.read_default_logo()==b'original-logo'
    read.assert_called_once_with(1)
    assets.append(SimpleNamespace(id=3,name='ROCKFIELD ULTRA LIVE - BASIC'))
    with pytest.raises(ValueError):production.read_default_logo()
    assert read.call_count==1


def table_text(count=27):
    lines=['シート: Sheet1','START\tEND\tグループ名\t持ち時間\t物販開始\t物販終了\t物販時間\t物販場所\t']
    for i in range(count):
        start=600+i*20;end=start+20
        clock=lambda n:f'{n//60:02d}:{n%60:02d}'
        lines.append(f'{clock(start)}\t{clock(end)}\tArtist {i}\t20\t11:00\t12:00\t60\tA\t2026-11-21 00:00:00')
    lines.insert(3,'10:20\t10:25\t調整\t5\t\t\t\t\t')
    return '\n'.join(lines)


def test_named_excel_columns_use_exact_source_rows_not_model_parts(monkeypatch):
    from services.production_table import single_table
    text=table_text();parsed=single_table(text)
    assert len(parsed['rows'])==27
    assert parsed['rows'][0]['artist']=='Artist 0' and parsed['rows'][-1]['artist']=='Artist 26'
    assert parsed['rows'][0]['goods_start']=='11:00'
    output=result();output.pop('parts');output['event']['open_time']='';output['event']['start_time']=''
    response=Mock(status_code=200)
    response.json.return_value={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(output)}}]}
    post=Mock(return_value=response);monkeypatch.setattr(intake.requests,'post',post)
    answer=intake.analyze('OPEN▶09:30 START▶10:00',text,'key','code','code')
    assert len(answer['parts'])==1 and len(answer['parts'][0]['rows'])==27
    assert answer['parts'][0]['open_time']=='09:30' and answer['parts'][0]['start_time']=='10:00'
    assert 'parts' not in post.call_args.kwargs['json']['response_format']['json_schema']['schema']['properties']
    assert any('27出演行' in warning for warning in answer['warnings'])


@pytest.mark.parametrize('change',[
    lambda text:text+'\nシート: Sheet2',
    lambda text:text.replace('START\tEND','第2部 START\tEND'),
    lambda text:text.replace('物販場所\t','物販場所\t追加開始'),
    lambda text:text.replace('11:00\t12:00','終演後物販\t12:00'),
    lambda text:text.replace('10:00\t10:20','不明\t10:20'),
])
def test_ambiguous_or_unsupported_tables_keep_existing_ai_route(change):
    from services.production_table import single_table
    assert single_table(change(table_text())) is None


@pytest.mark.parametrize('count,rows,expected',[(0,0,'0部'),(7,2,'7部'),(1,101,'101出演行')])
def test_invalid_part_count_and_actual_row_limit_have_distinct_messages(monkeypatch,count,rows,expected):
    output=result();output['parts']=[deepcopy(part()) for _ in range(count)]
    if count:output['parts'][0]['rows']=[deepcopy(part()['rows'][0]) for _ in range(rows)]
    response=Mock(status_code=200)
    response.json.return_value={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(output)}}]}
    monkeypatch.setattr(intake.requests,'post',Mock(return_value=response))
    with pytest.raises(ValueError,match=expected):intake.analyze('overview','source','key','code','code')


def test_oversized_structured_table_is_rejected_before_paid_analysis(monkeypatch):
    from services.production_table import single_table
    text=table_text(1)
    row=text.splitlines()[2]
    text+='\n'+'\n'.join([row]*100)
    assert len(single_table(text)['rows'])==101
    post=Mock();monkeypatch.setattr(intake.requests,'post',post)
    with pytest.raises(ValueError,match='101出演行'):intake.analyze('overview',text,'key','code','code')
    post.assert_not_called()
