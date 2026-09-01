# -*- coding: utf-8 -*-
"""段階③ コミット2: 追加予定リスト UI の AppTest 機械確認 (read-only・§12.4 方式)。

確認項目:
  (1) 追加候補 multiselect (key="tt_add_candidates") が描画される
  (2) 候補を選び「予定に追加」を押すと tt_pending_add に溜まる (重複しない)
  (3) 押下後に候補 multiselect の選択がクリアされる
  (4) この操作で draft_rows は一切変化しない (= まだ TT には追加されない・DB 保存もない)
  (5) 例外が出ない

制約(罠34): sort_items(streamlit_sortables)は AppTest で非描画・非操作のため、
ドラッグ&ドロップと × ボタンは実機テストで確認する。

安全設計: tests/conftest.py と同じく read-only secrets を注入し、接続ユーザーが
event_app_readonly でなければ即中断する(書き込み可能ユーザーでは絶対に走らせない)。
"""
from __future__ import annotations

import os
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
    print("SKIP: read-only secrets 未配置:", READONLY_SECRETS_PATH)
    sys.exit(0)

with open(READONLY_SECRETS_PATH, "rb") as f:
    creds = _toml.load(f).get("supabase") or {}
if "DB_URL" not in creds:
    print("SKIP: DB_URL なし")
    sys.exit(0)

import streamlit.runtime.secrets as st_secrets  # noqa: E402

st_secrets.secrets_singleton._secrets = {"supabase": dict(creds)}

# --- 安全弁: read-only ユーザー以外では即中断 ---
from sqlalchemy import create_engine, text  # noqa: E402

_eng = create_engine(creds["DB_URL"], connect_args={"sslmode": "require"})
with _eng.connect() as conn:
    user = conn.execute(text("SELECT current_user")).scalar()
_eng.dispose()
if user != EXPECTED_USER:
    print("ABORT: 接続ユーザーが %r。%r 以外では実行しません。" % (user, EXPECTED_USER))
    sys.exit(3)
print("[safety] current_user = %s (read-only OK)" % user)

from streamlit.testing.v1 import AppTest  # noqa: E402

SELECTOR_KEY = "ws_project_selector_label"
fails = 0


def _sget(at, key, default=None):
    """AppTest.session_state は dict の .get() を持たないため安全参照ヘルパを使う。"""
    try:
        return at.session_state[key]
    except (KeyError, AttributeError):
        return default


def _names(rows):
    return [r.artist_name for r in (rows or [])]


at = AppTest.from_file(str(REPO_ROOT / "app.py"), default_timeout=120).run()
assert not at.exception, "初期描画で例外: %s" % at.exception

options = [o for o in at.selectbox(key=SELECTOR_KEY).options
           if o not in ("(選択してください)", "➕ 新規プロジェクト作成")]
if not options:
    print("SKIP: 選択できるプロジェクトが無い")
    sys.exit(0)

label = options[0]
at.selectbox(key=SELECTOR_KEY).select(label).run()
assert not at.exception, "プロジェクト選択で例外: %s" % at.exception
print("[setup] project = %s" % label)

# (1) multiselect の存在
ms = at.multiselect(key="tt_add_candidates")
ok = bool(ms)
print(("  PASS  " if ok else "  FAIL  ") + "(1) 追加候補 multiselect が描画される")
fails += 0 if ok else 1
if not ok:
    print("PENDING_ADD_UI_FAILED"); sys.exit(1)

cands = list(ms.options)
print("       候補数 = %d" % len(cands))
if len(cands) < 1:
    print("SKIP: 追加候補が 0 件(全アーティストが既に TT にいる)")
    sys.exit(0)

rows_before = _names(_sget(at, "draft_rows"))
pick = cands[:2] if len(cands) >= 2 else cands[:1]

# (2)(3)(4) 候補を選択 → 「予定に追加」
for n in pick:
    at.multiselect(key="tt_add_candidates").select(n)
at.run()
assert not at.exception, "候補選択で例外: %s" % at.exception

at.button(key="btn_tt_pending_push").click().run()
assert not at.exception, "「予定に追加」で例外: %s" % at.exception

pending = list(_sget(at, "tt_pending_add") or [])
ok = pending == pick
print(("  PASS  " if ok else "  FAIL  ") + "(2) tt_pending_add に選択順で溜まる -> %r" % pending)
fails += 0 if ok else 1

sel_after = list(at.multiselect(key="tt_add_candidates").value or [])
ok = sel_after == []
print(("  PASS  " if ok else "  FAIL  ") + "(3) 押下後に候補の選択がクリアされる -> %r" % sel_after)
fails += 0 if ok else 1

rows_after = _names(_sget(at, "draft_rows"))
ok = rows_after == rows_before
print(("  PASS  " if ok else "  FAIL  ") + "(4) draft_rows は不変 (TT にはまだ追加されない)")
fails += 0 if ok else 1
if not ok:
    print("       before=%r" % rows_before)
    print("       after =%r" % rows_after)

# (2b) 同じ候補をもう一度押しても重複しない
for n in pick:
    at.multiselect(key="tt_add_candidates").select(n)
at.run()
at.button(key="btn_tt_pending_push").click().run()
pending2 = list(_sget(at, "tt_pending_add") or [])
ok = pending2 == pick
print(("  PASS  " if ok else "  FAIL  ") + "(2b) 二重押下でも重複しない -> %r" % pending2)
fails += 0 if ok else 1

# (5) 例外なし
ok = not at.exception
print(("  PASS  " if ok else "  FAIL  ") + "(5) 一連の操作で例外なし")
fails += 0 if ok else 1

print()
print("PENDING_ADD_UI_ALL_PASS" if fails == 0 else "PENDING_ADD_UI_FAILED (%d)" % fails)
sys.exit(0 if fails == 0 else 1)
