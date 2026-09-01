# -*- coding: utf-8 -*-
"""段階③ コミット1: _append_artist_rows の機械検証 (DB 非接続・§12.4 方式)。

検証内容:
  (A) 旧「＋」インライン処理を1件ずつ N 回適用した結果 == _append_artist_rows(rows, names)
  (B) insert 位置 (終演後物販の直前 / 無ければ末尾)
  (C) 既存出演順の保持 (前後の既存行がそのまま残る)
  (D) 純関数性 (引数リストを破壊しない・新しい list を返す)
  (E) 空 names / None は無変化

本番 DB へは一切接続しない。st.secrets シングルトンにダミー値を注入して
database.py の import 時 config 読み出しを本番 secrets.toml から切り離す
(create_engine / create_client は遅延接続のため実接続は発生しない)。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# --- 本番 secrets を絶対に読ませない: ダミー注入 (conftest と同じ流儀) ---
import streamlit.runtime.secrets as st_secrets

st_secrets.secrets_singleton._secrets = {
    "supabase": {
        "DB_URL": "postgresql://dummy:dummy@127.0.0.1:5432/dummy",
        "URL": "https://dummy.supabase.co",
        "KEY": "dummy-key",
    }
}

from models.timetable import (  # noqa: E402
    POST_GOODS_ARTIST_NAME,
    PRE_GOODS_ARTIST_NAME,
    TimetableRowDraft,
)
from views.timetable import _append_artist_rows  # noqa: E402


def _legacy_add_one(draft_rows, new_artist):
    """旧 views/timetable.py L419-430 のインライン処理の逐語コピー (mutating)。"""
    new_row = TimetableRowDraft(artist_name=new_artist, place="A")
    post_idx = next((i for i, r in enumerate(draft_rows) if r.is_post_goods_row), None)
    if post_idx is None:
        draft_rows.append(new_row)
    else:
        draft_rows.insert(post_idx, new_row)
    return draft_rows


def _legacy_add_many(draft_rows, names):
    """旧処理を1件ずつ順に適用 (= ユーザーが「＋」を N 回押した場合)。"""
    rows = list(draft_rows)
    for n in names:
        _legacy_add_one(rows, n)
    return rows


def _cmp(rows):
    """比較用タプル (session_manager._rows_to_comparable と同じ粒度)。"""
    return tuple(
        (
            r.artist_name, r.duration, r.adjustment, r.is_post_goods, r.is_hidden,
            r.goods_start_time, r.goods_duration, r.place,
            r.add_goods_start_time, r.add_goods_duration, r.add_goods_place,
        )
        for r in rows
    )


def _pre():
    return TimetableRowDraft(artist_name=PRE_GOODS_ARTIST_NAME, duration=0, goods_duration=30)


def _post():
    return TimetableRowDraft(artist_name=POST_GOODS_ARTIST_NAME, duration=0)


def _normal(name):
    return TimetableRowDraft(artist_name=name, place="A")


CASES = [
    ("空リスト / 追加1件",            [],                                    ["X"]),
    ("空リスト / 追加3件",            [],                                    ["X", "Y", "Z"]),
    ("通常行のみ / 追加1件",          [_normal("A"), _normal("B")],          ["X"]),
    ("通常行のみ / 追加3件",          [_normal("A"), _normal("B")],          ["X", "Y", "Z"]),
    ("開演前+通常 / 追加2件",         [_pre(), _normal("A")],                ["X", "Y"]),
    ("通常+終演後 / 追加1件",         [_normal("A"), _post()],               ["X"]),
    ("通常+終演後 / 追加3件",         [_normal("A"), _normal("B"), _post()], ["X", "Y", "Z"]),
    ("開演前+通常+終演後 / 追加2件",  [_pre(), _normal("A"), _post()],       ["X", "Y"]),
    ("開演前のみ / 追加1件",          [_pre()],                              ["X"]),
    ("終演後のみ / 追加2件",          [_post()],                             ["X", "Y"]),
    ("同名の重複追加",                [_normal("A")],                        ["A", "A"]),
]

fails = 0

print("=== (A) 旧1件ずつ N 回 == _append_artist_rows(names) ===")
for label, base, names in CASES:
    legacy = _legacy_add_many(base, names)
    new = _append_artist_rows(base, names)
    ok = _cmp(legacy) == _cmp(new)
    print(("  PASS  " if ok else "  FAIL  ") + label
          + "  -> " + ",".join(r.artist_name for r in new))
    if not ok:
        fails += 1
        print("        legacy=", [r.artist_name for r in legacy])
        print("        new   =", [r.artist_name for r in new])

print("=== (B) insert 位置 ===")
b1 = _append_artist_rows([_pre(), _normal("A"), _post()], ["X", "Y"])
exp1 = [PRE_GOODS_ARTIST_NAME, "A", "X", "Y", POST_GOODS_ARTIST_NAME]
ok = [r.artist_name for r in b1] == exp1
print(("  PASS  " if ok else "  FAIL  ") + "終演後物販の直前に names 順で連続配置")
fails += 0 if ok else 1

b2 = _append_artist_rows([_pre(), _normal("A")], ["X", "Y"])
exp2 = [PRE_GOODS_ARTIST_NAME, "A", "X", "Y"]
ok = [r.artist_name for r in b2] == exp2
print(("  PASS  " if ok else "  FAIL  ") + "終演後物販が無ければ末尾に names 順")
fails += 0 if ok else 1

print("=== (C) 既存出演順の保持 ===")
base = [_pre(), _normal("A"), _normal("B"), _normal("C"), _post()]
got = _append_artist_rows(base, ["X"])
names_got = [r.artist_name for r in got]
ok = (names_got[:4] == [PRE_GOODS_ARTIST_NAME, "A", "B", "C"]
      and names_got[-1] == POST_GOODS_ARTIST_NAME)
print(("  PASS  " if ok else "  FAIL  ") + "既存行の相対順序と特殊行の位置が不変 -> " + ",".join(names_got))
fails += 0 if ok else 1

print("=== (D) 純関数性 ===")
base = [_normal("A"), _post()]
snapshot = _cmp(base)
out = _append_artist_rows(base, ["X"])
ok_len = len(base) == 2 and _cmp(base) == snapshot
ok_id = out is not base
print(("  PASS  " if ok_len else "  FAIL  ") + "引数リストを破壊しない")
print(("  PASS  " if ok_id else "  FAIL  ") + "新しい list を返す")
fails += (0 if ok_len else 1) + (0 if ok_id else 1)

print("=== (E) 空 names / None ===")
base = [_normal("A"), _post()]
for label, names in (("names=[]", []), ("names=None", None)):
    out = _append_artist_rows(base, names)
    ok = _cmp(out) == _cmp(base) and out is not base
    print(("  PASS  " if ok else "  FAIL  ") + label + " -> 無変化 (かつ別 list)")
    fails += 0 if ok else 1
out = _append_artist_rows(None, ["X"])
ok = [r.artist_name for r in out] == ["X"]
print(("  PASS  " if ok else "  FAIL  ") + "draft_rows=None -> 新規1件")
fails += 0 if ok else 1

print()
print("APPEND_ROWS_ALL_PASS" if fails == 0 else "APPEND_ROWS_FAILED (%d)" % fails)
sys.exit(0 if fails == 0 else 1)
