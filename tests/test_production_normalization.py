"""Keep original lineup order and normalize ticket fields before rendering/persistence."""
from copy import deepcopy
import json
from unittest.mock import Mock

import pytest
from services import production_normalization as clean,production_intake as intake,production_service as production


@pytest.mark.parametrize('source,expected',[
    ('((撮影不可))','撮影不可'),('（(撮影不可)）','撮影不可'),
    ('前方エリア（指定グループのみ）','前方エリア（指定グループのみ）'),
    ('(前方)(撮影可)','(前方)(撮影可)'),('(未完','(未完'),
])
def test_outer_brackets_only(source,expected):assert clean.bare_note(source)==expected


@pytest.mark.parametrize('source',['撮影不可','(撮影不可)','（(撮影不可)）'])
def test_renderer_wrapper_is_idempotent(source):assert clean.ticket_note_text(source)=='(撮影不可)'


def test_normalize_drink_to_separate_common_field_without_price_change():
    event=dict(artists=['A'],tickets=[
        dict(name='Sチケット',price='¥6,000',note='((前方エリア、指定グループ静止画撮影可能))'),
        dict(name='Aチケット',price='¥2,000',note='（撮影不可）'),
        dict(name='当日',price='各+¥1,000',note='（※各ドリンク代別）')],ticket_common_note='')
    original=deepcopy(event);out=clean.normalize_event(event)
    assert [t['price'] for t in out['tickets']]==['¥6,000','¥2,000','各+¥1,000']
    assert out['tickets'][0]['note']=='前方エリア、指定グループ静止画撮影可能'
    assert out['tickets'][1]['note']=='撮影不可' and out['tickets'][2]['note']==''
    assert out['ticket_common_note']=='※各ドリンク代別'
    assert clean.normalize_event(out)==out and event==original


@pytest.mark.parametrize('field,text',[
    ('note','撮影不可 / ※各ドリンク代別'),('note','撮影不可（※各ドリンク代別）'),
    ('price','¥2,000 (※各ドリンク代別)'),
])
def test_embedded_common_note_is_moved_and_deduplicated(field,text):
    ticket=dict(name='A',price='¥2,000',note='撮影不可');ticket[field]=text
    out=clean.normalize_event(dict(tickets=[ticket],ticket_common_note='※各ドリンク代別'))
    assert out['tickets'][0]==dict(name='A',price='¥2,000',note='撮影不可')
    assert out['ticket_common_note']=='※各ドリンク代別'


@pytest.mark.parametrize('note',[
    'VIPのみドリンク代不要','ドリンク代別（VIPのみ不要）','Sチケットは1D込み',
    '撮影可（VIP対象、ドリンク代別、特典あり）',
])
def test_ticket_specific_conditions_are_never_reclassified_as_common(note):
    out=clean.normalize_event(dict(tickets=[dict(name='VIP',price='¥5,000',note=note)],ticket_common_note=''))
    assert out['tickets'][0]['note']==note and out['ticket_common_note']==''


def test_raw_overview_lineup_overrides_reordered_ai_list():
    source='【公演概要】\n■出演者\n花いろは\nESTLINK\nOne Last Bloom\nソラネルカンパー\n\n■チケット・入場に関して\n入場順'
    out=clean.normalize_event(dict(artists=['One Last Bloom','花いろは'],tickets=[],ticket_common_note=''),source)
    assert out['artists']==['花いろは','ESTLINK','One Last Bloom','ソラネルカンパー']


def test_order_uses_unique_roster_matches_and_typo_recovery_not_timetable_order():
    overview=['花いろは','ESTLINK','One Last Bloom','ソラネルカンパー','蛍']
    roster=['蛍','One last bloom','花いろは','ソラネルカンパニー','ESTLINK☆']
    order,report=clean.grid_order(overview,roster)
    assert order==['花いろは','ESTLINK☆','One last bloom','ソラネルカンパニー','蛍']
    assert report['source']=='公演概要の出演者順' and not report['unlisted']
    assert len(report['matched'])==3


def test_ambiguous_names_are_not_silently_pushed_to_end():
    with pytest.raises(ValueError,match='一意'):
        clean.grid_order(['ONE LAST BLOOM'],['One Last Bloom','One last bloom'])
    order,report=clean.grid_order(['A'],['B','A'])
    assert order==['A','B'] and report['unlisted']==['B']
    order,report=clean.grid_order([],['B','A'])
    assert order==['B','A'] and report['source']=='タイムテーブル出演順'


def test_analysis_normalizes_model_output_and_preserves_raw_lineup(monkeypatch):
    from test_auto_production import result
    output=result();output['event']['artists']=['A','B']
    output['event']['tickets'][0]['note']='((限定100枚))'
    response=Mock(status_code=200)
    response.json.return_value={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(output)}}]}
    monkeypatch.setattr(intake.requests,'post',Mock(return_value=response))
    out=intake.analyze('■出演者\nB\nA\n■料金\nVIP','10:30 - 10:50 A\n10:55 - 11:15 B','key','code','code')
    assert out['event']['artists']==['B','A']
    assert out['event']['tickets'][0]['note']=='限定100枚'


def test_compiler_reconciles_order_and_common_notes_even_after_manual_field_edits():
    from test_auto_production import event,part
    e,p=event(),part()
    e['artists']=['b','A'];e['tickets']=[dict(name='当日',price='各+¥1,000',note='(※各ドリンク代別)')]
    e['ticket_common_note']=''
    draft,rows=production.compile_plan(e,[p])
    assert draft.grid_settings['order']==['B','A']
    assert [r.artist_name for r in rows]==['A','B']
    assert draft.ticket_notes==['※各ドリンク代別'] and draft.tickets[0].note==''
    assert draft.settings['production_order']['source']=='公演概要の出演者順'


def test_render_and_summary_never_double_wrap_existing_notes(monkeypatch):
    import utils.flyer_generator as compositor
    from utils.text_generator import build_event_summary_text
    from constants import FONT_DIR
    from pathlib import Path
    path=str(Path(FONT_DIR)/'keifont.ttf')
    texts=[];original=compositor.draw_text_with_shadow
    def draw(canvas,text,*args,**kwargs):texts.append(text);return original(canvas,text,*args,**kwargs)
    monkeypatch.setattr(compositor,'draw_text_with_shadow',draw)
    from models.flyer_keys import FLYER_KEY_REGISTRY
    styles={e.short_key:e.default for e in FLYER_KEY_REGISTRY if e.persist}
    compositor.create_flyer_image_shadow(None,None,None,styles,'','','','10:20','10:30',
        [dict(name='A',price='¥2,000',note='（(撮影不可)）')],[],path)
    assert 'A ¥2,000 (撮影不可)' in texts
    text=build_event_summary_text('event','',None,'','','10:20','10:30',
        [dict(name='A',price='¥2,000',note='（(撮影不可)）')],[],[],[])
    assert '(撮影不可)' in text and '((撮影不可))' not in text and '（(' not in text


def test_single_part_times_recovered_without_mutating_source():
    parts=[dict(open_time='',start_time='',rows=[])]
    out=clean.normalize_parts(parts,dict(open_time='10:20',start_time='10:30'))
    assert out[0]['open_time']=='10:20' and out[0]['start_time']=='10:30'
    assert parts[0]['open_time']==''


def test_times_recovered_from_explicit_overview_only():
    parts=[dict(open_time='',start_time='')]
    out=clean.normalize_parts(parts,{},'■時間\nOPEN▶１０：２０\nSTART▶10:30')
    assert out[0]==dict(open_time='10:20',start_time='10:30')
    assert clean.normalize_parts(parts,{},'出演 10:30〜10:50')==parts
    assert clean.normalize_parts(parts,{},'OPEN 10:00 / OPEN 11:00')==parts


def test_per_part_times_preserved_and_multi_part_never_inherits_global():
    parts=[dict(open_time='11:00',start_time='11:30')]
    assert clean.normalize_parts(parts,dict(open_time='10:00',start_time='10:30'))==parts
    parts=[dict(open_time='',start_time=''),dict(open_time='',start_time='')]
    assert clean.normalize_parts(parts,dict(open_time='10:00',start_time='10:30'),'OPEN 10:00 START 10:30')==parts
