# -*- coding: utf-8 -*-
"""段階③ コミット3: 「追加する」の AppTest 機械確認 (read-only・§12.4 方式)。

確認項目:
  (1) 予定リストの並び順のまま draft_rows へ append される
  (2) 挿入位置: 終演後物販行があればその直前 / 無ければ末尾。開演前物販は先頭のまま
  (3) 既存行の相対順序が保持される
  (4) tt_pending_add がクリアされる
  (5) tt_editor_key が bump される (data_editor の強制 reset)
  (6) ★DB 保存が走っていない: saved_rows_snapshot が不変かつ未保存判定が True
     (save_active_project → mark_saved が走っていれば snapshot は更新されてしまう)

安全設計: read-only secrets 注入 + current_user 検査。書き込みは物理的にも不可。
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

try:
    import tomllib as _toml
except ModuleNotFoundError:
    import tomli as _toml

READONLY_SECRETS_PATH = REPO_ROOT / ".streamlit" / "secrets.readonly.toml"
EXPECTED_USER = "event_app_readonly"

if not READONLY_SECRETS_PATH.exists():
    print("SKIP: read-only secrets 未配置"); sys.exit(0)
with open(READONLY_SECRETS_PATH, "rb") as f:
    creds = _toml.load(f).get("supabase") or {}
if "DB_URL" not in creds:
    print("SKIP: DB_URL なし"); sys.exit(0)

import streamlit.runtime.secrets as st_secrets  # noqa: E402
st_secrets.secrets_singleton._secrets = {"supabase": dict(creds)}

from sqlalchemy import create_engine, text  # noqa: E402
_eng = create_engine(creds["DB_URL"], connect_args={"sslmode": "require"})
with _eng.connect() as conn:
    user = conn.execute(text("SELECT current_user")).scalar()
_eng.dispose()
if user != EXPECTED_USER:
    print("ABORT: 接続ユーザーが %r" % user); sys.exit(3)
print("[safety] current_user = %s (read-only OK)" % user)

from streamlit.testing.v1 import AppTest  # noqa: E402
from models.timetable import PRE_GOODS_ARTIST_NAME, POST_GOODS_ARTIST_NAME  # noqa: E402

SELECTOR_KEY = "ws_project_selector_label"
fails = 0


def _sget(at, key, default=None):
    try:
        return at.session_state[key]
    except (KeyError, AttributeError):
        return default


def _names(rows):
    return [r.artist_name for r in (rows or [])]


at = AppTest.from_file(str(REPO_ROOT / "app.py"), default_timeout=180).run()
assert not at.exception, "初期描画で例外: %s" % at.exception

options = [o for o in at.selectbox(key=SELECTOR_KEY).options
           if o not in ("(選択してください)", "➕ 新規プロジェクト作成")]
if not options:
    print("SKIP: プロジェクトが無い"); sys.exit(0)

# 引数でラベル部分一致を指定できる (特殊行を持つ project を狙って検証するため)。
# 未指定なら先頭のプロジェクト。
want = sys.argv[1] if len(sys.argv) > 1 else None
if want:
    matched = [o for o in options if want in o]
    if not matched:
        print("SKIP: ラベルに %r を含むプロジェクトが無い" % want); sys.exit(0)
    label = matched[0]
else:
    label = options[0]
at.selectbox(key=SELECTOR_KEY).select(label).run()
assert not at.exception, "選択で例外: %s" % at.exception
print("[setup] project = %s" % label)

rows_before = _names(_sget(at, "draft_rows"))
snap_before = _sget(at, "saved_rows_snapshot")
key_before = _sget(at, "tt_editor_key")
has_post = POST_GOODS_ARTIST_NAME in rows_before
has_pre = PRE_GOODS_ARTIST_NAME in rows_before
print("[setup] rows=%d  開演前物販=%s  終演後物販=%s  tt_editor_key=%s"
      % (len(rows_before), has_pre, has_post, key_before))

cands = list(at.multiselect(key="tt_add_candidates").options)
if len(cands) < 2:
    print("SKIP: 追加候補が 2 件未満"); sys.exit(0)
pick = cands[:2]

for n in pick:
    at.multiselect(key="tt_add_candidates").select(n)
at.run()
at.button(key="btn_tt_pending_push").click().run()
assert not at.exception, "予定に追加で例外: %s" % at.exception

pending = list(_sget(at, "tt_pending_add") or [])
print("[setup] pending = %r" % pending)

# 逆順に並べ替えたケースも見たいので session を直接いじる(DnD は AppTest 非操作=罠34)
at.session_state["tt_pending_add"] = list(reversed(pending))
at.run()
pending = list(_sget(at, "tt_pending_add") or [])
print("[setup] 並べ替え後 pending = %r" % pending)

at.button(key="btn_tt_pending_apply").click().run()
assert not at.exception, "「追加する」で例外: %s" % at.exception

rows_after = _names(_sget(at, "draft_rows"))

# (1) 並び順のまま append
if has_post:
    p = rows_after.index(POST_GOODS_ARTIST_NAME)
    added = rows_after[p - len(pending):p]
else:
    added = rows_after[-len(pending):]
ok = added == pending
print(("  PASS  " if ok else "  FAIL  ") + "(1) 予定リストの並び順のまま append -> %r" % added)
fails += 0 if ok else 1

# (2) 挿入位置 / 特殊行の位置
ok = (not has_post) or (rows_after[-1] == POST_GOODS_ARTIST_NAME)
print(("  PASS  " if ok else "  FAIL  ") + "(2a) 終演後物販は末尾のまま (存在時)")
fails += 0 if ok else 1
ok = (not has_pre) or (rows_after[0] == PRE_GOODS_ARTIST_NAME)
print(("  PASS  " if ok else "  FAIL  ") + "(2b) 開演前物販は先頭のまま (存在時)")
fails += 0 if ok else 1

# (3) 既存行の相対順序が保持される
ok = [n for n in rows_after if n not in pending or n in rows_before] == rows_before
print(("  PASS  " if ok else "  FAIL  ") + "(3) 既存行の相対順序が保持される (%d -> %d 行)"
      % (len(rows_before), len(rows_after)))
fails += 0 if ok else 1
if not ok:
    print("       before=%r" % rows_before)
    print("       after =%r" % rows_after)

# (4) pending クリア
pend_after = list(_sget(at, "tt_pending_add") or [])
ok = pend_after == []
print(("  PASS  " if ok else "  FAIL  ") + "(4) tt_pending_add がクリアされる -> %r" % pend_after)
fails += 0 if ok else 1

# (5) editor key bump
key_after = _sget(at, "tt_editor_key")
ok = key_after is not None and key_before is not None and key_after > key_before
print(("  PASS  " if ok else "  FAIL  ") + "(5) tt_editor_key が bump (%s -> %s)" % (key_before, key_after))
fails += 0 if ok else 1

# (6) ★DB 保存が走っていない
snap_after = _sget(at, "saved_rows_snapshot")
ok = snap_after == snap_before
print(("  PASS  " if ok else "  FAIL  ") + "(6a) saved_rows_snapshot が不変 (= mark_saved 未実行 = 未保存)")
fails += 0 if ok else 1
ok = bool(_sget(at, "tt_unsaved_changes"))
print(("  PASS  " if ok else "  FAIL  ") + "(6b) tt_unsaved_changes = True (mark_dirty 済み)")
fails += 0 if ok else 1
ok = (snap_after is not None) and (len(snap_after) == len(rows_before))
print(("  PASS  " if ok else "  FAIL  ") + "(6c) snapshot 行数は追加前のまま (%s)" % (len(snap_after) if snap_after else None))
fails += 0 if ok else 1

print()
print("PENDING_APPLY_ALL_PASS" if fails == 0 else "PENDING_APPLY_FAILED (%d)" % fails)
sys.exit(0 if fails == 0 else 1)
