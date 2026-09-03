# -*- coding: utf-8 -*-
"""アプリが作るフライヤー画像と API(render_flyer_png_for_project)の出力が一致するかの検証。

AppTest で実アプリを動かし、中間画像(last_generated_*)に API と同じ生成物を差し込んで
本物の create_flyer_image_shadow を通す → session の flyer_result_* を PNG 化して
API の出力とバイト比較する。

★DB 書込防止: project_service.save_active_project をモック(True を返すだけ)。
read-only(SELECT のみ)。
"""
from __future__ import annotations

import hashlib
import io
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
try:
    import tomllib as _toml
except ModuleNotFoundError:
    import tomli as _toml

creds = _toml.load(open(REPO / ".streamlit" / "secrets.readonly.toml", "rb"))["supabase"]
import streamlit.runtime.secrets as st_secrets
st_secrets.secrets_singleton._secrets = {"supabase": dict(creds)}

from sqlalchemy import create_engine, text  # noqa: E402
_e = create_engine(creds["DB_URL"], connect_args={"sslmode": "require"})
with _e.connect() as c:
    assert c.execute(text("SELECT current_user")).scalar() == "event_app_readonly"
_e.dispose()
print("[safety] current_user = event_app_readonly")

from streamlit.testing.v1 import AppTest  # noqa: E402
import views.flyer as vf  # noqa: E402
from services import generation_service as gs  # noqa: E402

vf.project_service.save_active_project = lambda: True  # ★DB 書込防止

TARGET = sys.argv[1] if len(sys.argv) > 1 else "2026-09-21"
fails = 0


def _sha(png):
    return hashlib.sha256(png).hexdigest()


def _png(img):
    b = io.BytesIO(); img.save(b, format="PNG"); return b.getvalue()


at = AppTest.from_file(str(REPO / "app.py"), default_timeout=600).run()
opts = [o for o in at.selectbox(key="ws_project_selector_label").options
        if o not in ("(選択してください)", "➕ 新規プロジェクト作成")]
label = next((o for o in opts if TARGET in o), None)
if label is None:
    print("SKIP: 対象プロジェクトが無い"); sys.exit(0)
at.selectbox(key="ws_project_selector_label").select(label).run()
assert not at.exception, at.exception
pid = at.session_state["tt_current_proj_id"]
print("[setup] project id=%s  %s" % (pid, label))

# API と同じ中間画像をアプリ側に差し込む(アプリの「設定反映」を押した状態を再現)
at.session_state["last_generated_grid_image"] = gs._render_grid_image_for_project(pid)
at.session_state["last_generated_tt_image"] = gs._render_tt_image_for_project(pid)

btn = next((b for b in at.button if "プレビューを生成" in str(b.label)), None)
assert btn is not None, "生成ボタンが見つからない"
btn.click().run()
assert not at.exception, "生成で例外: %s" % at.exception

for skey, variant in (("flyer_result_grid", "grid"), ("flyer_result_tt", "tt")):
    app_img = at.session_state[skey]
    app_png = _png(app_img)
    api_png = gs.render_flyer_png_for_project(pid, variant=variant)
    ok = (api_png is not None and _sha(app_png) == _sha(api_png))
    print(("  PASS  " if ok else "  FAIL  ")
          + "variant=%-5s app=%d bytes / api=%d bytes  sha %s"
          % (variant, len(app_png), len(api_png) if api_png else -1,
             "一致" if ok else "★不一致"))
    if not ok:
        fails += 1
        print("        app sha=%s" % _sha(app_png))
        print("        api sha=%s" % (_sha(api_png) if api_png else "None"))
        print("        app size=%s  api size=%s"
              % (app_img.size, __import__("PIL.Image", fromlist=["Image"]).open(io.BytesIO(api_png)).size if api_png else None))

print()
print("FLYER_E2E_PARITY_OK" if fails == 0 else "FLYER_E2E_PARITY_FAILED (%d)" % fails)
sys.exit(0 if fails == 0 else 1)
