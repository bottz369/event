# -*- coding: utf-8 -*-
"""段階② 初期採番の実データ確認 (AppTest + read-only DB)。

確認項目:
  (1) プロジェクトを開くと draft_rows の grid_no が保存済み order から復元される
  (2) ★build_grid_order_from_rows(draft_rows) が保存済み order を再現する
      (= 番号列を足しても初期表示のグリッド並びが変わらない)
      ただし TT にいない名前は落ちる(仕様変更・合意済み)ので、その差分を明示する
  (3) ★開いただけで has_unsaved_changes() が True にならない(誤「未保存」警告なし)
  (4) GRID_NO のチェック注入が draft_rows まで届く(罠33)

安全設計: read-only secrets 注入 + current_user 検査。SELECT のみ。
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

P = REPO_ROOT / ".streamlit" / "secrets.readonly.toml"
if not P.exists():
    print("SKIP: read-only secrets 未配置"); sys.exit(0)
creds = _toml.load(open(P, "rb"))["supabase"]
import streamlit.runtime.secrets as st_secrets
st_secrets.secrets_singleton._secrets = {"supabase": dict(creds)}

from sqlalchemy import create_engine, text
_e = create_engine(creds["DB_URL"], connect_args={"sslmode": "require"})
with _e.connect() as c:
    u = c.execute(text("SELECT current_user")).scalar()
_e.dispose()
assert u == "event_app_readonly", "read-only 以外では実行しない: %r" % u
print("[safety] current_user =", u)

from streamlit.testing.v1 import AppTest  # noqa: E402
from models.timetable import build_grid_order_from_rows  # noqa: E402

SELECTOR_KEY = "ws_project_selector_label"
fails = 0


def _chk(ok, label, extra=""):
    global fails
    print(("  PASS  " if ok else "  FAIL  ") + label + (("  " + extra) if extra else ""))
    if not ok:
        fails += 1


def _sget(at, k, default=None):
    try:
        return at.session_state[k]
    except (KeyError, AttributeError):
        return default


at = AppTest.from_file(str(REPO_ROOT / "app.py"), default_timeout=180).run()
assert not at.exception, "初期描画で例外: %s" % at.exception

options = [o for o in at.selectbox(key=SELECTOR_KEY).options
           if o not in ("(選択してください)", "➕ 新規プロジェクト作成")]
if not options:
    print("SKIP: プロジェクトが無い"); sys.exit(0)

label = options[0]
at.selectbox(key=SELECTOR_KEY).select(label).run()
assert not at.exception, "選択で例外: %s" % at.exception
print("[setup] project = %s" % label)

rows = _sget(at, "draft_rows") or []
order = list(_sget(at, "grid_order") or [])
print("[setup] rows=%d  保存済み order=%d 件" % (len(rows), len(order)))
if not order:
    print("SKIP: このプロジェクトには保存済み grid_order が無い")
    sys.exit(0)

# (1) 採番されているか
numbered = [(r.artist_name, r.grid_no) for r in rows if r.grid_no is not None]
_chk(len(numbered) > 0, "grid_no が保存済み order から復元されている",
     "-> %d 行に採番  例: %s" % (len(numbered), numbered[:3]))

# (2) 保存済み order を再現するか
rebuilt = build_grid_order_from_rows(rows)
tt_names = {(r.artist_name or "").strip() for r in rows}
order_clean = [(n or "").strip() for n in order if (n or "").strip()]
expected = [n for n in dict.fromkeys(order_clean) if n in tt_names]
ghosts = [n for n in dict.fromkeys(order_clean) if n not in tt_names]
_chk(rebuilt[:len(expected)] == expected,
     "保存済み order の並びを再現する(TT にいる分)",
     "-> 先頭5=%s" % rebuilt[:5])
extra_tail = rebuilt[len(expected):]
print("       TT にいない名前(保存時に order から落ちる) = %d 件 %s"
      % (len(ghosts), ghosts[:5]))
print("       order に無い TT 行(末尾に付く)             = %d 件 %s"
      % (len(extra_tail), extra_tail[:5]))

# (3) 誤「未保存」警告が出ないこと
from services import session_manager  # noqa: E402
import streamlit as _st  # noqa: E402
_st.session_state.clear()
for k in ("draft_project", "draft_rows", "saved_project_snapshot", "saved_rows_snapshot"):
    v = _sget(at, k)
    if v is not None:
        _st.session_state[k] = v
unsaved = session_manager.has_unsaved_changes()
_chk(unsaved is False, "プロジェクトを開いただけでは未保存にならない",
     "-> has_unsaved_changes()=%s" % unsaved)

# (4) GRID_NO 注入が draft_rows まで届く(罠33)
target = next((i for i, r in enumerate(rows) if not r.is_special_row), None)
if target is None:
    print("SKIP: 通常行が無い")
else:
    k = _sget(at, "tt_editor_key")
    at.session_state[f"tt_editor_{k}"] = {
        "edited_rows": {target: {"GRID_NO": 99}}, "added_rows": [], "deleted_rows": []}
    at.run()
    _chk(not at.exception, "GRID_NO 注入で例外なし")
    dr = _sget(at, "draft_rows") or []
    _chk(dr[target].grid_no == 99, "GRID_NO の編集が draft_rows に届く(先取り確定を通る)",
         "-> %s" % (dr[target].grid_no if dr else None))
    _chk(build_grid_order_from_rows(dr)[0] != dr[target].artist_name
         or len(dr) == 1,
         "99 を振った行が先頭に来ない(= 大きい番号は後ろ)")

print()
print("GRID_NO_SEEDING_ALL_PASS" if fails == 0 else "GRID_NO_SEEDING_FAILED (%d)" % fails)
sys.exit(0 if fails == 0 else 1)
