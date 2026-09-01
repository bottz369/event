# -*- coding: utf-8 -*-
"""段階① 一括削除の機械検証 (DB 非接続・§12.4 方式)。

検証内容:
  (A) _drop_marked_rows: 特殊行は必ず残る / チェックした通常行だけ消える /
      残った行の順序保持 / 空チェック時は無変化 / 純関数性
  (B) _normalize_edited_rows が特殊行の is_delete_marked を False に倒す
  (C) ★先取り確定 (_apply_editor_state_to_df) を DELETE 列が通ること
      = 罠33 対策。ここが通らないとチェックが毎 run 捨てられて機能しない
  (D) 非永続の証明: timetable_repo の _draft_to_row → _row_to_draft 往復で
      is_delete_marked が False に戻る (DB へは書かれない = スキーマ変更ゼロ)
  (E) session_manager._rows_to_comparable が is_delete_marked を無視する
      (チェックしただけで「未保存」警告が出ない)

本番 DB へは一切接続しない (ダミー secrets を注入して import だけ通す)。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit.runtime.secrets as st_secrets

st_secrets.secrets_singleton._secrets = {
    "supabase": {
        "DB_URL": "postgresql://dummy:dummy@127.0.0.1:5432/dummy",
        "URL": "https://dummy.supabase.co",
        "KEY": "dummy-key",
    }
}

import streamlit as st  # noqa: E402

from models.timetable import (  # noqa: E402
    POST_GOODS_ARTIST_NAME,
    PRE_GOODS_ARTIST_NAME,
    TimetableRowDraft,
    df_to_draft_rows,
    draft_rows_to_df,
)
from repositories import timetable_repo  # noqa: E402
from services import session_manager  # noqa: E402
from views.timetable import (  # noqa: E402
    _apply_editor_state_to_df,
    _drop_marked_rows,
    _normalize_edited_rows,
)

fails = 0


def _chk(ok, label, extra=""):
    global fails
    print(("  PASS  " if ok else "  FAIL  ") + label + (("  " + extra) if extra else ""))
    if not ok:
        fails += 1


def _pre():
    return TimetableRowDraft(artist_name=PRE_GOODS_ARTIST_NAME, duration=0, goods_duration=30)


def _post():
    return TimetableRowDraft(artist_name=POST_GOODS_ARTIST_NAME, duration=0)


def _n(name, marked=False):
    return TimetableRowDraft(artist_name=name, place="A", is_delete_marked=marked)


def _names(rows):
    return [r.artist_name for r in rows]


print("=" * 66)
print("(A) _drop_marked_rows")
print("=" * 66)

rows = [_pre(), _n("A"), _n("B", True), _n("C"), _n("D", True), _post()]
out = _drop_marked_rows(rows)
_chk(_names(out) == [PRE_GOODS_ARTIST_NAME, "A", "C", POST_GOODS_ARTIST_NAME],
     "チェックした通常行だけ消える / 残りの順序保持", "-> %s" % _names(out))

# 特殊行にチェックが付いていても残す
rows = [_pre(), _n("A", True), _post()]
rows[0].is_delete_marked = True
rows[2].is_delete_marked = True
out = _drop_marked_rows(rows)
_chk(_names(out) == [PRE_GOODS_ARTIST_NAME, POST_GOODS_ARTIST_NAME],
     "特殊行はチェックされていても必ず残る", "-> %s" % _names(out))

# 空チェック
rows = [_pre(), _n("A"), _n("B"), _post()]
out = _drop_marked_rows(rows)
_chk(_names(out) == _names(rows), "チェックが1つも無ければ無変化")

# 全通常行チェック
rows = [_pre(), _n("A", True), _n("B", True), _post()]
out = _drop_marked_rows(rows)
_chk(_names(out) == [PRE_GOODS_ARTIST_NAME, POST_GOODS_ARTIST_NAME],
     "通常行を全部チェックしても特殊行は残る")

# 純関数性
rows = [_n("A", True), _n("B")]
before = _names(rows)
out = _drop_marked_rows(rows)
_chk(_names(rows) == before and out is not rows, "引数リストを破壊せず新しい list を返す")
_chk(_drop_marked_rows([]) == [] and _drop_marked_rows(None) == [], "空 / None 入力で例外を出さない")

print()
print("=" * 66)
print("(B) _normalize_edited_rows が特殊行のチェックを倒す")
print("=" * 66)
st.session_state["tt_open_time"] = "10:00"
st.session_state["tt_start_time"] = "10:30"
rows = [_pre(), _n("A", True), _post()]
rows[0].is_delete_marked = True
rows[2].is_delete_marked = True
_normalize_edited_rows(rows)
_chk([r.is_delete_marked for r in rows] == [False, True, False],
     "特殊行のみ False に倒れ、通常行のチェックは維持",
     "-> %s" % [r.is_delete_marked for r in rows])

print()
print("=" * 66)
print("(C) ★先取り確定を DELETE 列が通る (罠33)")
print("=" * 66)
draft = [_n("A"), _n("B"), _n("C")]
# data_editor の内部 state を模す: 行1 の DELETE にチェック
pending = {"edited_rows": {1: {"DELETE": True}}}
seeded = _apply_editor_state_to_df(draft_rows_to_df(draft), pending)
_chk("DELETE" in seeded.columns, "先取り確定に渡す df が DELETE 列を持つ")
_chk(seeded["DELETE"].tolist() == [False, True, False],
     "edited_rows の DELETE が df に適用される", "-> %s" % seeded["DELETE"].tolist())
seeded_rows = df_to_draft_rows(seeded)
_normalize_edited_rows(seeded_rows)
_chk([r.is_delete_marked for r in seeded_rows] == [False, True, False],
     "先取り確定 → draft_rows までチェックが生き残る")
# 冪等性: 2回適用しても同じ (後段 L515 の書き戻しと二重適用しても drift しない)
again = df_to_draft_rows(_apply_editor_state_to_df(draft_rows_to_df(seeded_rows), pending))
_normalize_edited_rows(again)
_chk([r.is_delete_marked for r in again] == [False, True, False], "二重適用しても drift しない (冪等)")
# 実際に消える所まで通す
_chk(_names(_drop_marked_rows(seeded_rows)) == ["A", "C"],
     "先取り確定 → 一括削除まで一気通貫", "-> %s" % _names(_drop_marked_rows(seeded_rows)))

print()
print("=" * 66)
print("(D) 非永続の証明 (DB へ書かれない = スキーマ変更ゼロ)")
print("=" * 66)
d = _n("A", marked=True)
orm_row = timetable_repo._draft_to_row(project_id=1, sort_order=0, d=d)
_chk(not hasattr(orm_row, "is_delete_marked") or getattr(orm_row, "is_delete_marked", None) is None,
     "TimetableRow(ORM) に is_delete_marked は載らない")
_chk("DELETE" not in {c.name for c in orm_row.__table__.columns}
     and "is_delete_marked" not in {c.name for c in orm_row.__table__.columns},
     "timetable_rows テーブルに対応カラムが存在しない",
     "-> columns=%d" % len(orm_row.__table__.columns))
back = timetable_repo._row_to_draft(orm_row)
_chk(back.is_delete_marked is False, "保存→再読込の往復でチェックは必ず False に戻る")

print()
print("=" * 66)
print("(E) 未保存判定がチェックに反応しない")
print("=" * 66)
a = [_n("A"), _n("B")]
b = [_n("A", True), _n("B", True)]
_chk(session_manager._rows_to_comparable(a) == session_manager._rows_to_comparable(b),
     "チェックの有無で比較タプルが変わらない (誤「未保存」警告なし)")
c = _drop_marked_rows(b)
_chk(session_manager._rows_to_comparable(a) != session_manager._rows_to_comparable(c),
     "実際に行を消したら比較タプルが変わる (差分は検知できる)")

print()
print("BULK_DELETE_ALL_PASS" if fails == 0 else "BULK_DELETE_FAILED (%d)" % fails)
sys.exit(0 if fails == 0 else 1)
