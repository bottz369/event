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


def test_regular_photo_rows_include_changeovers_extra_goods_and_post():
    from services.event_format_service import timetable_rows
    part = new_part(0, rows=[row(ADJUSTMENT=5, ADD_GOODS_START="15:00",
                                ADD_GOODS_DURATION=30, ADD_GOODS_PLACE="B")])
    part.update(post_duration=60, post_start="16:00", transition_label="VIP入れ替え")
    rows = timetable_rows(part)
    assert rows[0] == ("10:30 - 10:50", "A", "11:00 - 12:00 / 15:00 - 15:30", "A / B")
    assert rows[1] == ("10:50 - 10:55", "VIP入れ替え", "", "")
    assert rows[2] == ("16:00 - 17:00", "終演後物販", "", "")


def test_multipart_flyer_uses_regular_compositor_and_all_saved_styles(monkeypatch):
    from services import event_format_service as renderer, font_service
    from utils import flyer_generator
    from models.project import ProjectDraft
    from PIL import Image
    project = ProjectDraft(settings={KEY: dict(enabled=True, free_viewing=True)},
                           flyer_settings=dict(date_pos_x=123, logo_scale=1.8, tt_scale_h=67,
                                               free_placement="overlay", free_viewing_pos_y=91))
    monkeypatch.setattr(font_service, "ensure_font_path", lambda value: value)
    captured = {}
    def compose(**kwargs):
        captured.update(kwargs)
        return kwargs["main_source"], {}
    monkeypatch.setattr(flyer_generator, "create_flyer_image_shadow", compose)
    renderer.compose_flyer(project, Image.new("RGBA", (10, 10)), "tt")
    styles = captured["styles"]
    assert styles["date_pos_x"] == 123
    assert styles["logo_scale"] == 1.8
    assert styles["content_scale_h"] == 67
    assert styles["event_multipart"] is True
    assert styles["free_viewing_pos_y"] == 91
    assert "free_placement" not in styles


def test_multipart_editor_exposes_regular_controls_without_global_time(app_test):
    from tests.conftest import select_tab
    from views.workspace import TAB_FLYER
    at = app_test.run()
    label = next(x for x in at.selectbox(key="ws_project_selector_label").options
                 if x not in ("(選択してください)", "➕ 新規プロジェクト作成"))
    at.selectbox(key="ws_project_selector_label").select(label).run()
    draft = at.session_state["draft_project"]
    draft.settings[KEY] = dict(enabled=True, free_viewing=True, count=2,
                               parts=[new_part(0), new_part(1)])
    at.session_state["draft_project"] = draft
    select_tab(at, TAB_FLYER)
    keys = {w.key for w in at.slider}
    assert "flyer_logo_scale" in keys or not at.session_state["flyer_logo_id"]
    assert "flyer_grid_scale_w" in keys
    assert "flyer_free_viewing_size" in keys
    assert "flyer_time_size" not in keys
    assert "flyer_free_placement" not in {w.key for w in at.selectbox}


def test_click_move_consumed_once_before_widgets(app_test, monkeypatch):
    from tests.conftest import select_tab
    from views.workspace import TAB_FLYER
    from views import flyer
    from PIL import Image
    at = app_test.run()
    label = next(x for x in at.selectbox(key="ws_project_selector_label").options
                 if x not in ("(選択してください)", "➕ 新規プロジェクト作成"))
    at.selectbox(key="ws_project_selector_label").select(label).run()
    select_tab(at, TAB_FLYER)
    monkeypatch.setattr(flyer, "_generate_preview", lambda proj: None)
    # Component returns the same coordinates again after the widgets have rendered.
    coords = dict(x=300, y=200)
    monkeypatch.setattr(flyer, "streamlit_image_coordinates", lambda *a, **kw: coords)
    at.session_state["flyer_result_grid"] = Image.new("RGBA", (1080,1350))
    at.session_state["flyer_layout_meta"] = {"date": dict(base_x=540, base_y=500)}
    at.session_state["flyer_click_target"] = "date"
    at.session_state["coord_grid"] = coords
    at.run()
    assert not at.exception
    ratio = 1080 / at.session_state["flyer_preview_width"]
    assert at.session_state["flyer_date_pos_x"] == int(300 * ratio - 540)
    at.number_input(key="flyer_date_pos_x").set_value(15).run()
    assert not at.exception
    assert at.session_state["flyer_date_pos_x"] == 15


@pytest.mark.parametrize("placement", ["band", "overlay", None])
@pytest.mark.parametrize("multipart", [False, True])
def test_free_viewing_is_inline_below_tickets_even_for_legacy_band(monkeypatch, placement, multipart):
    from utils import flyer_generator as generator
    from models.flyer_keys import FLYER_KEY_REGISTRY
    styles = {e.short_key: e.default for e in FLYER_KEY_REGISTRY if e.persist}
    styles.update(event_multipart=multipart, event_free_viewing=True, event_free_text="ステージ前",
                  free_placement=placement, free_viewing_pos_x=35, free_viewing_pos_y=20,
                  ticket_name_pos_y=200, ticket_gap=-10)
    times, texts = [], []
    def time_row(canvas, *args, **kwargs):
        times.append(canvas)
        return 30
    def text(canvas, content, x, y, *args, **kwargs):
        texts.append((content,x,y))
        return 30
    monkeypatch.setattr(generator, "draw_time_row_aligned", time_row)
    monkeypatch.setattr(generator, "draw_text_with_shadow", text)
    image, meta = generator.create_flyer_image_shadow(None,None,None,styles,"date","venue","sub",
        "10:00","10:30",[dict(name="VIP",price="5000"),dict(name="一般",price="2000")],["備考"])
    assert image.size == (1080,1350)
    assert (times == [None,None]) if multipart else all(t is not None for t in times)
    assert ("time" not in meta) == multipart
    tickets = [t for t in texts if t[0] in ("VIP 5000", "一般 2000")]
    assert meta["free_viewing"]["base_y"] == max(t[2]+30 for t in tickets)+10
    assert ("観覧無料",575,meta["free_viewing"]["base_y"]-20) in texts
    assert ("ステージ前",540,meta["free_note"]["base_y"]) in texts
    assert [t[0] for t in texts].count("sub") == 1
    assert [t[0] for t in texts].index("date") < [t[0] for t in texts].index("venue")


def test_multipart_header_passes_venue_and_single_subtitle(monkeypatch):
    from services import event_format_service as renderer, font_service
    from utils import flyer_generator
    from models.project import ProjectDraft
    from PIL import Image
    project = ProjectDraft(subtitle="2026 KABUKICHO vol.3", venue_name="KABUKICHO TOWER STAGE",
                           settings={KEY: dict(enabled=True)})
    monkeypatch.setattr(font_service, "ensure_font_path", lambda value: value)
    captured = {}
    def compose(**kwargs):
        captured.update(kwargs)
        return kwargs["main_source"], {}
    monkeypatch.setattr(flyer_generator, "create_flyer_image_shadow", compose)
    renderer.compose_flyer(project, Image.new("RGBA", (10,10)), "grid")
    assert captured["venue_text"] == "KABUKICHO TOWER STAGE"
    assert captured["subtitle_text"] == "2026 KABUKICHO vol.3"


def test_visible_text_bounds_match_pixels_without_changing_render():
    from PIL import Image
    from utils.flyer_generator import draw_text_with_shadow
    first = Image.new("RGBA", (600,300))
    second = first.copy()
    bounds = {}
    args = ("VIP 5000",300,100,None,40,560,"white")
    draw_text_with_shadow(first,*args)
    draw_text_with_shadow(second,*args,layout_bounds=bounds)
    assert first.tobytes() == second.tobytes()
    assert bounds["bottom"] == second.getbbox()[3]
