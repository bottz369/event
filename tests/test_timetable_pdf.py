"""Read-only PDF import regressions: timing parity, column isolation and explicit apply."""
from copy import deepcopy
import pytest
from services.timetable_pdf_service import parse_layout, read_pdf, match_artists
from models.event_format import KEY, schedule


def artist(start,end,num,name,minutes,goods):
    return f" {start} - {end} {num} 】 (6人) {name} ({minutes})".ljust(54)+goods.ljust(30)+"控室"


def goods(start,end,room_start="09:30",room_end="12:20"):
    return " "*57+(f"{start} - {end}").ljust(21)+f"{room_start} - {room_end}"


@pytest.fixture
def layout():
    return "\n".join([
        "公演日 2026.11.7 会場 TEST",
        "    1部   10:00 / START 10:30 (30) 公開リハなし",
        " OPEN",
        " 10:25 - 10:30 VIP受け入れ開始 (5)",
        artist("10:30","10:50",1,"Alpha",20,"並行 A"),
        goods("11:00","12:00"),
        " 10:50 - 10:55 VIP入れ替え (5)",
        artist("10:55","11:15",2,"Beta",20,"並行 B ※2組同時"),
        goods("11:30","12:30","09:55","12:45"),
        " 11:15 - 11:25 特典会準備 (10)",
        " 11:25 - 12:55 終演後特典会 (90)",
        " 12:55 - 17:30 2部準備 (275)",
        "    2部".ljust(54)+"17:25 公開リハーサル(5分)",
        " OPEN    17:30 / START 17:50 (20) 17:30 公開リハーサル(5分)",
        artist("17:50","18:15",1,"Gamma",25,"終演後特典会"),
        " "*78+"17:40 - 21:30",
        " 18:15 - 18:25 特典会準備 (10)",
        " 18:25 - 19:55 終演後特典会 (90)",
        " 19:55 - 21:00 退館準備 (65)",
    ])


def test_import_preserves_stage_goods_and_excludes_dressing(layout):
    result=parse_layout(layout)
    first,second=result["parts"]
    rows,_=schedule(first)
    assert [(r["start"],r["end"]) for r in rows] == [("10:30","10:50"),("10:55","11:15")]
    assert first["rows"][0]["ADJUSTMENT"] == 5
    assert first["rows"][0]["GOODS_START_MANUAL"] == "11:00"
    assert first["rows"][0]["GOODS_DURATION"] == 60
    assert first["rows"][0]["PLACE"] == "A"
    assert all(not r["ADD_GOODS_START"] for p in result["parts"] for r in p["rows"])
    assert second["rows"][0]["IS_POST_GOODS"]
    assert schedule(second)[0][0]["goods"] == "18:25–19:55"
    assert second["start_time"] == "17:50"
    assert "17:25 公開リハーサル" in second["note"]
    assert "控室" not in str(result)
    assert "VIP受け入れ" in first["note"]
    assert any("2組同時" in warning for warning in result["warnings"])


@pytest.mark.parametrize("change", [
    lambda s:s.replace("Alpha (20)","Alpha (25)"),
    lambda s:s.replace(goods("11:00","12:00")," "*78+"09:30 - 12:20"),
    lambda s:s.replace("START 10:30","START 10:20"),
    lambda s:s.replace("Gamma (25)","Gamma (不明)"),
    lambda s:s.replace("    2部", "    3部"),
    lambda s:s+"\n    3部",
])
def test_incomplete_or_ambiguous_import_fails_instead_of_guessing(layout,change):
    with pytest.raises(ValueError):
        parse_layout(change(layout))


def test_artist_matching_uses_only_unique_normalized_names(layout):
    result=parse_layout(layout)
    original=deepcopy(result)
    matched=match_artists(result,["AL PHA","Beta 2","GAMMA"])
    assert [r["ARTIST"] for r in matched["parts"][0]["rows"]] == ["AL PHA","Beta"]
    assert matched["unmatched"] == ["Beta"]
    ambiguous=match_artists(result,["Alpha","ALPHA"])
    assert "Alpha" in ambiguous["unmatched"]
    assert result == original


@pytest.mark.parametrize("data",[b"",b"bad PDF",b"x"*(10*1024*1024+1)])
def test_invalid_and_oversized_uploads_report_errors(data):
    with pytest.raises(ValueError):
        read_pdf(data)


def test_pdf_preview_requires_apply_and_preserves_normal_rows_and_styles(app_test,layout,monkeypatch):
    from tests.conftest import select_tab
    from views.workspace import TAB_TT
    from services import timetable_pdf_service as service
    from views import pdf_import
    monkeypatch.setattr(pdf_import.st,"file_uploader",lambda *a,**k:type("Upload",(),{"getvalue":lambda self:b"fixture"})())
    monkeypatch.setattr(service,"read_pdf",lambda data:parse_layout(layout))
    at=app_test.run()
    label=next(x for x in at.selectbox(key="ws_project_selector_label").options
               if x not in ("(選択してください)","➕ 新規プロジェクト作成"))
    at.selectbox(key="ws_project_selector_label").select(label).run()
    select_tab(at,TAB_TT)
    pid=at.session_state["ws_active_project_id"]
    normal=deepcopy(at.session_state["draft_rows"])
    before=deepcopy(at.session_state["draft_project"])
    at.button(key=f"btn_pdf_parse_{pid}").click().run()
    assert not at.exception
    assert at.session_state["draft_project"] == before
    assert at.session_state["draft_rows"] == normal
    at.button(key=f"btn_pdf_apply_{pid}").click().run()
    assert not at.exception
    draft=at.session_state["draft_project"]
    assert draft.settings[KEY]["enabled"]
    assert [len(p["rows"]) for p in draft.settings[KEY]["parts"]] == [2,1]
    assert at.session_state["draft_rows"] == normal
    assert draft.flyer_settings == before.flyer_settings
    assert draft.tickets == before.tickets
    assert at.text_input(key=f"eventfmt_{pid}_0_start_time").value == "10:30"
    assert at.checkbox(key=f"eventfmt_{pid}_None_enabled").value is True


def test_select_pdf_parts_excludes_unchecked_and_preserves_source_order(layout):
    from services.timetable_pdf_service import select_parts
    result = parse_layout(layout)
    third = deepcopy(result['parts'][1])
    third['name'] = '3部'
    result['parts'].append(third)
    original = deepcopy(result)
    assert [p['name'] for p in select_parts(result, [2, 0])] == ['1部', '3部']
    assert [p['name'] for p in select_parts(result, [1])] == ['2部']
    for indices in ([], [-1], [3]):
        with pytest.raises(ValueError):
            select_parts(result, indices)
    assert result == original


def test_single_pdf_part_adapts_post_goods_without_changing_times(layout):
    from services.timetable_pdf_service import normal_rows_from_part
    from services.timetable_service import build_tt_gen_list_from_rows
    part = parse_layout(layout)['parts'][1]
    before = deepcopy(part)
    rows = normal_rows_from_part(part)
    assert rows[0].goods_start_time == '18:25'
    assert rows[0].goods_duration == 90
    assert rows[-1].is_post_goods_row
    data = build_tt_gen_list_from_rows(rows, part['open_time'], part['start_time'])
    assert data[0][0] == '17:50 - 18:15'
    assert data[-1][2] == '18:25 - 19:55'
    assert part == before


@pytest.mark.parametrize('selected', [[0], [1], [0,2]])
def test_pdf_checkboxes_apply_only_selected_parts_and_use_normal_for_one(app_test, layout, monkeypatch, selected):
    import hashlib
    from tests.conftest import select_tab
    from views.workspace import TAB_TT, TAB_GRID
    from services import timetable_pdf_service as service
    from views import pdf_import
    result = parse_layout(layout)
    third = deepcopy(result['parts'][1])
    third['name'] = '3部'
    third['rows'][0]['ARTIST'] = 'Third'
    result['parts'].append(third)
    monkeypatch.setattr(pdf_import.st, 'file_uploader', lambda *a, **k:
        type('Upload', (), {'getvalue': lambda self: b'fixture'})())
    monkeypatch.setattr(service, 'read_pdf', lambda data: deepcopy(result))
    at = app_test.run()
    label = next(x for x in at.selectbox(key='ws_project_selector_label').options
                 if x not in ('(選択してください)', '➕ 新規プロジェクト作成'))
    at.selectbox(key='ws_project_selector_label').select(label).run()
    select_tab(at, TAB_TT)
    pid = at.session_state['ws_active_project_id']
    before = deepcopy(at.session_state['draft_project'])
    normal = deepcopy(at.session_state['draft_rows'])
    at.button(key=f'btn_pdf_parse_{pid}').click().run()
    digest = hashlib.sha256(b'fixture').hexdigest()
    for i in range(3):
        at.checkbox(key=f'eventfmt_pdf_select_{pid}_{digest}_{i}').uncheck().run()
    assert at.button(key=f'btn_pdf_apply_{pid}').disabled
    assert at.session_state['draft_rows'] == normal
    for i in selected:
        at.checkbox(key=f'eventfmt_pdf_select_{pid}_{digest}_{i}').check().run()
    at.button(key=f'btn_pdf_apply_{pid}').click().run()
    assert not at.exception
    draft = at.session_state['draft_project']
    cfg = draft.settings[KEY]
    assert cfg['enabled'] is (len(selected) > 1)
    assert draft.tickets == before.tickets
    assert draft.flyer_settings == before.flyer_settings
    if len(selected) == 1:
        part = result['parts'][selected[0]]
        assert draft.open_time == part['open_time']
        assert draft.start_time == part['start_time']
        rows = at.session_state['draft_rows']
        assert [r.artist_name for r in rows if not r.is_special_row] == [r['ARTIST'] for r in part['rows']]
        assert at.session_state['tt_start_time'] == part['start_time']
        if selected == [1]:
            assert rows[-1].goods_start_time == '18:25'
            assert rows[-1].goods_duration == 90
        select_tab(at, TAB_GRID)
        assert at.number_input(key='grid_rows')
    else:
        assert [p['name'] for p in cfg['parts']] == ['1部','3部']
        assert at.session_state['draft_rows'] == normal
        assert cfg['count'] == 2
    at.run()
    assert not at.exception
