"""Excel imports preserve source timing and require explicit, draft-only application."""
from copy import deepcopy
from datetime import time
import io
from unittest.mock import Mock

import pytest
from models.event_format import KEY, schedule
from models.project import ProjectDraft
from models.timetable import TimetableRowDraft
from services.timetable_excel_service import parse_rows, read_excel, sheet_names, _minute


@pytest.fixture
def table():
    return [
        ['START ', 'END', 'グループ名', '持ち時間', '物販開始', '物販終了', '物販時間', '物販場所', '控室'],
        [time(10,30),time(10,50),'Alpha',20,time(11),time(12),60,'A','09:00 - 09:30'],
        [time(10,50),time(10,55),'調整',5],
        ['10:55','11:20','Beta',25,'10:00','11:00',60,'B'],
        ['11:20','11:30','調整',10],
        ['11:30','11:50','Gamma',20,None,None,0,''],
    ]


def workbook_bytes(table):
    # In-memory test input only, never an authored deliverable or production write.
    from openpyxl import Workbook
    book=Workbook();sheet=book.active;sheet.title='Timetable'
    for row in table:sheet.append(row)
    book.create_sheet('Notes').append(['unused'])
    out=io.BytesIO();book.save(out);book.close()
    return out.getvalue()


def test_named_columns_keep_timing_and_ignore_room_column(table):
    result=parse_rows(table)
    part=result['parts'][0]
    calculated,_=schedule(part)
    assert [r['ARTIST'] for r in calculated]==['Alpha','Beta','Gamma']
    assert [(r['start'],r['end']) for r in calculated]==[('10:30','10:50'),('10:55','11:20'),('11:30','11:50')]
    assert [r['ADJUSTMENT'] for r in calculated]==[5,10,0]
    assert calculated[0]['goods']=='11:00–12:00'
    assert calculated[1]['goods']=='10:00–11:00'
    assert calculated[2]['goods']==''
    assert not part['open_time'] and part['start_time']=='10:30'
    assert len(result['warnings'])==2
    assert all(not r['ADD_GOODS_START'] for r in part['rows'])


def test_workbook_sheet_selection_and_trailing_date_is_ignored(table):
    from datetime import datetime
    table[0][-1]=''; table[1][-1]=datetime(2026,11,21)
    data=workbook_bytes(table)
    assert sheet_names(data)==['Timetable','Notes']
    assert len(read_excel(data,'Timetable')['parts'][0]['rows'])==3
    with pytest.raises(ValueError,match='ヘッダ'):
        read_excel(data,'Notes')
    with pytest.raises(ValueError,match='シート'):
        read_excel(data,'unknown')


@pytest.mark.parametrize('value,expected',[(time(10,30),630),('１０:３０',630),('9:05',545),(0.5,720),('10:30:00',630)])
def test_time_encodings(value,expected):
    assert _minute(value,'time')==expected


@pytest.mark.parametrize('value',[None,'25:00','10:60','=A1',time(10,30,1),0.50001])
def test_invalid_or_uncached_formula_time_rejected(value):
    with pytest.raises(ValueError):_minute(value,'time')


@pytest.mark.parametrize('change',[
    lambda t:t[1].__setitem__(3,25),
    lambda t:t[1].__setitem__(6,90),
    lambda t:t[1].__setitem__(0,None),
    lambda t:t[1].__setitem__(2,None),
    lambda t:t[1].__setitem__(5,None),
    lambda t:t[3].__setitem__(0,'10:40'),
    lambda t:t[3].__setitem__(5,'09:00'),
    lambda t:t[2].extend(['11:00','12:00',60,'A']),
    lambda t:t[0].append('出演開始'),
    lambda t:t.append(t[0].copy()),
])
def test_ambiguous_or_invalid_rows_never_silently_import(table,change):
    change(table)
    with pytest.raises(ValueError):parse_rows(table)


@pytest.mark.parametrize('data',[b'',b'not excel'])
def test_invalid_workbooks(data):
    with pytest.raises(ValueError):sheet_names(data)


def test_missing_goods_is_allowed_but_one_header_is_not():
    result=parse_rows([['出演開始','出演終了','アーティスト'],['10:30','10:50','A']])
    assert result['parts'][0]['rows'][0]['GOODS_DURATION']==0
    with pytest.raises(ValueError):
        parse_rows([['START','END','グループ名','物販開始'],['10:30','10:50','A','11:00']])


def test_apply_preparation_keeps_open_design_order_and_comingsoon(table):
    from views.excel_import import prepare_apply
    result=parse_rows(table);original=deepcopy(result)
    draft=ProjectDraft(open_time='10:20',grid_settings={'order':['Beta','Alpha']},flyer_settings={'logo_scale':1.2})
    rows=[TimetableRowDraft(artist_name='Beta',grid_no=1,is_comingsoon=True,is_grid_hidden=True),TimetableRowDraft(artist_name='Alpha',grid_no=2)]
    prepared=prepare_apply(result,draft,rows)
    raw=prepared['parts'][0]['rows']
    assert prepared['parts'][0]['open_time']=='10:20'
    assert [r['GRID_NO'] for r in raw]==[2,1,3]
    assert raw[1]['COMINGSOON'] and raw[1]['GRID_HIDDEN']
    assert result==original and draft.flyer_settings=={'logo_scale':1.2}
    draft.open_time='12:00'
    with pytest.raises(ValueError,match='OPEN'):prepare_apply(result,draft,rows)


def test_preview_does_not_apply_until_clicked_and_invalidates_on_sheet_change(app_test,monkeypatch,table):
    from views import excel_import
    from services import artist_service,project_service
    from tests.conftest import select_tab
    from views.workspace import TAB_TT
    data=workbook_bytes(table)
    original_uploader=excel_import.st.file_uploader
    monkeypatch.setattr(excel_import.st,'file_uploader',lambda *a,**k:
        type('Upload',(),{'getvalue':lambda self:data})() if k.get('type')==['xlsx'] else original_uploader(*a,**k))
    monkeypatch.setattr(artist_service,'list_artists',lambda:[])
    save=Mock(side_effect=AssertionError('preview must not save'))
    monkeypatch.setattr(project_service,'save_active_project',save)
    at=app_test.run()
    labels=at.selectbox(key='ws_project_selector_label').options
    label=next(x for x in labels if x not in ('(選択してください)','➕ 新規プロジェクト作成'))
    at.selectbox(key='ws_project_selector_label').select(label).run()
    select_tab(at,TAB_TT)
    pid=at.session_state['ws_active_project_id'];key=f'excel_import_{pid}'
    before=deepcopy(at.session_state['draft_project']);rows=deepcopy(at.session_state['draft_rows'])
    # The source has no OPEN, so supply a valid current project OPEN in session only.
    at.session_state['draft_project'].open_time='10:00'
    at.session_state['tt_open_time']='10:00'
    before.open_time='10:00'
    at.button(key=key+'_parse').click().run()
    assert not at.exception
    assert at.session_state['draft_project']==before
    assert at.session_state['draft_rows']==rows
    from hashlib import sha256
    sheet_key=key+'_sheet_'+sha256(data).hexdigest()
    at.selectbox(key=sheet_key).select('Notes').run()
    assert not any(b.key==key+'_apply' for b in at.button)
    at.selectbox(key=sheet_key).select('Timetable').run()
    at.button(key=key+'_apply').click().run()
    assert not at.exception
    after=at.session_state['draft_project']
    assert after.open_time=='10:00' and after.start_time=='10:30'
    assert not after.settings[KEY]['enabled']
    assert after.flyer_settings==before.flyer_settings and after.tickets==before.tickets
    assert [r.artist_name for r in at.session_state['draft_rows']]==['Alpha','Beta','Gamma']
    assert [r.adjustment for r in at.session_state['draft_rows']]==[5,10,0]
    save.assert_not_called()


def test_upload_size_limit_and_zip_expansion_limit(monkeypatch):
    import zipfile
    from services import timetable_excel_service as service
    monkeypatch.setattr(service,'MAX_UPLOAD',3)
    with pytest.raises(ValueError,match='10MB'):sheet_names(b'abcd')
    monkeypatch.setattr(service,'MAX_UPLOAD',10*1024*1024)
    fake=Mock();fake.__enter__=Mock(return_value=fake);fake.__exit__=Mock(return_value=False)
    fake.infolist.return_value=[type('Item',(),dict(file_size=41*1024*1024))()]
    monkeypatch.setattr(zipfile,'ZipFile',lambda *_:fake)
    with pytest.raises(ValueError,match='展開後'):sheet_names(b'fixture')


def test_preview_replaces_multipart_only_on_apply(monkeypatch,table):
    from views import excel_import
    from services import session_manager
    from models.event_format import new_part
    draft=ProjectDraft(id=999,open_time='10:00',start_time='10:30',settings={KEY:dict(enabled=True,count=2,parts=[new_part(0),new_part(1)])},flyer_settings={'logo_scale':1.5})
    class State(dict):
        __getattr__ = dict.__getitem__
        __setattr__ = dict.__setitem__
    state=State(draft_project=draft,draft_rows=[],ws_active_project_id=999,tt_editor_key=0)
    monkeypatch.setattr(session_manager.st,'session_state',state)
    monkeypatch.setattr(excel_import.st,'toast',Mock())
    excel_import.apply_preview(parse_rows(table))
    assert not draft.settings[KEY]['enabled']
    assert draft.flyer_settings=={'logo_scale':1.5}
    assert len(state['draft_rows'])==3
    assert state['tt_unsaved_changes'] is True
