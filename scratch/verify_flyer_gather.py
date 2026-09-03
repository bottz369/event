# -*- coding: utf-8 -*-
"""build_flyer_kwargs_for_project が view(_generate_preview)と同じ引数を組むかの機械検証。

実アプリを AppTest で動かし、views.flyer が create_flyer_image_shadow へ渡す
kwargs を捕捉して、DB 駆動 gather の出力と全キー比較する。

★DB 書込防止: project_service.save_active_project をモックして True を返すだけにする
  (フライヤーの生成ボタンは保存 → プレビュー生成の順に呼ぶため)。
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

from sqlalchemy import create_engine, text  # noqa: E402
_e = create_engine(creds["DB_URL"], connect_args={"sslmode": "require"})
with _e.connect() as c:
    u = c.execute(text("SELECT current_user")).scalar()
_e.dispose()
assert u == "event_app_readonly", "read-only 以外では実行しない: %r" % u
print("[safety] current_user =", u)

from PIL import Image  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402

import views.flyer as vf  # noqa: E402
from services import generation_service as gs  # noqa: E402

SELECTOR_KEY = "ws_project_selector_label"
fails = 0


def _chk(ok, label, extra=""):
    global fails
    print(("  PASS  " if ok else "  FAIL  ") + label + (("  " + extra) if extra else ""))
    if not ok:
        fails += 1


# --- create_flyer_image_shadow を捕捉に差し替え(生成はしない) ---
captured = []
_dummy = Image.new("RGBA", (8, 8), (0, 0, 0, 0))


def _capture(**kwargs):
    captured.append(kwargs)
    return (_dummy, {})


vf.create_flyer_image_shadow = _capture
# ★DB 書込防止: 保存は必ずモック(実際には何も書かない)
vf.project_service.save_active_project = lambda: True


def _sget(at, k, default=None):
    try:
        return at.session_state[k]
    except (KeyError, AttributeError):
        return default


at = AppTest.from_file(str(REPO / "app.py"), default_timeout=300).run()
assert not at.exception, "初期描画で例外: %s" % at.exception
options = [o for o in at.selectbox(key=SELECTOR_KEY).options
           if o not in ("(選択してください)", "➕ 新規プロジェクト作成")]
if not options:
    print("SKIP: プロジェクトが無い"); sys.exit(0)

checked = 0
for label in options[:3]:
    captured.clear()
    at.selectbox(key=SELECTOR_KEY).select(label).run()
    if at.exception:
        print("  SKIP  %s (描画で例外)" % label[:36]); continue
    pid = _sget(at, "tt_current_proj_id")

    # main_source は中間画像。存在しないと view が生成をスキップするのでダミーを置く
    at.session_state["last_generated_grid_image"] = Image.new("RGBA", (40, 30), (1, 2, 3, 255))
    at.session_state["last_generated_tt_image"] = Image.new("RGBA", (30, 40), (4, 5, 6, 255))

    btn = next((b for b in at.button if "プレビューを生成" in str(b.label)), None)
    if btn is None:
        print("  SKIP  %s (生成ボタンが見つからない)" % label[:36]); continue
    btn.click().run()
    if at.exception:
        print("  SKIP  %s (生成で例外: %s)" % (label[:36], at.exception)); continue
    if len(captured) < 2:
        print("  SKIP  %s (捕捉 %d 件)" % (label[:36], len(captured))); continue

    for idx, variant in ((0, "grid"), (1, "tt")):
        view_kw = dict(captured[idx])
        view_kw.pop("main_source", None)  # 中間画像は比較対象外(DB に無い)
        mine = gs.build_flyer_kwargs_for_project(pid, variant=variant)
        assert mine is not None
        mine_kw = dict(mine)

        # styles は別途フルキー比較する
        v_styles = dict(view_kw.pop("styles"))
        m_styles = dict(mine_kw.pop("styles"))
        # view の styles は session_state 由来なので UI 専用 / transient キーが混ざる。
        # 比較対象は gather が組む(= registry persist=True + content_*)キー集合。
        common = set(m_styles)
        missing = [k for k in common if k not in v_styles]
        diff_style = {k: (v_styles.get(k), m_styles.get(k)) for k in common
                      if k in v_styles and v_styles[k] != m_styles[k]}

        ok_scalar = view_kw == mine_kw
        ok_style = (not missing) and (not diff_style)
        _chk(ok_scalar and ok_style,
             "id=%-4s variant=%-4s styles %d キー一致 / スカラー引数 %d 件一致"
             % (pid, variant, len(common), len(mine_kw)))
        if not ok_scalar:
            for k in set(view_kw) | set(mine_kw):
                if view_kw.get(k) != mine_kw.get(k):
                    print("        [%s] view=%r  gather=%r" % (k, view_kw.get(k), mine_kw.get(k)))
        if missing:
            print("        view に無い styles キー: %r" % missing[:8])
        for k, (a, b) in list(diff_style.items())[:8]:
            print("        styles[%s] view=%r  gather=%r" % (k, a, b))
    checked += 1

_chk(checked > 0, "実データで最低 1 件は突合できた", "-> %d 件" % checked)
print()
print("FLYER_GATHER_ALL_PASS" if fails == 0 else "FLYER_GATHER_FAILED (%d)" % fails)
sys.exit(0 if fails == 0 else 1)
