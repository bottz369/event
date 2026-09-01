# -*- coding: utf-8 -*-
"""段階② build_grid_order_from_rows の機械検証 (DB・streamlit 非依存)。

検証内容:
  (A) 番号昇順で並ぶ / 未入力は末尾(TT出演順を保つ)
  (B) 番号重複は TT出演順(行index)でタイブレーク
  (C) 特殊行(開演前/終演後物販) と is_grid_hidden 行と空名を除外
      ★is_hidden(タイムテーブル非表示)では除外しないことも確認する
  (D) 同名重複は先頭のみ残す
  (E) ★現状 grid_order から採番したら現状 order を再現する(初期表示で見た目が変わらない)
  (F) ★TT にいない登録アーティストは出力に含まれない(仕様変更・合意済み)
  (G) 契約: 戻り値は必ず名前(str)の list
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.timetable import (  # noqa: E402
    POST_GOODS_ARTIST_NAME,
    build_grid_hidden_from_rows,
    PRE_GOODS_ARTIST_NAME,
    TimetableRowDraft,
    build_grid_order_from_rows,
)

fails = 0


def _chk(ok, label, extra=""):
    global fails
    print(("  PASS  " if ok else "  FAIL  ") + label + (("  " + extra) if extra else ""))
    if not ok:
        fails += 1


def _n(name, grid_no=None, grid_hidden=False, tt_hidden=False):
    return TimetableRowDraft(
        artist_name=name, place="A", grid_no=grid_no,
        is_grid_hidden=grid_hidden, is_hidden=tt_hidden,
    )


def _pre():
    return TimetableRowDraft(artist_name=PRE_GOODS_ARTIST_NAME, duration=0, grid_no=1)


def _post():
    return TimetableRowDraft(artist_name=POST_GOODS_ARTIST_NAME, duration=0, grid_no=1)


print("=" * 68)
print("(A) 番号昇順 / 未入力は末尾")
print("=" * 68)
rows = [_n("A", 3), _n("B", 1), _n("C", 2)]
out = build_grid_order_from_rows(rows)
_chk(out == ["B", "C", "A"], "番号の昇順で並ぶ", "-> %s" % out)

rows = [_n("A"), _n("B", 1), _n("C"), _n("D", 2)]
out = build_grid_order_from_rows(rows)
_chk(out == ["B", "D", "A", "C"],
     "未入力は末尾へ回り、その中では TT 出演順を保つ", "-> %s" % out)

rows = [_n("A"), _n("B"), _n("C")]
out = build_grid_order_from_rows(rows)
_chk(out == ["A", "B", "C"], "全員未入力なら TT 出演順そのまま", "-> %s" % out)

print()
print("=" * 68)
print("(B) 番号重複のタイブレーク")
print("=" * 68)
rows = [_n("A", 2), _n("B", 1), _n("C", 1), _n("D", 2)]
out = build_grid_order_from_rows(rows)
_chk(out == ["B", "C", "A", "D"],
     "同番号は TT 出演順(行index)で決定的に並ぶ", "-> %s" % out)

# 決定性: 同じ入力で何度呼んでも同じ
_chk(all(build_grid_order_from_rows(rows) == out for _ in range(5)), "何度呼んでも同じ結果(決定的)")

print()
print("=" * 68)
print("(C) 除外: 特殊行 / is_grid_hidden / 空名")
print("=" * 68)
rows = [_pre(), _n("A", 2), _n("B", 1), _post()]
out = build_grid_order_from_rows(rows)
_chk(out == ["B", "A"], "特殊行は番号が付いていても除外", "-> %s" % out)

rows = [_n("A", 1), _n("B", 2, grid_hidden=True), _n("C", 3)]
out = build_grid_order_from_rows(rows)
_chk(out == ["A", "C"], "is_grid_hidden 行は除外", "-> %s" % out)

# ★2 つのフラグが独立であること
rows = [_n("A", 1, tt_hidden=True), _n("B", 2), _n("C", 3, grid_hidden=True)]
out = build_grid_order_from_rows(rows)
_chk(out == ["A", "B"],
     "is_hidden(タイムテーブル非表示)では除外しない / is_grid_hidden でのみ除外",
     "-> %s" % out)

rows = [_n("A", 1, tt_hidden=True, grid_hidden=True), _n("B", 2)]
out = build_grid_order_from_rows(rows)
_chk(out == ["B"], "両方立っていればグリッドからも消える", "-> %s" % out)

rows = [_n("A", 1), _n("", 2), _n("   ", 3), _n("C", 4)]
out = build_grid_order_from_rows(rows)
_chk(out == ["A", "C"], "空名 / 空白のみの行は除外", "-> %s" % out)

rows = [_n("  D  ", 1), _n("E", 2)]
out = build_grid_order_from_rows(rows)
_chk(out == ["D", "E"], "名前は strip される(grid.py 従来フィルタと同じ)", "-> %s" % out)

print()
print("=" * 68)
print("(D) 同名重複")
print("=" * 68)
rows = [_n("A", 1), _n("B", 2), _n("A", 3)]
out = build_grid_order_from_rows(rows)
_chk(out == ["A", "B"], "同名は先に出た方だけ残す", "-> %s" % out)

print()
print("=" * 68)
print("(E) ★現状 order から採番 → 現状 order を再現")
print("=" * 68)
# 現状のグリッド並び(TT 出演順の逆順で作られているのが従来既定)
current_order = ["E", "D", "C", "B", "A"]
tt_rows = [_n(n) for n in ["A", "B", "C", "D", "E"]]
# views 側の初期採番と同じロジック: order 内の位置+1 を grid_no に入れる
pos = {name: i for i, name in enumerate(current_order)}
for r in tt_rows:
    if r.artist_name in pos:
        r.grid_no = pos[r.artist_name] + 1
out = build_grid_order_from_rows(tt_rows)
_chk(out == current_order, "現状 order を完全に再現(初期表示で見た目が変わらない)",
     "-> %s" % out)

# order に無い TT 行は None のまま = 末尾に TT 出演順で付く
tt_rows2 = [_n(n) for n in ["A", "B", "C", "D", "E", "NEW1", "NEW2"]]
for r in tt_rows2:
    if r.artist_name in pos:
        r.grid_no = pos[r.artist_name] + 1
out = build_grid_order_from_rows(tt_rows2)
_chk(out == current_order + ["NEW1", "NEW2"],
     "order に無い TT 行(新規追加)は末尾に TT 出演順で付く", "-> %s" % out)

print()
print("=" * 68)
print("(F) ★TT にいない登録アーティストは落ちる(仕様変更・合意済み)")
print("=" * 68)
# 旧 order には居るが TT には居ない "GHOST"
old_order = ["GHOST", "A", "B"]
tt_rows = [_n("A"), _n("B")]
pos = {name: i for i, name in enumerate(old_order)}
for r in tt_rows:
    if r.artist_name in pos:
        r.grid_no = pos[r.artist_name] + 1
out = build_grid_order_from_rows(tt_rows)
_chk("GHOST" not in out, "TT にいない名前は出力に含まれない", "-> %s" % out)
_chk(out == ["A", "B"], "残りは番号順で正しく並ぶ", "-> %s" % out)

print()
print("=" * 68)
print("(G) 契約: 名前(str)の list を返す")
print("=" * 68)
rows = [_pre(), _n("A", 1), _n("B"), _post()]
out = build_grid_order_from_rows(rows)
_chk(isinstance(out, list) and all(isinstance(x, str) for x in out),
     "戻り値は list[str](grid_order_json['order'] の契約)")
_chk(build_grid_order_from_rows([]) == [] and build_grid_order_from_rows(None) == [],
     "空 / None 入力で例外を出さず [] を返す")
_chk(build_grid_order_from_rows([_pre(), _post()]) == [],
     "特殊行しか無ければ空リスト")

print()
print("=" * 68)
print("(H) build_grid_hidden_from_rows (保存用の名前リスト)")
print("=" * 68)
rows = [_n("A", 1, grid_hidden=True), _n("B", 2), _n("C", 3, grid_hidden=True)]
out = build_grid_hidden_from_rows(rows)
_chk(out == ["A", "C"], "グリッド非表示の通常行の名前だけを返す", "-> %s" % out)

rows = [_pre(), _n("A", 1), _n("B", 2)]
rows[0].is_grid_hidden = True
out = build_grid_hidden_from_rows(rows)
_chk(out == [], "特殊行は対象外", "-> %s" % out)

rows = [_n("A", 1, tt_hidden=True), _n("B", 2)]
_chk(build_grid_hidden_from_rows(rows) == [],
     "is_hidden(タイムテーブル非表示)だけでは grid_hidden に入らない")

rows = [_n("  A  ", 1, grid_hidden=True), _n("A", 2, grid_hidden=True), _n("", 3, grid_hidden=True)]
out = build_grid_hidden_from_rows(rows)
_chk(out == ["A"], "strip + 重複除去 + 空名スキップ", "-> %s" % out)

_chk(build_grid_hidden_from_rows([]) == [] and build_grid_hidden_from_rows(None) == [],
     "空 / None 入力で [] を返す")
_chk(isinstance(build_grid_hidden_from_rows([_n("A", 1, grid_hidden=True)]), list),
     "戻り値は list[str]")

# ★キーの存在が移行済みフラグを兼ねるので、該当ゼロでも [] を返すこと
_chk(build_grid_hidden_from_rows([_n("A", 1), _n("B", 2)]) == [],
     "該当ゼロでも [] を返す(キー存在=移行済みの印になる)")

print()
print("BUILD_GRID_ORDER_ALL_PASS" if fails == 0 else "BUILD_GRID_ORDER_FAILED (%d)" % fails)
sys.exit(0 if fails == 0 else 1)
