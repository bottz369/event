"""保存をプロジェクト単位の1ボタンに統合したことの回帰テスト。

守る不変条件:
  1. 保存ボタンはアプリ全体で 1 つだけ。各タブに保存/生成ボタンは無い。
  2. 「複製して編集」は保存ボタンの右隣に残っている。
  3. プロジェクトを開いただけ / レンダーを繰り返しただけでは画像生成が走らない
     (罠16 / Phase 3 stop-autogen の回帰防止)。
  4. 保存を押すと「現在のタブ」のプレビューだけが保存後の状態から再生成される。
     フライヤータブでは素材(grid / TT)も含めて再生成される。
  5. 設定を変えて保存しなければ DB は変わらず、プレビューは stale 扱いになって
     ダウンロードできない(乖離した画像を配らない)。
  6. web プレビューの入力(列数 / フォント / 出演順)が DB と一致する
     = LINE/API (generation_service) と同一入力になる。

本番 DB 書き込み禁止のため、保存そのものは monkeypatch でスタブする
(save_active_project を置き換えるので DB へは一切書かない)。
"""
from __future__ import annotations

import json

import pytest

SELECTOR_KEY = "ws_project_selector_label"
SAVE_BUTTON_KEY = "btn_project_save"
DUPLICATE_BUTTON_KEY = "btn_proj_duplicate"


def _make_engine(db_url: str):
    from sqlalchemy import create_engine

    return create_engine(db_url, connect_args={"sslmode": "require"})


@pytest.fixture
def opened_project(app_test):
    """最初の実プロジェクトを開いた AppTest と、その project_id を返す。"""
    at = app_test.run()
    assert not at.exception, f"初期描画で例外: {at.exception}"
    options = [
        o
        for o in at.selectbox(key=SELECTOR_KEY).options
        if o not in ("(選択してください)", "➕ 新規プロジェクト作成")
    ]
    if not options:
        pytest.skip("選択できるプロジェクトが無い")
    at.selectbox(key=SELECTOR_KEY).select(options[0]).run()
    assert not at.exception, f"プロジェクト選択で例外: {at.exception}"
    return at, at.session_state["ws_active_project_id"]


@pytest.fixture
def stub_save(monkeypatch):
    """save_active_project を成功扱いのスタブに置き換える(DB へ書かない)。

    返り値は呼ばれた回数を持つ dict。
    """
    from services import project_service

    calls = {"n": 0}

    def _fake_save():
        calls["n"] += 1
        return True

    monkeypatch.setattr(project_service, "save_active_project", _fake_save)
    return calls


@pytest.fixture
def spy_regenerators(monkeypatch):
    """workspace が呼ぶ再生成関数を記録用スタブに差し替える。"""
    from views import workspace

    fired = []
    for name in (
        "regenerate_tt_preview",
        "regenerate_grid_preview",
        "regenerate_flyer_preview",
        "mark_overview_saved",
    ):
        def _make(n):
            def _rec(*_a, **_kw):
                fired.append(n)
                return True

            return _rec

        monkeypatch.setattr(workspace, name, _make(name))
    return fired


# ---------------------------------------------------------------------------
# 1 / 2: ボタン構成
# ---------------------------------------------------------------------------
def test_single_save_button_and_duplicate_beside_it(opened_project):
    """保存ボタンは 1 つだけ存在し、複製ボタンも残っている。"""
    at, _pid = opened_project
    assert at.button(key=SAVE_BUTTON_KEY), "統合保存ボタンが無い"
    assert at.button(key=DUPLICATE_BUTTON_KEY), "「複製して編集」が消えている"


@pytest.mark.parametrize(
    "removed_key", ["btn_tt_generate", "btn_grid_generate", "btn_overview_save"]
)
def test_per_tab_save_buttons_are_gone(opened_project, tab, removed_key):
    """各タブの旧「設定反映」ボタンがどのタブにも存在しない。"""
    from tests.conftest import select_tab

    at, _pid = opened_project
    for label in tab.TAB_LABELS:
        select_tab(at, label)
        with pytest.raises(KeyError):
            at.button(key=removed_key)


# ---------------------------------------------------------------------------
# 3: 開くだけでは生成しない(罠16)
# ---------------------------------------------------------------------------
def test_opening_and_rerendering_does_not_generate(opened_project, tab):
    """開くだけ / レンダー反復では画像が生成されない。"""
    from tests.conftest import select_tab

    at, _pid = opened_project

    def _images():
        out = {}
        for k in ("last_generated_tt_image", "last_generated_grid_image", "flyer_result_grid"):
            try:
                out[k] = at.session_state[k]
            except Exception:
                out[k] = None
        return out

    for label in tab.TAB_LABELS:
        select_tab(at, label)
        for _ in range(2):
            at.run()
            assert not at.exception, f"{label} の再描画で例外: {at.exception}"
            imgs = _images()
            assert not any(imgs.values()), (
                f"{label} を描画しただけで画像が生成された: "
                f"{[k for k, v in imgs.items() if v]}"
            )


# ---------------------------------------------------------------------------
# 4: 保存で「現在のタブ」だけ再生成される
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "tab_attr,expected",
    [
        ("TAB_TT", ["regenerate_tt_preview"]),
        ("TAB_GRID", ["regenerate_grid_preview"]),
        (
            "TAB_FLYER",
            ["regenerate_grid_preview", "regenerate_tt_preview", "regenerate_flyer_preview"],
        ),
        ("TAB_OVERVIEW", ["mark_overview_saved"]),
    ],
)
def test_save_regenerates_only_current_tab(
    opened_project, tab, stub_save, spy_regenerators, tab_attr, expected
):
    """保存ハンドラは現在のタブ(とその依存)だけを再生成する。

    フライヤーは grid → TT → フライヤーの順で素材から作り直す。
    順序が崩れると古い素材で合成され、症状1(DL 画像と DB の乖離)が再発する。
    """
    from tests.conftest import select_tab

    at, _pid = opened_project
    select_tab(at, getattr(tab, tab_attr))

    at.button(key=SAVE_BUTTON_KEY).click().run()
    assert not at.exception, f"保存で例外: {at.exception}"
    assert stub_save["n"] == 1, "save_active_project が 1 回呼ばれていない"
    assert spy_regenerators == expected, (
        f"再生成の対象/順序が想定と違う: {spy_regenerators} != {expected}"
    )


# ---------------------------------------------------------------------------
# 5: 保存しなければ DB は変わらず、プレビューは stale
# ---------------------------------------------------------------------------
def test_editing_without_saving_changes_nothing_in_db(
    opened_project, tab, readonly_creds
):
    """設定を変えても保存しなければ DB は変わらない(明示保存型)。"""
    from sqlalchemy import text

    from tests.conftest import select_tab

    at, pid = opened_project
    engine = _make_engine(readonly_creds["DB_URL"])

    def _snapshot():
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT settings_json, flyer_json, grid_order_json "
                    "FROM projects_v4 WHERE id = :i"
                ),
                {"i": pid},
            ).fetchone()
        return tuple(row)

    try:
        before = _snapshot()

        select_tab(at, tab.TAB_FLYER)
        slider = at.slider(key="flyer_grid_scale_w")
        slider.set_value(11 if slider.value != 11 else 12).run()
        assert not at.exception, f"スライダー操作で例外: {at.exception}"

        assert _snapshot() == before, "保存していないのに DB が変化した"
    finally:
        engine.dispose()


def test_unsaved_change_marks_preview_stale(opened_project, tab):
    """未保存の変更があるとフライヤープレビューは stale 扱いになる。

    stale の間は DL ボタンを出さない(乖離した画像を配らない)ため、
    この判定が壊れると症状1 と同じ「保存値と違う画像を DL できる」状態に戻る。
    """
    from tests.conftest import select_tab
    from views.flyer import flyer_preview_is_stale

    at, _pid = opened_project
    select_tab(at, tab.TAB_FLYER)

    # まだ一度も保存由来のプレビューを作っていないので stale
    assert flyer_preview_is_stale() is True
    # DL ボタンも出ていない
    for key in ("dl_grid_single", "dl_tt_single"):
        with pytest.raises(KeyError):
            at.button(key=key)


# ---------------------------------------------------------------------------
# 6: web プレビューの入力が DB(= LINE/API の入力)と一致する
# ---------------------------------------------------------------------------
def test_preview_inputs_match_db_and_api(
    opened_project, tab, readonly_creds, stub_save, monkeypatch
):
    """列数・フォント・出演順が DB と一致し、API と同じ入力になる。

    web(保存ハンドラが画像生成に渡す値)と generation_service(DB を読む API)の
    gen_list を突き合わせる。ここがズレると「web は 2 列 / LINE は 1 列」という
    症状1 が起きる。

    build_gen_list_from_draft() は st.session_state を読むのでスクリプト実行
    コンテキストの中でしか正しく動かない。そこで保存ハンドラが呼ぶ再生成関数を
    「gen_list を計算して session に置くだけ」のスタブへ差し替え、保存ボタン経由で
    実際の実行コンテキストの中から取り出す(DB へは stub_save のため書かない)。
    """
    from sqlalchemy import text

    from services import timetable_service
    from tests.conftest import select_tab
    from views import workspace
    from views.timetable import build_gen_list_from_draft

    at, pid = opened_project
    select_tab(at, tab.TAB_TT)

    engine = _make_engine(readonly_creds["DB_URL"])
    try:
        with engine.connect() as conn:
            raw = conn.execute(
                text("SELECT settings_json FROM projects_v4 WHERE id = :i"), {"i": pid}
            ).scalar()
    finally:
        engine.dispose()
    db_settings = json.loads(raw) if raw else {}

    # 設定値: session(web が生成に使う値)と DB(API が読む値)が一致
    for sess_key, db_key, api_default in (
        ("tt_columns", "tt_columns", 2),
        ("tt_font", "tt_font", "keifont.ttf"),
        ("grid_font", "grid_font", "keifont.ttf"),
    ):
        web_value = at.session_state[sess_key]
        api_value = db_settings.get(db_key) or api_default
        assert web_value == api_value, (
            f"{sess_key} が web={web_value!r} / API={api_value!r} で食い違う"
        )

    # 保存ハンドラの中で gen_list を計算させ、session 経由で回収する
    import streamlit as st

    def _capture():
        st.session_state["_probe_gen_list"] = build_gen_list_from_draft()
        return True

    monkeypatch.setattr(workspace, "regenerate_tt_preview", _capture)
    at.button(key=SAVE_BUTTON_KEY).click().run()
    assert not at.exception, f"保存で例外: {at.exception}"
    web_gen_list = at.session_state["_probe_gen_list"]

    draft = at.session_state["draft_project"]
    rows = timetable_service.get_rows_for_project(pid)
    api_gen_list = timetable_service.build_tt_gen_list_from_rows(
        rows, draft.open_time, draft.start_time
    )
    assert web_gen_list == api_gen_list, (
        "web と API の gen_list が食い違う "
        f"(web={len(web_gen_list)}件 / API={len(api_gen_list)}件)"
    )

    # render 側(画面に出る表)とも一致していること
    assert at.session_state["tt_gen_list"] == api_gen_list, (
        "画面表示用の gen_list が API と食い違う"
    )


def test_unvisited_tabs_settings_are_not_lost_on_save(
    opened_project, tab, readonly_creds, stub_save, monkeypatch
):
    """未訪問タブの設定が保存で消えない(タブ遅延描画の最大のリスク)。

    タブを遅延描画すると、開いていないタブのウィジェットは描画されない。
    Streamlit は未描画ウィジェットの session_state を破棄するため、素直に実装すると
    「grid タブを開かずに保存したら grid の設定が既定へ戻る」といった事故が起きる。
    _pin_session_keys() の延命と legacy_adapter の seed でこれを防いでいる。

    ここでは grid / TT を一度も開かずフライヤータブへ移り、保存ハンドラの中
    (= sync_session_to_draft が読むのと同じ実行コンテキスト)で値を回収して
    DB と一致することを確かめる。
    """
    from sqlalchemy import text

    from tests.conftest import select_tab
    from views import workspace

    at, pid = opened_project

    engine = _make_engine(readonly_creds["DB_URL"])
    try:
        with engine.connect() as conn:
            s_raw, g_raw = conn.execute(
                text(
                    "SELECT settings_json, grid_order_json FROM projects_v4 WHERE id = :i"
                ),
                {"i": pid},
            ).fetchone()
    finally:
        engine.dispose()
    db_settings = json.loads(s_raw) if s_raw else {}
    db_grid = json.loads(g_raw) if g_raw else {}

    # grid / TT タブは開かずにフライヤータブへ
    select_tab(at, tab.TAB_FLYER)

    import streamlit as st

    watched = (
        "tt_columns",
        "tt_font",
        "grid_font",
        "grid_row_counts_str",
        "grid_layout_mode",
        "grid_alignment",
    )

    def _capture(*_a, **_kw):
        st.session_state["_probe_settings"] = {
            k: st.session_state.get(k) for k in watched
        }
        return True

    for name in ("regenerate_grid_preview", "regenerate_tt_preview", "regenerate_flyer_preview"):
        monkeypatch.setattr(workspace, name, _capture)

    at.button(key=SAVE_BUTTON_KEY).click().run()
    assert not at.exception, f"保存で例外: {at.exception}"
    captured = at.session_state["_probe_settings"]

    expected = {
        "tt_columns": db_settings.get("tt_columns") or 2,
        "tt_font": db_settings.get("tt_font") or "keifont.ttf",
        "grid_font": db_settings.get("grid_font") or "keifont.ttf",
        "grid_row_counts_str": db_grid.get("row_counts_str"),
        "grid_layout_mode": db_grid.get("layout_mode"),
        "grid_alignment": db_grid.get("alignment"),
    }
    for key, want in expected.items():
        if want is None:
            continue  # DB に無いキーは比較対象外(既定が入る)
        assert captured[key] == want, (
            f"未訪問タブの {key} が保存時に失われている: "
            f"保存される値={captured[key]!r} / DB={want!r}"
        )
