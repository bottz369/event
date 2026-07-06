"""AppTest ヘッドレス・スモークテスト(read-only DB)。

(a) test_smoke_all_tabs: 既存プロジェクトを1つ選択し、workspace の全タブが
    例外なく描画される(at.exception が空)。
(b) test_no_value_bleed_on_switch: row_counts が異なる既存プロジェクト2件を
    交互に選択し、grid の text_input が各プロジェクトの値を表示する
    (プロジェクト間で混入しない = ホットフィックス 7379418 の回帰テスト)。

read-only のため新規作成・保存は一切行わない。
"""
from __future__ import annotations

import pytest

SELECTOR_KEY = "ws_project_selector_label"
ROW_COUNTS_WIDGET_KEY = "grid_row_counts_input_widget"


def _select_project(at, label):
    at.selectbox(key=SELECTOR_KEY).select(label).run()
    return at


def test_smoke_all_tabs(app_test, two_projects_different_row_counts):
    """プロジェクト選択後、workspace の 4 タブ(概要/TT/グリッド/フライヤー)が
    例外なく eager 描画されることを確認する。"""
    (_pid_a, label_a, _rc_a), _ = two_projects_different_row_counts

    at = app_test.run()
    assert not at.exception, f"初期描画で例外: {at.exception}"

    options = at.selectbox(key=SELECTOR_KEY).options
    if label_a not in options:
        pytest.skip(f"selectbox にラベル '{label_a}' が見つからない(ラベル整合ずれ)")

    _select_project(at, label_a)
    assert not at.exception, (
        f"プロジェクト '{label_a}' 選択後の全タブ描画で例外: {at.exception}"
    )

    # グリッドタブの主要 widget がツリー上に存在する(= grid タブが描画された)ことも確認
    assert at.text_input(key=ROW_COUNTS_WIDGET_KEY), "グリッドタブが描画されていない"


def test_no_value_bleed_on_switch(app_test, two_projects_different_row_counts):
    """プロジェクト切替時に grid の row_counts が他プロジェクトの値で汚染されない。

    回帰対象: 固定 key の text_input(grid_row_counts_input_widget)が切替時に
    clear されず前プロジェクトの値が残留するバグ(commit 7379418 で修正)。
    残留していると B 選択時に A の値が表示され v_a == v_b になる。
    """
    (_pid_a, label_a, _rc_a), (_pid_b, label_b, _rc_b) = two_projects_different_row_counts

    at = app_test.run()
    assert not at.exception, f"初期描画で例外: {at.exception}"

    options = at.selectbox(key=SELECTOR_KEY).options
    for lbl in (label_a, label_b):
        if lbl not in options:
            pytest.skip(f"selectbox にラベル '{lbl}' が見つからない(ラベル整合ずれ)")

    # A を選択 → grid の値
    _select_project(at, label_a)
    assert not at.exception, f"A 選択後に例外: {at.exception}"
    v_a = at.text_input(key=ROW_COUNTS_WIDGET_KEY).value

    # B を選択 → grid の値
    _select_project(at, label_b)
    assert not at.exception, f"B 選択後に例外: {at.exception}"
    v_b = at.text_input(key=ROW_COUNTS_WIDGET_KEY).value

    # A を再選択 → 値が安定して戻る
    _select_project(at, label_a)
    assert not at.exception, f"A 再選択後に例外: {at.exception}"
    v_a2 = at.text_input(key=ROW_COUNTS_WIDGET_KEY).value

    # 回帰判定: 残留していれば v_b は A の値と一致してしまう
    assert v_a != v_b, (
        "row_counts の値混入を検出(A と B が同一表示)。"
        f" A={v_a!r} B={v_b!r} — ホットフィックス 7379418 の退行の可能性。"
    )
    # 各プロジェクトが自分の値を安定して表示すること
    assert v_a == v_a2, (
        f"A の再選択で row_counts 表示が変動: 初回={v_a!r} 再選択={v_a2!r}"
    )
