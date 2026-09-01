# -*- coding: utf-8 -*-
"""アー写グリッド非表示: seed(移行フォールバック)の機械検証。DB / streamlit 非依存。

検証内容:
  (A) grid_hidden キーが【無い】既存プロジェクト → is_grid_hidden = is_hidden
      ★build_grid_order_from_rows の出力が「変更前(is_hidden で除外)」と一致する
        = 既存プロジェクトの見た目が変わらない
  (B) grid_hidden キーが【ある】(空リスト含む) → その名前リストが正
      ★空リストを「未移行」と誤判定して is_hidden を引き継がないこと
  (C) 特殊行は常に対象外
  (D) 壊れた値(None / dict / 非リスト / None 混じり)でも例外を出さない
  (E) 保存 → 再読込の往復で is_grid_hidden が保たれる
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.timetable import (  # noqa: E402
    POST_GOODS_ARTIST_NAME,
    PRE_GOODS_ARTIST_NAME,
    TimetableRowDraft,
    build_grid_hidden_from_rows,
    build_grid_order_from_rows,
    seed_grid_hidden_from_settings,
)

fails = 0


def _chk(ok, label, extra=""):
    global fails
    print(("  PASS  " if ok else "  FAIL  ") + label + (("  " + extra) if extra else ""))
    if not ok:
        fails += 1


def _n(name, grid_no=None, tt_hidden=False):
    return TimetableRowDraft(artist_name=name, place="A", grid_no=grid_no, is_hidden=tt_hidden)


def _pre():
    return TimetableRowDraft(artist_name=PRE_GOODS_ARTIST_NAME, duration=0)


def _post():
    return TimetableRowDraft(artist_name=POST_GOODS_ARTIST_NAME, duration=0)


def _legacy_order(rows):
    """変更前の build_grid_order_from_rows(除外条件が is_hidden だった頃)の等価実装。"""
    indexed = []
    for i, r in enumerate(rows or []):
        if r.is_special_row or r.is_hidden:
            continue
        name = (r.artist_name or "").strip()
        if not name:
            continue
        no_input = r.grid_no is None
        indexed.append((no_input, 0 if no_input else int(r.grid_no), i, name))
    indexed.sort(key=lambda t: (t[0], t[1], t[2]))
    return list(dict.fromkeys(n for _, _, _, n in indexed))


print("=" * 70)
print("(A) ★未移行プロジェクト: is_hidden を引き継いで見た目が変わらない")
print("=" * 70)
CASES = [
    ("非表示なし", [_n("A", 1), _n("B", 2), _n("C", 3)]),
    ("1人が非表示", [_n("A", 1), _n("B", 2, tt_hidden=True), _n("C", 3)]),
    ("複数非表示", [_n("A", 1, tt_hidden=True), _n("B", 2), _n("C", 3, tt_hidden=True)]),
    ("全員非表示", [_n("A", 1, tt_hidden=True), _n("B", 2, tt_hidden=True)]),
    ("特殊行あり", [_pre(), _n("A", 1, tt_hidden=True), _n("B", 2), _post()]),
    ("番号未入力混在", [_n("A"), _n("B", 1, tt_hidden=True), _n("C")]),
]
for label, rows in CASES:
    before = _legacy_order(rows)                 # 変更前の出力
    seed_grid_hidden_from_settings(rows, {})     # grid_hidden キー無し = 未移行
    after = build_grid_order_from_rows(rows)     # 変更後の出力
    _chk(before == after, "%s: 変更前後でグリッド出力が一致" % label, "-> %s" % after)

rows = [_n("A", 1, tt_hidden=True), _n("B", 2)]
seed_grid_hidden_from_settings(rows, {})
_chk([r.is_grid_hidden for r in rows] == [True, False],
     "is_grid_hidden が is_hidden から引き継がれる")
_chk([r.is_hidden for r in rows] == [True, False], "is_hidden 自体は書き換えない")

print()
print("=" * 70)
print("(B) ★移行済みプロジェクト: grid_hidden キーが正(空リストも含む)")
print("=" * 70)
rows = [_n("A", 1, tt_hidden=True), _n("B", 2), _n("C", 3)]
seed_grid_hidden_from_settings(rows, {"grid_hidden": ["B"]})
_chk([r.is_grid_hidden for r in rows] == [False, True, False],
     "名前リストどおりに復元(is_hidden とは独立)",
     "-> %s" % [r.is_grid_hidden for r in rows])
_chk(build_grid_order_from_rows(rows) == ["A", "C"],
     "TT非表示の A はグリッドに出る / グリッド非表示の B は消える",
     "-> %s" % build_grid_order_from_rows(rows))

rows = [_n("A", 1, tt_hidden=True), _n("B", 2)]
seed_grid_hidden_from_settings(rows, {"grid_hidden": []})
_chk([r.is_grid_hidden for r in rows] == [False, False],
     "★空リストは『誰も非表示でない』(is_hidden を引き継がない)",
     "-> %s" % [r.is_grid_hidden for r in rows])
_chk(build_grid_order_from_rows(rows) == ["A", "B"],
     "空リストなら TT非表示の人もグリッドには出る", "-> %s" % build_grid_order_from_rows(rows))

rows = [_n("  A  ", 1)]
seed_grid_hidden_from_settings(rows, {"grid_hidden": ["A"]})
_chk(rows[0].is_grid_hidden is True, "名前は strip して突合する")

print()
print("=" * 70)
print("(C) 特殊行は常に対象外")
print("=" * 70)
rows = [_pre(), _n("A", 1), _post()]
seed_grid_hidden_from_settings(rows, {"grid_hidden": [PRE_GOODS_ARTIST_NAME, POST_GOODS_ARTIST_NAME]})
_chk([r.is_grid_hidden for r in rows] == [False, False, False],
     "特殊行は grid_hidden に名前があっても False のまま")
rows = [_pre(), _n("A", 1)]
rows[0].is_hidden = True
seed_grid_hidden_from_settings(rows, {})
_chk(rows[0].is_grid_hidden is False, "未移行フォールバックでも特殊行は False")

print()
print("=" * 70)
print("(D) 壊れた値の耐性")
print("=" * 70)
for label, gs in [
    ("grid_settings=None", None),
    ("grid_settings=非dict", ["x"]),
    ("grid_hidden=None", {"grid_hidden": None}),
    ("grid_hidden=非リスト", {"grid_hidden": "AB"}),
    ("grid_hidden に None 混じり", {"grid_hidden": ["A", None, "", "  "]}),
]:
    rows = [_n("A", 1), _n("B", 2)]
    try:
        seed_grid_hidden_from_settings(rows, gs)
        _chk(True, "%s で例外なし" % label, "-> %s" % [r.is_grid_hidden for r in rows])
    except Exception as e:
        _chk(False, "%s で例外: %r" % (label, e))

print()
print("=" * 70)
print("(E) 保存 → 再読込の往復")
print("=" * 70)
rows = [_n("A", 1), _n("B", 2), _n("C", 3)]
rows[1].is_grid_hidden = True
saved = build_grid_hidden_from_rows(rows)          # 保存時に畳む
reloaded = [_n("A", 1), _n("B", 2), _n("C", 3)]    # DB から読み直し (全部 False)
seed_grid_hidden_from_settings(reloaded, {"grid_hidden": saved})
_chk([r.is_grid_hidden for r in reloaded] == [False, True, False],
     "保存 → 再読込で is_grid_hidden が保たれる", "-> saved=%s" % saved)
_chk(build_grid_order_from_rows(rows) == build_grid_order_from_rows(reloaded),
     "往復前後でグリッド出力が一致")

print()
print("GRID_HIDDEN_MIGRATION_ALL_PASS" if fails == 0 else "GRID_HIDDEN_MIGRATION_FAILED (%d)" % fails)
sys.exit(0 if fails == 0 else 1)
