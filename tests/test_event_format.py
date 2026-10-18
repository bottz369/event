"""Optional event format: normal events, independent parts, persistence and UI."""
from copy import deepcopy
import json

import pytest

from models.event_format import KEY, active_parts, new_part, options, schedule, validate
from models.timetable import TimetableRowDraft


def row(name="A", **updates):
    result = TimetableRowDraft(artist_name=name, place="A").to_legacy_dict()
    result.update(updates)
    return result


def test_old_settings_do_not_enable_new_format():
    assert not options({"tt_columns": 2}).get("enabled")
    assert validate({}) == []


def test_settings_round_trip_preserves_parts_and_duplicate_performer():
    cfg = dict(enabled=True, count=2, parts=[new_part(0, rows=[row()]), new_part(1, rows=[row()])])
    loaded = options(json.loads(json.dumps({KEY: cfg})))
    assert loaded == cfg
    loaded["parts"][0]["rows"][0]["ARTIST"] = "changed"
    assert cfg["parts"][0]["rows"][0]["ARTIST"] == "A"


def test_each_part_restarts_at_its_own_start():
    first = new_part(0, "10:00", "10:30", [row(ADJUSTMENT=5), row("B")])
    second = new_part(1, "17:30", "17:50", [row()])
    a, _ = schedule(first)
    b, _ = schedule(second)
    assert a[1]["start"] == "10:55"
    assert b[0]["start"] == "17:50"


def test_hidden_rows_consume_stage_time():
    data, _ = schedule(new_part(0, rows=[row(IS_HIDDEN=True), row("B")]))
    assert data[1]["start"] == "10:50"


def test_goods_manual_and_post_session_are_independent():
    part = new_part(0, rows=[row(GOODS_START_MANUAL="11:30"), row("B", IS_POST_GOODS=True, GOODS_START_MANUAL="08:00")])
    part.update(post_start="15:50", post_duration=90)
    data, post = schedule(part)
    assert data[0]["goods"] == "11:30–12:30"
    assert data[1]["goods"] == "15:50–17:20"
    assert post == "15:50"


def test_zero_minutes_are_not_defaulted_to_twenty_or_sixty():
    data, _ = schedule(new_part(0, rows=[row(DURATION=0, GOODS_DURATION=0)]))
    assert data[0]["start"] == data[0]["end"]
    assert data[0]["goods"] == ""


def test_reducing_count_keeps_unused_parts_for_restoration():
    cfg = dict(enabled=True, count=2, parts=[new_part(i) for i in range(3)])
    before = deepcopy(cfg["parts"][2])
    assert len(active_parts(cfg)) == 2
    cfg["count"] = 3
    assert active_parts(cfg)[2] == before


@pytest.mark.parametrize("field", ["open_time", "start_time", "post_start"])
def test_invalid_part_times_are_rejected(field):
    part = new_part(0)
    part[field] = "not-a-time"
    assert validate(dict(enabled=True, count=2, parts=[part]))


def test_post_flag_requires_a_duration():
    part = new_part(0, rows=[row(IS_POST_GOODS=True)])
    assert validate(dict(enabled=True, count=2, parts=[part]))


def test_mode_switch_preserves_normal_rows(app_test):
    from tests.conftest import select_tab
    from views.workspace import TAB_TT
    at = app_test.run()
    choices = at.selectbox(key="ws_project_selector_label").options
    label = next(x for x in choices if x not in ("(選択してください)", "➕ 新規プロジェクト作成"))
    at.selectbox(key="ws_project_selector_label").select(label).run()
    select_tab(at, TAB_TT)
    before = deepcopy(at.session_state["draft_rows"])
    pid = at.session_state["ws_active_project_id"]
    key = f"eventfmt_{pid}_None_enabled"
    at.checkbox(key=key).check().run()
    assert not at.exception
    assert at.session_state["draft_rows"] == before
    assert at.session_state["draft_project"].settings[KEY]["enabled"]
    at.checkbox(key=key).uncheck().run()
    assert not at.exception
    assert at.session_state["draft_rows"] == before


def test_optional_settings_survive_session_sync(app_test):
    from services import session_manager
    from models.project import ProjectDraft
    from unittest.mock import patch
    class State(dict):
        __getattr__ = dict.__getitem__
        __setattr__ = dict.__setitem__
    cfg = dict(enabled=True, count=2, parts=[new_part(0), new_part(1)])
    draft = ProjectDraft(settings={KEY: cfg})
    state = State(draft_project=draft, tt_columns=2)
    with patch.object(session_manager.st, "session_state", state):
        session_manager.sync_session_to_draft()
    assert draft.settings[KEY] == cfg


def test_edit_add_then_edit_does_not_duplicate_rows(monkeypatch):
    from views import event_format
    from models.project import ProjectDraft
    from services import session_manager
    cfg = dict(enabled=True, count=2, parts=[new_part(0, rows=[row()]), new_part(1)])
    draft = ProjectDraft(id=999, settings={KEY: cfg})
    state = dict(draft_project=draft, ws_active_project_id=999)
    monkeypatch.setattr(session_manager.st, "session_state", state)
    state["editor0"] = dict(edited_rows={}, deleted_rows=[], added_rows=[{"ARTIST": "B"}])
    event_format._rows_changed("editor0", 0)
    state["editor1"] = dict(edited_rows={0: {"DURATION": 0}}, deleted_rows=[], added_rows=[])
    event_format._rows_changed("editor1", 0)
    data = draft.settings[KEY]["parts"][0]["rows"]
    assert [r["ARTIST"] for r in data] == ["A", "B"]
    assert data[0]["DURATION"] == 0


def test_free_banner_keeps_original_pixels(monkeypatch):
    from PIL import Image, ImageFont
    from services import event_format_service as renderer
    monkeypatch.setattr(renderer, "_font", lambda path, size: ImageFont.load_default(size=size))
    original = Image.new("RGBA", (400, 300), (255, 0, 0, 100))
    result = renderer.free_banner(original, "Free viewing area", "unused")
    assert result.size[0] == original.width
    assert result.height > original.height
    assert result.crop((0, 0, 400, 300)).tobytes() == original.tobytes()


@pytest.mark.parametrize("variant", ["tt", "grid"])
def test_api_uses_shared_renderer_for_enabled_format(monkeypatch, variant):
    from PIL import Image
    from models.project import ProjectDraft
    from services import generation_service as api, event_format_service as renderer
    project = ProjectDraft(settings={KEY: dict(enabled=True)})
    calls = []
    monkeypatch.setattr(renderer, "project_from_db", lambda pid: project)
    def fake_render(project, mode, finished=False, failures=None):
        calls.append((mode, finished))
        return Image.new("RGBA", (10, 10))
    monkeypatch.setattr(renderer, "render", fake_render)
    assert api.render_flyer_png_for_project(1, variant).startswith(b"\x89PNG")
    assert calls == [(variant, True)]


def test_summary_lists_all_parts_and_free_viewing_without_mutating_inputs():
    from models.event_format import summary_inputs
    parts = [new_part(0, rows=[row("A")]), new_part(1, "17:30", "17:50", [row("B"), row("A")])]
    notes = ["VIP条件"]
    cfg = dict(enabled=True, count=2, parts=parts, free_viewing=True, free_text="ステージ前")
    result = summary_inputs(cfg, ["old"], notes, [], "09:00", "09:30")
    assert result["artists"] == ["A", "B"]
    assert result["open_time"] == "10:00"
    assert "17:50" in result["free_texts"][0]["content"]
    assert result["ticket_notes"][-1] == "観覧無料（ステージ前）"
    assert notes == ["VIP条件"]


def test_summary_normal_mode_is_unchanged():
    from models.event_format import summary_inputs
    result = summary_inputs({}, ["A"], ["note"], [], "10:00", "10:30")
    assert result == dict(artists=["A"], ticket_notes=["note"], free_texts=[],
                          open_time="10:00", start_time="10:30")
