"""予定組数の web 入力欄(Issue2)のテスト。

「■出演者（N組予定）」の N を、intake で作ったプロジェクトだけでなく
既存プロジェクトでも web から設定できるようにした。

配線の要点(調査結果):
  - widget key = flyer_planned_artist_count が SSOT(罠18)
  - 保存は統合保存ボタンのみ。sync_session_to_draft が flyer_* を丸ごと
    draft.flyer_settings に写し、apply_draft が flyer_json にマージする
    (専用の保存配線は不要 = blocklist 方式のおかげ)
  - 読込は legacy_adapter が flyer_json の各キーを flyer_* に戻す。
    値が None のキーはスキップされるので、空欄保存は「未設定」に戻る

★実 DB には書かない(保存は monkeypatch でスタブ)。
"""
from __future__ import annotations

import pytest

SELECTOR_KEY = "ws_project_selector_label"
SAVE_BUTTON_KEY = "btn_project_save"
PLANNED_KEY = "flyer_planned_artist_count"


@pytest.fixture
def opened_overview(app_test, tab):
    """最初の実プロジェクトを開き、概要タブを表示した AppTest。"""
    from tests.conftest import select_tab

    at = app_test.run()
    assert not at.exception, f"初期描画で例外: {at.exception}"
    options = [
        o for o in at.selectbox(key=SELECTOR_KEY).options
        if o not in ("(選択してください)", "➕ 新規プロジェクト作成")
    ]
    if not options:
        pytest.skip("選択できるプロジェクトが無い")
    at.selectbox(key=SELECTOR_KEY).select(options[0]).run()
    assert not at.exception, f"プロジェクト選択で例外: {at.exception}"
    select_tab(at, tab.TAB_OVERVIEW)
    return at


def _planned(at):
    try:
        return at.session_state[PLANNED_KEY]
    except Exception:
        return "(キー無し)"


# ---------------------------------------------------------------------------
# 入力欄
# ---------------------------------------------------------------------------
def test_planned_count_input_exists_and_starts_empty(opened_overview):
    """入力欄があり、未設定のプロジェクトでは空欄(= 実組数へフォールバック)。"""
    at = opened_overview
    widget = at.number_input(key=PLANNED_KEY)
    assert widget, "予定組数の入力欄が無い"
    assert _planned(at) is None, "未設定なのに値が入っている"


def test_entering_a_value_updates_the_session_key(opened_overview):
    at = opened_overview
    at.number_input(key=PLANNED_KEY).set_value(27).run()
    assert not at.exception, f"入力で例外: {at.exception}"
    assert _planned(at) == 27


def test_clearing_the_value_falls_back_to_none(opened_overview):
    at = opened_overview
    at.number_input(key=PLANNED_KEY).set_value(27).run()
    at.number_input(key=PLANNED_KEY).set_value(None).run()
    assert _planned(at) is None, "空欄に戻せていない"


def test_minimum_is_one():
    """0 や負を入れられない(0 は「未設定」と区別できないため)。

    AppTest の NumberInput は min_value を公開しないので、ウィジェット定義側で
    min_value=1 を渡していることを固定する。
    """
    src = open("views/overview.py", encoding="utf-8").read()
    block = src[src.index('st.number_input(\n            "予定組数"'):]
    block = block[:block.index(")\n")]
    assert "min_value=1" in block
    assert "value=None" in block, "既定が空欄でないとフォールバックが効かない"
    assert 'key="flyer_planned_artist_count"' in block


# ---------------------------------------------------------------------------
# 変更検知
# ---------------------------------------------------------------------------
def test_changing_planned_count_marks_unsaved(opened_overview):
    """予定組数を変えたら「変更を保存すると…」が出る。"""
    at = opened_overview
    warnings_before = [w.value for w in at.warning]
    assert not any("変更を保存すると" in str(w) for w in warnings_before), (
        "開いただけで未保存扱いになっている"
    )

    at.number_input(key=PLANNED_KEY).set_value(27).run()
    warnings_after = [str(w.value) for w in at.warning]
    assert any("変更を保存すると" in w for w in warnings_after), (
        "予定組数を変えても未保存警告が出ない"
    )


def test_change_detection_uses_one_shared_param_builder():
    """レンダー側と保存済みの印が同じ作り方であること。

    以前は同じ辞書が 2 か所にあり、片方にキーを足すと永久に「未保存」に
    なる作りだった。_overview_params() に一本化してある。
    """
    src = open("views/overview.py", encoding="utf-8").read()
    assert "current_params = _overview_params()" in src
    assert src.count('"planned":') == 1, "パラメータ辞書が複数ある"


# ---------------------------------------------------------------------------
# 保存経路(実 DB には書かない)
# ---------------------------------------------------------------------------
def test_planned_count_reaches_the_draft_on_save(opened_overview, monkeypatch):
    """保存時に flyer_json 側(draft.flyer_settings)へ載ること。

    実際の DB 書き込みはスタブし、sync_session_to_draft が終わった時点の
    draft を覗いて配線を確かめる。
    """
    from services import project_service, session_manager
    from views import workspace

    at = opened_overview
    at.number_input(key=PLANNED_KEY).set_value(27).run()

    captured = {}

    def _fake_save():
        session_manager.sync_session_to_draft()
        draft = session_manager.get_draft_project()
        captured["flyer"] = dict(draft.flyer_settings or {})
        return True

    monkeypatch.setattr(project_service, "save_active_project", _fake_save)
    monkeypatch.setattr(workspace, "mark_overview_saved", lambda: True)

    at.button(key=SAVE_BUTTON_KEY).click().run()
    assert not at.exception, f"保存で例外: {at.exception}"
    assert captured["flyer"].get("planned_artist_count") == 27, (
        "予定組数が flyer_json 側へ渡っていない"
    )


def test_cleared_planned_count_is_saved_as_none(opened_overview, monkeypatch):
    """空欄は None として保存され、読込時にスキップされてフォールバックする。"""
    from services import project_service, session_manager
    from views import workspace

    at = opened_overview
    at.number_input(key=PLANNED_KEY).set_value(27).run()
    at.number_input(key=PLANNED_KEY).set_value(None).run()

    captured = {}

    def _fake_save():
        session_manager.sync_session_to_draft()
        captured["flyer"] = dict(
            session_manager.get_draft_project().flyer_settings or {})
        return True

    monkeypatch.setattr(project_service, "save_active_project", _fake_save)
    monkeypatch.setattr(workspace, "mark_overview_saved", lambda: True)

    at.button(key=SAVE_BUTTON_KEY).click().run()
    assert captured["flyer"].get("planned_artist_count", "MISSING") is None


def test_planned_count_key_is_not_excluded_from_persistence():
    """flyer_* の除外リストに入っていないこと(入ると保存されない)。"""
    import services.session_manager as sm

    assert PLANNED_KEY not in sm._FLYER_EXCLUDED_KEYS


def test_none_valued_flyer_keys_are_skipped_on_load():
    """読込時に None のキーはスキップされる(= 未設定に戻る)配線の確認。"""
    src = open("services/legacy_adapter.py", encoding="utf-8").read()
    assert "if v is None:" in src and "continue" in src
