# -*- coding: utf-8 -*-
"""build_tt_gen_list_from_rows が view の tt_gen_list と一致することの機械検証。

(A) AppTest で実アプリを動かし、st.session_state.tt_gen_list と純関数の出力を突合(実データ)
(B) 合成データで境界条件(OPEN/START 除外・IS_HIDDEN 除外・is_grid_hidden は無関係・列順)

read-only(SELECT のみ)。
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

try:
    import tomllib as _toml
except ModuleNotFoundError:
    import tomli as _toml

P = REPO / ".streamlit" / "secrets.readonly.toml"
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

from models.timetable import PRE_GOODS_ARTIST_NAME, POST_GOODS_ARTIST_NAME, TimetableRowDraft  # noqa: E402
from services.timetable_service import build_tt_gen_list_from_rows  # noqa: E402

fails = 0


def _chk(ok, label, extra=""):
    global fails
    print(("  PASS  " if ok else "  FAIL  ") + label + (("  " + extra) if extra else ""))
    if not ok:
        fails += 1


# ---------------- (A) 実アプリの tt_gen_list と突合 ----------------
print()
print("=" * 70)
print("(A) ★AppTest: 実アプリの st.session_state.tt_gen_list と一致するか")
print("=" * 70)

from streamlit.testing.v1 import AppTest  # noqa: E402
from repositories import project_repo  # noqa: E402
from database import SessionLocal  # noqa: E402

SELECTOR_KEY = "ws_project_selector_label"


def _sget(at, k, default=None):
    try:
        return at.session_state[k]
    except (KeyError, AttributeError):
        return default


at = AppTest.from_file(str(REPO / "app.py"), default_timeout=240).run()
assert not at.exception, "初期描画で例外: %s" % at.exception
options = [o for o in at.selectbox(key=SELECTOR_KEY).options
           if o not in ("(選択してください)", "➕ 新規プロジェクト作成")]
if not options:
    print("SKIP: プロジェクトが無い"); sys.exit(0)

checked = 0
for label in options[:4]:
    at.selectbox(key=SELECTOR_KEY).select(label).run()
    if at.exception:
        print("  SKIP  %s (描画で例外)" % label[:40]); continue
    view_list = _sget(at, "tt_gen_list")
    rows = _sget(at, "draft_rows") or []
    pid = _sget(at, "tt_current_proj_id")
    if view_list is None or not rows:
        print("  SKIP  %s (tt_gen_list なし)" % label[:40]); continue

    db = SessionLocal()
    try:
        draft = project_repo.to_draft(project_repo.get_project(db, pid))
    finally:
        db.close()

    mine = build_tt_gen_list_from_rows(rows, draft.open_time, draft.start_time)
    ok = [list(x) for x in view_list] == [list(x) for x in mine]
    _chk(ok, "id=%-4s %-30.30s view=%d行 / 純関数=%d行"
         % (pid, label, len(view_list), len(mine)))
    if not ok:
        for i, (a, b) in enumerate(zip(view_list, mine)):
            if list(a) != list(b):
                print("        行%d view=%r" % (i, a)); print("             mine=%r" % (b,)); break
    checked += 1

_chk(checked > 0, "実データで最低 1 件は突合できた", "-> %d 件" % checked)

# ---------------- (B) 境界条件 ----------------
print()
print("=" * 70)
print("(B) 境界条件(合成データ)")
print("=" * 70)


def _n(name, hidden=False, grid_hidden=False):
    return TimetableRowDraft(artist_name=name, duration=30, adjustment=0, place="A",
                             goods_start_time="12:00", goods_duration=60,
                             is_hidden=hidden, is_grid_hidden=grid_hidden)


base = [_n("A"), _n("B"), _n("C")]
out = build_tt_gen_list_from_rows(base, "10:00", "10:30")
_chk([r[1] for r in out] == ["A", "B", "C"], "通常3行がそのまま出る", "-> %s" % [r[1] for r in out])
_chk(all(len(r) == 4 for r in out), "各行は 4 要素 [TIME_DISPLAY, ARTIST, GOODS_DISPLAY, PLACE]")
_chk(all(r[1] != "OPEN / START" for r in out), "★OPEN / START 行は除外される")
_chk(out[0][0] == "10:30 - 11:00", "TIME_DISPLAY が start_time 起点で計算される", "-> %r" % out[0][0])

rows = [_n("A"), _n("B", hidden=True), _n("C")]
out = build_tt_gen_list_from_rows(rows, "10:00", "10:30")
_chk([r[1] for r in out] == ["A", "C"], "★IS_HIDDEN(タイムテーブル非表示)行は除外", "-> %s" % [r[1] for r in out])

rows = [_n("A"), _n("B", grid_hidden=True), _n("C")]
out = build_tt_gen_list_from_rows(rows, "10:00", "10:30")
_chk([r[1] for r in out] == ["A", "B", "C"],
     "★is_grid_hidden(アー写グリッド非表示)では除外しない(役割が別)", "-> %s" % [r[1] for r in out])

rows = [_n("A", hidden=True), _n("B", hidden=True, grid_hidden=True), _n("C")]
out = build_tt_gen_list_from_rows(rows, "10:00", "10:30")
_chk([r[1] for r in out] == ["C"], "両方立っていても除外判定は IS_HIDDEN のみ")

# 非表示行が index をずらさないこと(先頭・中間・末尾)
for pos, label in ((0, "先頭"), (1, "中間"), (2, "末尾")):
    rows = [_n("A"), _n("B"), _n("C")]
    rows[pos].is_hidden = True
    out = build_tt_gen_list_from_rows(rows, "10:00", "10:30")
    expect = [n for i, n in enumerate(["A", "B", "C"]) if i != pos]
    _chk([r[1] for r in out] == expect, "非表示が%sでも他行がズレない" % label, "-> %s" % [r[1] for r in out])

# 特殊行
pre = TimetableRowDraft(artist_name=PRE_GOODS_ARTIST_NAME, duration=0, goods_start_time="10:00", goods_duration=30)
post = TimetableRowDraft(artist_name=POST_GOODS_ARTIST_NAME, duration=0, goods_start_time="20:00", goods_duration=60)
out = build_tt_gen_list_from_rows([pre, _n("A"), post], "10:00", "10:30")
_chk([r[1] for r in out] == [PRE_GOODS_ARTIST_NAME, "A", POST_GOODS_ARTIST_NAME],
     "特殊行は TT 画像には出る(除外しない)", "-> %s" % [r[1] for r in out])

out = build_tt_gen_list_from_rows([], "10:00", "10:30")
_chk(out == [], "空 rows -> []")
rows = [_n("A", hidden=True)]
_chk(build_tt_gen_list_from_rows(rows, "10:00", "10:30") == [], "全行非表示 -> []")

print()
print("TT_GEN_LIST_ALL_PASS" if fails == 0 else "TT_GEN_LIST_FAILED (%d)" % fails)
sys.exit(0 if fails == 0 else 1)
