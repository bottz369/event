"""TT エディタ「2回目の編集が消える」バグの再現/切り分け(read-only DB)。

Phase 0 で確定した構造的原因:
- views/timetable.py の data_editor 同期(L511-516)は上流 rerun 群(L405-483 の
  _bump_editor_seq()+st.rerun())より下流。上流 rerun が走ると同期に到達せず、
  かつ _bump_editor_seq() が data_editor の key を変えて保留デルタを破棄する。

制約: Streamlit 1.50 の AppTest は st.data_editor を操作できない(widget アクセサ無し)。
そのため data_editor の直接操作による再現は不可。本ファイルは
(1) AppTest で操作可能な上流 widget(checkbox/selectbox/button)が tt_editor_key を
    bump し rerun するか(= 保留デルタ破棄の前提)を機械確認する切り分けに用いる。
(2) session_state 注入で data_editor の擬似編集が反映されるかも試す(反映されなければ
    AppTest 限界として記録)。

コミット/push はしない(犯人特定後に修正とセットで回帰網化する)。
"""
from __future__ import annotations

import pytest

SELECTOR_KEY = "ws_project_selector_label"


def _open_project_tt(at, label):
    """プロジェクトを選択して run(workspace は st.tabs で TT を eager 描画)。"""
    at.selectbox(key=SELECTOR_KEY).select(label).run()
    return at


def test_probe_tt_tab_structure(app_test, two_projects_different_row_counts):
    """TT タブ到達時の session_state と操作可能 widget を可視化する probe。"""
    (_pid_a, label_a, _rc_a), _ = two_projects_different_row_counts

    at = app_test.run()
    assert not at.exception, f"初期描画で例外: {at.exception}"

    options = at.selectbox(key=SELECTOR_KEY).options
    if label_a not in options:
        pytest.skip(f"selectbox にラベル '{label_a}' 不在")

    _open_project_tt(at, label_a)
    assert not at.exception, f"プロジェクト選択後に例外: {at.exception}"

    # session_state の主要キー(既知キーを直接アクセス。列挙 API 差異を避ける)
    ss = at.session_state
    def _sget(k, default=None):
        try:
            return ss[k]
        except Exception:
            return default
    print("\n[PROBE] tt_editor_key =", _sget("tt_editor_key"))
    print("[PROBE] tt_unsaved_changes =", _sget("tt_unsaved_changes"))
    print("[PROBE] request_calc =", _sget("request_calc"))
    dr = _sget("draft_rows")
    print("[PROBE] draft_rows type/len =", type(dr).__name__,
          len(dr) if dr is not None else None)
    if dr:
        print("[PROBE] draft_rows[0] artist_name/duration =",
              getattr(dr[0], "artist_name", "?"), getattr(dr[0], "duration", "?"))

    # 操作可能 widget の keys(TT タブ配下)
    try:
        cb_keys = [c.key for c in at.checkbox]
    except Exception as e:
        cb_keys = f"error: {e}"
    try:
        sb_keys = [s.key for s in at.selectbox]
    except Exception as e:
        sb_keys = f"error: {e}"
    try:
        btn_labels = [b.label for b in at.button]
    except Exception as e:
        btn_labels = f"error: {e}"
    print("[PROBE] checkbox keys:", cb_keys)
    print("[PROBE] selectbox keys:", sb_keys)
    print("[PROBE] button labels:", btn_labels)

    # data_editor がツリーにあるか(get で汎用アクセス試行)
    try:
        de = at.get("arrow_data_frame")  # data_editor の内部要素名候補
        print("[PROBE] get('arrow_data_frame') count:", len(de))
    except Exception as e:
        print("[PROBE] get('arrow_data_frame') error:", e)
    for cand in ("data_editor", "arrow_data_editor"):
        try:
            print(f"[PROBE] get('{cand}') count:", len(at.get(cand)))
        except Exception as e:
            print(f"[PROBE] get('{cand}') error:", e)

    # sort_items(streamlit_sortables=カスタムコンポーネント)の tree 上の存在
    for cand in ("component_instance", "iframe"):
        try:
            print(f"[PROBE] get('{cand}') count:", len(at.get(cand)))
        except Exception as e:
            print(f"[PROBE] get('{cand}') error:", e)

    assert True  # probe は情報収集のみ


def _sget(at, k, default=None):
    try:
        return at.session_state[k]
    except Exception:
        return default


def test_spurious_rerun_on_noop(app_test, two_projects_different_row_counts):
    """無操作の連続 run で tt_editor_key / draft_rows が動くか(spurious rerun 検出)。

    sort_items(L432)や keyless checkbox(L470)が毎 run で条件 True になり
    _bump_editor_seq()+st.rerun() を spurious に起こすなら、無操作でも
    tt_editor_key が増えるか draft_rows が変わる。安定なら spurious rerun は無い。
    """
    (_pid_a, label_a, _rc_a), _ = two_projects_different_row_counts
    at = app_test.run()
    options = at.selectbox(key=SELECTOR_KEY).options
    if label_a not in options:
        pytest.skip(f"selectbox にラベル '{label_a}' 不在")
    _open_project_tt(at, label_a)
    assert not at.exception

    k0 = _sget(at, "tt_editor_key")
    dr0 = _sget(at, "draft_rows")
    len0 = len(dr0) if dr0 else None
    names0 = [getattr(r, "artist_name", "?") for r in (dr0 or [])]

    # 無操作で再 run を数回
    seq = [k0]
    for _ in range(3):
        at.run()
        seq.append(_sget(at, "tt_editor_key"))
    dr1 = _sget(at, "draft_rows")
    len1 = len(dr1) if dr1 else None
    names1 = [getattr(r, "artist_name", "?") for r in (dr1 or [])]

    print("\n[NOOP] tt_editor_key seq:", seq)
    print("[NOOP] draft_rows len:", len0, "->", len1)
    print("[NOOP] names unchanged:", names0 == names1)
    print("[NOOP] exception:", at.exception)

    # 結果は assert せず記録(spurious の有無を可視化)。安定=犯人は spurious rerun でない。
    assert True


def test_upstream_bump_discards_pending(app_test, two_projects_different_row_counts):
    """上流 widget 操作で tt_editor_key が bump するか(=保留 data_editor デルタ破棄の前提)。

    data_editor は AppTest 非操作のため、pending 編集の直接注入はできない。
    ここでは「上流 widget を触ると editor key が変わる(保留デルタが消える構造)」を確認する。
    """
    (_pid_a, label_a, _rc_a), _ = two_projects_different_row_counts
    at = app_test.run()
    options = at.selectbox(key=SELECTOR_KEY).options
    if label_a not in options:
        pytest.skip(f"selectbox にラベル '{label_a}' 不在")
    _open_project_tt(at, label_a)
    assert not at.exception

    k_before = _sget(at, "tt_editor_key")

    # 「開演前物販を表示」checkbox(keyless・L470)を label で特定して toggle
    pre_cb = None
    for c in at.checkbox:
        if c.label and "開演前物販" in c.label:
            pre_cb = c
            break
    result = {"pre_checkbox_found": pre_cb is not None, "k_before": k_before}
    if pre_cb is not None:
        cur = pre_cb.value
        pre_cb.set_value(not cur).run()
        result["k_after_pretoggle"] = _sget(at, "tt_editor_key")
        result["pretoggle_bumped"] = result["k_after_pretoggle"] != k_before
        result["exception"] = str(at.exception) if at.exception else None
    print("\n[BUMP] result:", result)
    assert True


def test_editor_state_injection_feasibility(app_test, two_projects_different_row_counts):
    """data_editor の session_state(tt_editor_0=edited_rows)を注入して擬似編集が
    反映されるか試す。反映されれば案a(純 data_editor feedback)を機械検証できる。
    反映されなければ AppTest では data_editor 編集を注入不可と結論。"""
    (_pid_a, label_a, _rc_a), _ = two_projects_different_row_counts
    at = app_test.run()
    options = at.selectbox(key=SELECTOR_KEY).options
    if label_a not in options:
        pytest.skip(f"selectbox にラベル '{label_a}' 不在")
    _open_project_tt(at, label_a)
    assert not at.exception

    k = _sget(at, "tt_editor_key")
    editor_key = f"tt_editor_{k}"
    dr0 = _sget(at, "draft_rows")
    before_dur = getattr(dr0[0], "duration", None) if dr0 else None
    new_dur = 30 if before_dur != 30 else 25

    injected = False
    try:
        at.session_state[editor_key] = {
            "edited_rows": {0: {"DURATION": new_dur}},
            "added_rows": [],
            "deleted_rows": [],
        }
        injected = True
    except Exception as e:
        print("\n[INJECT] session_state 注入失敗:", e)

    reflected = None
    if injected:
        at.run()
        dr1 = _sget(at, "draft_rows")
        after_dur = getattr(dr1[0], "duration", None) if dr1 else None
        reflected = (after_dur == new_dur)
        print(f"\n[INJECT] editor_key={editor_key} before_dur={before_dur} "
              f"new_dur={new_dur} after_dur={after_dur} reflected={reflected} "
              f"exception={at.exception}")
    print("[INJECT] 注入で擬似編集が draft_rows に反映されたか:", reflected)
    assert True


def test_add_button_bump(app_test, two_projects_different_row_counts):
    """『＋』(追加)ボタン(L427 で _bump_editor_seq)で tt_editor_key が bump するか。"""
    (_pid_a, label_a, _rc_a), _ = two_projects_different_row_counts
    at = app_test.run()
    options = at.selectbox(key=SELECTOR_KEY).options
    if label_a not in options:
        pytest.skip(f"selectbox にラベル '{label_a}' 不在")
    _open_project_tt(at, label_a)
    assert not at.exception

    k_before = _sget(at, "tt_editor_key")
    # 追加 selectbox(keyless)に1件選び ＋ を押す
    add_sb = None
    for s in at.selectbox:
        # 追加 selectbox は options 先頭が "" で、tt_open_time/tt_start_time 等の
        # 既知 key を持たない(key=None)。候補を options で判定。
        if s.key is None and len(s.options) > 1 and s.options[0] == "":
            add_sb = s
            break
    result = {"add_sb_found": add_sb is not None, "k_before": k_before}
    if add_sb is not None and len(add_sb.options) > 1:
        add_sb.select(add_sb.options[1]).run()
        # ＋ ボタンを押す
        plus = None
        for b in at.button:
            if b.label == "＋":
                plus = b
                break
        if plus is not None:
            plus.click().run()
            result["k_after_add"] = _sget(at, "tt_editor_key")
            result["add_bumped"] = result["k_after_add"] != k_before
            result["exception"] = str(at.exception) if at.exception else None
    print("\n[ADD] result:", result)
    assert True


def _durations(dr):
    return [getattr(r, "duration", None) for r in (dr or [])]


def test_repro_case_a_pure_editor_two_edits(app_test, two_projects_different_row_counts):
    """案a: 上流 widget を触らず data_editor に2連続編集を注入 → 両方残るか。

    tt_editor_key が bump しない純 data_editor 経路。両方残れば案a単独では消えない
    (=消える主因は上流 rerun/bump 側)ことの機械証拠になる。"""
    (_pid_a, label_a, _rc_a), _ = two_projects_different_row_counts
    at = app_test.run()
    if label_a not in at.selectbox(key=SELECTOR_KEY).options:
        pytest.skip("label 不在")
    _open_project_tt(at, label_a)
    assert not at.exception

    k = _sget(at, "tt_editor_key")
    # 編集A: row0 DURATION=35
    at.session_state[f"tt_editor_{k}"] = {
        "edited_rows": {0: {"DURATION": 35}}, "added_rows": [], "deleted_rows": []}
    at.run()
    durs_after_a = _durations(_sget(at, "draft_rows"))
    k2 = _sget(at, "tt_editor_key")

    # 編集B: row1 DURATION=45(key は bump していない想定=同じ tt_editor_{k})
    at.session_state[f"tt_editor_{k2}"] = {
        "edited_rows": {1: {"DURATION": 45}}, "added_rows": [], "deleted_rows": []}
    at.run()
    durs_after_b = _durations(_sget(at, "draft_rows"))

    print("\n[CASE_A] k:", k, "->", k2)
    print("[CASE_A] durs after A:", durs_after_a[:3])
    print("[CASE_A] durs after B:", durs_after_b[:3])
    a_kept = 35 in durs_after_b
    b_kept = 45 in durs_after_b
    print(f"[CASE_A] A(35) kept={a_kept}  B(45) kept={b_kept}")
    # 回帰 assert: 純 data_editor の2連続編集で両方が draft_rows に残る。
    # 修正前は真因①で B が消える(RED)。修正後は先取り確定で両方残る(GREEN)。
    assert a_kept, "編集A(35)が draft_rows に残っていない"
    assert b_kept, "編集B(45)が消えた(真因①: data_editor 再フィードリセット)"


def test_repro_case_b_pending_edit_lost_on_checkbox(app_test, two_projects_different_row_counts):
    """案b(本命): data_editor 編集Aを『保留』したまま同一 run で上流 checkbox を toggle
    → Aが draft_rows に届く前に L470 が set_draft_rows+bump+rerun し、Aが消えるか。

    再現機序: 保留Aは tt_editor_{k} に居る。checkbox toggle が key を k+1 に bump+rerun
    → data_editor は新 key(空)で再初期化 → A のデルタ破棄 → L511 同期に A が乗らない。"""
    (_pid_a, label_a, _rc_a), _ = two_projects_different_row_counts
    at = app_test.run()
    if label_a not in at.selectbox(key=SELECTOR_KEY).options:
        pytest.skip("label 不在")
    _open_project_tt(at, label_a)
    assert not at.exception

    k = _sget(at, "tt_editor_key")
    durs_before = _durations(_sget(at, "draft_rows"))
    MARK = 35 if 35 not in durs_before else 40  # 元データに無い識別値

    # 保留編集A(row0 DURATION=MARK)を tt_editor_{k} に注入
    at.session_state[f"tt_editor_{k}"] = {
        "edited_rows": {0: {"DURATION": MARK}}, "added_rows": [], "deleted_rows": []}
    # 同一 run で上流 checkbox(開演前物販)を toggle
    pre_cb = None
    for c in at.checkbox:
        if c.label and "開演前物販" in c.label:
            pre_cb = c
            break
    if pre_cb is None:
        pytest.skip("開演前物販 checkbox 不在")
    pre_cb.set_value(not pre_cb.value).run()

    durs_after = _durations(_sget(at, "draft_rows"))
    k_after = _sget(at, "tt_editor_key")
    a_survived = MARK in durs_after

    print("\n[CASE_B] tt_editor_key:", k, "->", k_after, "(bump 想定)")
    print("[CASE_B] MARK(保留編集A の DURATION):", MARK)
    print("[CASE_B] durs before:", durs_before[:4])
    print("[CASE_B] durs after :", durs_after[:4])
    print(f"[CASE_B] A survived={a_survived}  (False=編集Aが消えた=再現)")
    print("[CASE_B] exception:", at.exception)
    # 回帰 assert: 保留セル編集 + 上流 checkbox toggle でも編集Aが残る。
    # 修正前は真因②(bump 前に未確定)で消える(RED)。修正後は先取り確定で残る(GREEN)。
    assert a_survived, "編集A(保留)が checkbox toggle で消えた(真因②: bump 前に未確定)"


def test_pregoods_normalize_nonregression(app_test, two_projects_different_row_counts):
    """§13.1 非回帰: 先取り確定を挟んでも、開演前物販行の goods_start_time が
    open_time に追従し duration/adjustment=0 に固定される(_normalize_edited_rows)。"""
    (_pid_a, label_a, _rc_a), _ = two_projects_different_row_counts
    at = app_test.run()
    if label_a not in at.selectbox(key=SELECTOR_KEY).options:
        pytest.skip("label 不在")
    _open_project_tt(at, label_a)
    assert not at.exception

    open_time = _sget(at, "tt_open_time")

    pre_cb = None
    for c in at.checkbox:
        if c.label and "開演前物販" in c.label:
            pre_cb = c
            break
    if pre_cb is None:
        pytest.skip("開演前物販 checkbox 不在")
    if not pre_cb.value:
        pre_cb.set_value(True).run()
    assert not at.exception

    # セル編集を注入(先取り確定を発火)→ pre-goods の仕様固定が保たれるか
    k = _sget(at, "tt_editor_key")
    at.session_state[f"tt_editor_{k}"] = {
        "edited_rows": {1: {"DURATION": 30}}, "added_rows": [], "deleted_rows": []}
    at.run()
    assert not at.exception

    dr = _sget(at, "draft_rows")
    pre = None
    for r in (dr or []):
        if getattr(r, "artist_name", "") == "開演前物販":
            pre = r
            break
    print("\n[PREGOODS] open_time:", open_time,
          "pre_found:", pre is not None,
          "goods_start:", getattr(pre, "goods_start_time", None) if pre else None,
          "duration:", getattr(pre, "duration", None) if pre else None,
          "adjustment:", getattr(pre, "adjustment", None) if pre else None)
    if pre is None:
        pytest.skip("開演前物販行が生成されなかった(プロジェクト状態依存)")
    assert pre.goods_start_time == open_time, "goods_start_time が open_time に追従していない"
    assert pre.duration == 0, "開演前物販の duration が 0 固定でない"
    assert pre.adjustment == 0, "開演前物販の adjustment が 0 固定でない"


# ---------------------------------------------------------------------------
# 段階①: 「行の一括削除」の回帰網(DELETE 列 → 先取り確定 → 一括削除)
# ---------------------------------------------------------------------------
def _normal_rows(at):
    """draft_rows のうち通常行(特殊行以外)の名前一覧。"""
    return [
        r.artist_name for r in (_sget(at, "draft_rows") or [])
        if r.artist_name not in ("開演前物販", "終演後物販")
    ]


def _inject_delete_check(at, row_index):
    """data_editor の内部 state に「DELETE 列のチェック」を注入する(罠34 の回避策)。

    AppTest は data_editor を直接操作できないため、既存の
    test_editor_state_injection_feasibility と同じ session_state 注入で代替する。
    """
    editor_key = f"tt_editor_{_sget(at, 'tt_editor_key')}"
    at.session_state[editor_key] = {
        "edited_rows": {row_index: {"DELETE": True}},
        "added_rows": [],
        "deleted_rows": [],
    }
    at.run()
    return at


def test_bulk_delete_removes_checked_row(app_test, two_projects_different_row_counts):
    """DELETE 列のチェックが先取り確定を通り、ボタンで実際に行が消えること。

    ★これが RED になるとき疑うのは罠33: DELETE が draft_rows_to_df の出力列で
    なくなると _apply_editor_state_to_df の `if col in new_df.columns` ガードに
    弾かれ、チェックが毎 run 捨てられて一括削除が沈黙する。
    """
    (_pid_a, label_a, _rc_a), _ = two_projects_different_row_counts
    at = app_test.run()
    options = at.selectbox(key=SELECTOR_KEY).options
    if label_a not in options:
        pytest.skip(f"selectbox にラベル '{label_a}' 不在")
    _open_project_tt(at, label_a)
    assert not at.exception

    rows_before = _sget(at, "draft_rows") or []
    if len(rows_before) < 2:
        pytest.skip("行数が足りない(プロジェクト状態依存)")

    # 通常行を1つ選んでチェックを注入する
    target_idx = next(
        (i for i, r in enumerate(rows_before)
         if r.artist_name not in ("開演前物販", "終演後物販")),
        None,
    )
    if target_idx is None:
        pytest.skip("通常行が無い")
    target_name = rows_before[target_idx].artist_name
    names_before = _normal_rows(at)

    _inject_delete_check(at, target_idx)
    assert not at.exception, f"チェック注入後に例外: {at.exception}"

    dr = _sget(at, "draft_rows") or []
    assert dr[target_idx].is_delete_marked is True, (
        "DELETE のチェックが draft_rows に届いていない(罠33 の再発を疑う)"
    )

    snap_before = _sget(at, "saved_rows_snapshot")
    at.button(key="btn_tt_bulk_delete").click().run()
    assert not at.exception, f"一括削除ボタンで例外: {at.exception}"

    names_after = _normal_rows(at)
    expected = list(names_before)
    expected.remove(target_name)
    assert names_after == expected, (
        f"チェックした行だけが消えていない: before={names_before} after={names_after}"
    )

    # ★DB 保存は走らない(保存は「🔄 設定反映」のみ)
    assert _sget(at, "saved_rows_snapshot") == snap_before, (
        "一括削除で保存スナップショットが更新された = DB 保存が走っている"
    )
    assert _sget(at, "tt_unsaved_changes") is True, "mark_dirty されていない"


def test_bulk_delete_button_disabled_without_check(app_test, two_projects_different_row_counts):
    """チェックが1つも無い状態では一括削除ボタンが押せないこと(誤爆防止)。"""
    (_pid_a, label_a, _rc_a), _ = two_projects_different_row_counts
    at = app_test.run()
    options = at.selectbox(key=SELECTOR_KEY).options
    if label_a not in options:
        pytest.skip(f"selectbox にラベル '{label_a}' 不在")
    _open_project_tt(at, label_a)
    assert not at.exception

    # at.button(key=...) は Button を直接返す(list ではない)
    btn = at.button(key="btn_tt_bulk_delete")
    assert btn is not None, "一括削除ボタンが描画されていない"
    assert btn.disabled is True, "チェック無しでもボタンが有効になっている"


# ---------------------------------------------------------------------------
# 段階②: 「アー写グリッド表示順」(GRID_NO) の回帰網
# ---------------------------------------------------------------------------
UNSAVED_WARNING_TEXT = "未保存の変更があります"


def _open_first_project(at):
    """selectbox で最初の実プロジェクトを開く。無ければ skip。"""
    options = [
        o for o in at.selectbox(key=SELECTOR_KEY).options
        if o not in ("(選択してください)", "➕ 新規プロジェクト作成")
    ]
    if not options:
        pytest.skip("選択できるプロジェクトが無い")
    at.selectbox(key=SELECTOR_KEY).select(options[0]).run()
    assert not at.exception, f"プロジェクト選択で例外: {at.exception}"
    return options[0]


def test_grid_no_seeded_from_saved_order(app_test, two_projects_different_row_counts):
    """読込時に grid_no が保存済み grid_order の位置から復元され、
    build_grid_order_from_rows がその並びを再現すること。

    = 番号列を足しても初期表示のグリッド並びが変わらないことの回帰網。
    """
    from models.timetable import build_grid_order_from_rows

    at = app_test.run()
    assert not at.exception
    _open_first_project(at)

    rows = _sget(at, "draft_rows") or []
    order = [str(n).strip() for n in (_sget(at, "grid_order") or []) if str(n).strip()]
    if not order:
        pytest.skip("保存済み grid_order が無いプロジェクト")

    assert any(r.grid_no is not None for r in rows), (
        "grid_no が復元されていない(seed_grid_no_from_order の退行を疑う)"
    )

    tt_names = {(r.artist_name or "").strip() for r in rows}
    expected = [n for n in dict.fromkeys(order) if n in tt_names]
    rebuilt = build_grid_order_from_rows(rows)
    assert rebuilt[: len(expected)] == expected, (
        f"保存済み order の並びを再現していない: expected={expected[:5]} got={rebuilt[:5]}"
    )


def test_no_false_unsaved_warning_on_open(app_test, two_projects_different_row_counts):
    """プロジェクトを開いただけで「未保存の変更があります」が出ないこと。

    grid_no は _rows_to_comparable に含まれるため、採番を
    session_manager.reload_project() の _save_snapshot() より後で行うと
    開いた瞬間に誤警告が出る。その退行を止める回帰網。
    """
    at = app_test.run()
    assert not at.exception
    _open_first_project(at)

    warnings = [w.value for w in at.warning]
    assert not any(UNSAVED_WARNING_TEXT in str(w) for w in warnings), (
        f"開いただけで未保存警告が出ている: {warnings}"
    )


def test_grid_no_edit_reaches_draft_rows(app_test, two_projects_different_row_counts):
    """GRID_NO の編集が先取り確定を通って draft_rows に届くこと(罠33)。

    ★RED になるときは GRID_NO が draft_rows_to_df の出力列から外れていないか疑う。
    """
    at = app_test.run()
    assert not at.exception
    _open_first_project(at)

    rows = _sget(at, "draft_rows") or []
    target = next(
        (i for i, r in enumerate(rows)
         if r.artist_name not in ("開演前物販", "終演後物販")),
        None,
    )
    if target is None:
        pytest.skip("通常行が無い")

    editor_key = f"tt_editor_{_sget(at, 'tt_editor_key')}"
    at.session_state[editor_key] = {
        "edited_rows": {target: {"GRID_NO": 99}},
        "added_rows": [],
        "deleted_rows": [],
    }
    at.run()
    assert not at.exception, f"GRID_NO 注入後に例外: {at.exception}"

    dr = _sget(at, "draft_rows") or []
    assert dr[target].grid_no == 99, (
        "GRID_NO の編集が draft_rows に届いていない(罠33 の再発を疑う)"
    )
    # 番号を変えたら未保存扱いになる(黙って失われない)
    assert _sget(at, "tt_unsaved_changes") is True


# ---------------------------------------------------------------------------
# アー写グリッド非表示 (GRID_HIDDEN) の回帰網
# ---------------------------------------------------------------------------
def test_grid_hidden_edit_reaches_draft_rows(app_test, two_projects_different_row_counts):
    """GRID_HIDDEN の編集が先取り確定を通って draft_rows に届くこと(罠33)。

    ★RED になるときは GRID_HIDDEN が draft_rows_to_df の出力列から
    外れていないか疑う。
    """
    from models.timetable import build_grid_order_from_rows

    at = app_test.run()
    assert not at.exception
    _open_first_project(at)

    rows = _sget(at, "draft_rows") or []
    target = next(
        (i for i, r in enumerate(rows)
         if r.artist_name not in ("開演前物販", "終演後物販")
         and not r.is_grid_hidden
         and (r.artist_name or "").strip()),
        None,
    )
    if target is None:
        pytest.skip("グリッド表示中の通常行が無い")
    target_name = rows[target].artist_name.strip()
    assert target_name in build_grid_order_from_rows(rows), "前提: 対象はグリッドに出ている"

    editor_key = f"tt_editor_{_sget(at, 'tt_editor_key')}"
    at.session_state[editor_key] = {
        "edited_rows": {target: {"GRID_HIDDEN": True}},
        "added_rows": [],
        "deleted_rows": [],
    }
    at.run()
    assert not at.exception, f"GRID_HIDDEN 注入後に例外: {at.exception}"

    dr = _sget(at, "draft_rows") or []
    assert dr[target].is_grid_hidden is True, (
        "GRID_HIDDEN の編集が draft_rows に届いていない(罠33 の再発を疑う)"
    )
    # グリッドからは消えるが、タイムテーブル非表示(is_hidden)は変わらない
    assert target_name not in build_grid_order_from_rows(dr), "グリッドから外れていない"
    assert dr[target].is_hidden == rows[target].is_hidden, (
        "アー写グリッド非表示がタイムテーブル非表示に波及している(2 つは独立のはず)"
    )
    assert _sget(at, "tt_unsaved_changes") is True


def test_grid_hidden_migration_preserves_look(app_test, two_projects_different_row_counts):
    """未移行プロジェクト(grid_hidden キー無し)は is_hidden から引き継がれること。

    = 既存プロジェクトのアー写グリッドの見た目が変わらないことの回帰網。
    """
    at = app_test.run()
    assert not at.exception
    _open_first_project(at)

    draft = _sget(at, "draft_project")
    rows = _sget(at, "draft_rows") or []
    if draft is None or not rows:
        pytest.skip("draft が取れない")

    gs = draft.grid_settings or {}
    if "grid_hidden" in gs:
        pytest.skip("既に移行済みのプロジェクト(このテストは未移行分を見る)")

    normal = [r for r in rows if r.artist_name not in ("開演前物販", "終演後物販")]
    assert [r.is_grid_hidden for r in normal] == [bool(r.is_hidden) for r in normal], (
        "未移行プロジェクトで is_grid_hidden が is_hidden から引き継がれていない"
        "(移行フォールバックの退行を疑う)"
    )
