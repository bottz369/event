"""🔗 リンク(縦横比固定)がレンダー起因で scale_h を破壊しないことの回帰テスト。

背景(症状2(a)):
    views/flyer.py は以前、レンダー本体で無条件に
        if st.session_state.flyer_grid_link:
            st.session_state.flyer_grid_scale_h = new_w
    を実行していた。flyer_grid_link / flyer_tt_link は persist=False・既定 True
    (models/flyer_keys.py)なので、プロジェクトを開くたびに必ず True へ戻り、
    scale_h != scale_w の健全なプロジェクトでも「開いて何か保存するだけ」で
    scale_h が scale_w に潰れる進行性のデータ破壊が起きていた。
    実 DB 監査では 18 件中 17 件が既に h == w に潰れており、
    id=35 (grid 10/90, tt 10/95) のみが未潰れで残っていた。

このテストが守る不変条件:
    (a) プロジェクトを開いただけ / 再レンダーを繰り返しただけでは scale_h が動かない
    (b) 保存対象(flyer_* の persist=True 全キー)が DB 値と一致したままである
    (c) それでも 🔗 の機能自体は生きている(横幅を操作したときだけ高さが追随する)

read-only: SELECT のみ。DB への書き込みは一切行わない。
"""
from __future__ import annotations

import json

import pytest

SELECTOR_KEY = "ws_project_selector_label"


def _make_engine(db_url: str):
    from sqlalchemy import create_engine

    return create_engine(db_url, connect_args={"sslmode": "require"})


@pytest.fixture(scope="session")
def project_with_unlinked_scales(readonly_creds):
    """flyer_json で scale_h != scale_w が残っているプロジェクトを1件返す。

    返り値: (id, event_date, flyer_json(dict))
    これが「次に開くと潰れる」候補そのものなので、回帰テストの検体として最適。
    見つからなければ skip(read-only なので検体を作れない)。
    """
    from sqlalchemy import text

    engine = _make_engine(readonly_creds["DB_URL"])
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT id, event_date, flyer_json FROM projects_v4 "
                    "WHERE flyer_json IS NOT NULL ORDER BY id DESC"
                )
            ).fetchall()
    finally:
        engine.dispose()

    for row in rows:
        try:
            f = json.loads(row.flyer_json)
        except Exception:
            continue
        gw, gh = f.get("grid_scale_w"), f.get("grid_scale_h")
        tw, th = f.get("tt_scale_w"), f.get("tt_scale_h")
        if (gw is not None and gw != gh) or (tw is not None and tw != th):
            return row.id, row.event_date, f

    pytest.skip(
        "scale_h != scale_w のプロジェクトが見つかりません"
        "(全件が既に潰れている場合、この回帰テストは検体を作れません)"
    )


def _open_project(at, event_date):
    """event_date でラベルを引き当ててプロジェクトを開く。"""
    label = next(
        (o for o in at.selectbox(key=SELECTOR_KEY).options if str(event_date) in o),
        None,
    )
    if label is None:
        pytest.skip(f"selectbox に event_date '{event_date}' のラベルが無い")
    at.selectbox(key=SELECTOR_KEY).select(label).run()
    assert not at.exception, f"プロジェクト選択で例外: {at.exception}"
    return at


def test_scale_h_survives_repeated_renders(app_test, project_with_unlinked_scales):
    """開いた直後および再レンダー後も scale_h が DB 値のまま動かない。

    修正前はここが RED になる(1 回目のレンダーで既に scale_h = scale_w)。
    """
    pid, event_date, dbf = project_with_unlinked_scales

    at = app_test.run()
    _open_project(at, event_date)

    for i in range(3):
        for prefix in ("grid", "tt"):
            expected = dbf.get(f"{prefix}_scale_h")
            if expected is None:
                continue
            actual = at.session_state[f"flyer_{prefix}_scale_h"]
            assert actual == expected, (
                f"id={pid} レンダー{i + 1}回目: flyer_{prefix}_scale_h が "
                f"DB値 {expected} から {actual} へ変化した"
                f"(🔗 リンクのレンダー起因上書き)"
            )
        at.run()
        assert not at.exception, f"再レンダー{i + 1}回目で例外: {at.exception}"


def test_flyer_settings_parity_on_open(app_test, project_with_unlinked_scales):
    """開いただけでは保存対象の flyer_* 全キーが DB と一致したまま。

    どのタブの保存ボタンも save_active_project() 経由で session の値をそのまま
    書き戻すため、この一致が崩れている = 開いて保存するだけで DB が壊れる、を意味する。
    """
    from models.flyer_keys import FLYER_KEY_REGISTRY

    pid, event_date, dbf = project_with_unlinked_scales

    at = app_test.run()
    _open_project(at, event_date)

    mismatches = []
    for entry in FLYER_KEY_REGISTRY:
        if not entry.persist or entry.short_key not in dbf:
            continue
        try:
            actual = at.session_state[f"flyer_{entry.short_key}"]
        except Exception:
            actual = "(session に無い)"
        if actual != dbf[entry.short_key]:
            mismatches.append((entry.short_key, dbf[entry.short_key], actual))

    assert not mismatches, (
        f"id={pid} を開いただけで DB と食い違ったキー: "
        + ", ".join(f"{k}: DB={d!r} → session={a!r}" for k, d, a in mismatches)
    )


@pytest.mark.parametrize("prefix", ["grid", "tt"])
def test_link_follows_only_on_width_change(
    app_test, project_with_unlinked_scales, prefix
):
    """🔗 の機能自体は生きている: 横幅を操作したときだけ高さが追随する。

    on_change コールバック(_sync_linked_scale_h)経由なので、ユーザー操作時のみ発火する。
    """
    _pid, event_date, _dbf = project_with_unlinked_scales

    at = app_test.run()
    _open_project(at, event_date)

    # 🔗 は persist=False・既定 True。念のため ON であることを前提条件として確認。
    if not at.session_state[f"flyer_{prefix}_link"]:
        pytest.skip(f"flyer_{prefix}_link が OFF のため連動を検証できない")

    new_w = 123  # 既存値と確実に異なる値(スライダー範囲 10-150 内)
    assert at.session_state[f"flyer_{prefix}_scale_w"] != new_w
    at.slider(key=f"flyer_{prefix}_scale_w").set_value(new_w).run()
    assert not at.exception, f"横幅操作で例外: {at.exception}"

    assert at.session_state[f"flyer_{prefix}_scale_w"] == new_w
    assert at.session_state[f"flyer_{prefix}_scale_h"] == new_w, (
        f"🔗 ON で横幅を {new_w} にしたのに flyer_{prefix}_scale_h が追随していない "
        f"(実際: {at.session_state[f'flyer_{prefix}_scale_h']})"
    )
