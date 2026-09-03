# -*- coding: utf-8 -*-
"""render_timetable_png_for_project の豆腐検証(§45 A2 と同型)。

まっさらな FONT_DIR で、
  - フォントが materialize されるか
  - ImageFont.truetype が【実ファイルパス】で呼ばれるか(load_default に落ちていないか)
  - 日本語文字列のグリフが実際に描けるか(非ゼロピクセル)
を機械判定する。read-only DB / 書き込みは一時 FONT_DIR のみ。

使い方: .venv/bin/python3 scratch/verify_tt_render_glyph.py <project_id>
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

try:
    import tomllib as _toml
except ModuleNotFoundError:
    import tomli as _toml

sec = _toml.loads((REPO / ".streamlit" / "secrets.readonly.toml").read_text())["supabase"]
os.environ["SUPABASE_DB_URL"] = sec["DB_URL"]
os.environ["SUPABASE_URL"] = sec["URL"]
os.environ["SUPABASE_KEY"] = sec["KEY"]

from sqlalchemy import create_engine, text  # noqa: E402
_e = create_engine(sec["DB_URL"], connect_args={"sslmode": "require"})
with _e.connect() as c:
    u = c.execute(text("SELECT current_user")).scalar()
_e.dispose()
assert u == "event_app_readonly", "read-only 以外では実行しない: %r" % u
print("[safety] current_user =", u)

PROJECT_ID = int(sys.argv[1]) if len(sys.argv) > 1 else 12

import logic_timetable as lt              # noqa: E402
from services import font_service         # noqa: E402
import services.generation_service as gs  # noqa: E402
from PIL import ImageFont                 # noqa: E402

# --- まっさらな FONT_DIR に差し替え ---
tmp_dir = tempfile.mkdtemp(prefix="pristine_tt_fonts_")
lt.FONT_DIR = tmp_dir if hasattr(lt, "FONT_DIR") else None
font_service.FONT_DIR = tmp_dir
gs.FONT_DIR = tmp_dir
print("[setup] FONT_DIR = %s  中身=%s" % (tmp_dir, sorted(os.listdir(tmp_dir))))

# --- ImageFont の呼び出しを記録 ---
calls = {"ok": [], "exc": [], "load_default": 0}
_real_tt, _real_ld = ImageFont.truetype, ImageFont.load_default


def _spy_tt(font=None, size=10, *a, **k):
    try:
        r = _real_tt(font, size, *a, **k)
        calls["ok"].append(str(font))
        return r
    except Exception as e:
        calls["exc"].append((str(font), repr(e)))
        raise


def _spy_ld(*a, **k):
    calls["load_default"] += 1
    return _real_ld(*a, **k)


ImageFont.truetype, ImageFont.load_default = _spy_tt, _spy_ld
lt.ImageFont.truetype, lt.ImageFont.load_default = _spy_tt, _spy_ld

print("[run] render_timetable_png_for_project(%d) ..." % PROJECT_ID)
png = gs.render_timetable_png_for_project(PROJECT_ID)

path_calls = sorted({p for p in calls["ok"] if not p.startswith("<")})
fails = 0


def _chk(ok, label, extra=""):
    global fails
    print(("  PASS  " if ok else "  FAIL  ") + label + (("  " + extra) if extra else ""))
    if not ok:
        fails += 1


print()
print("=" * 66)
print("  PNG bytes            =", len(png) if png else None)
print("  FONT_DIR 実行後       =", sorted(os.listdir(tmp_dir)))
print("  truetype 実パス呼出   =", len(path_calls), path_calls)
print("  truetype 例外        =", len(calls["exc"]))
print("  load_default 呼出    =", calls["load_default"])
print("=" * 66)

_chk(bool(png), "(1) PNG が生成された")
_chk(len(path_calls) > 0 and len(calls["exc"]) == 0,
     "(2) 実ファイルパスで truetype が使われた(例外なし)")
_chk(all(p.startswith(tmp_dir) for p in path_calls),
     "(3) materialize した FONT_DIR のフォントを使っている(load_default に落ちていない)")

if path_calls:
    f = _real_tt(path_calls[0], 40)
    mask = f.getmask("手羽先センセーション")
    nz = sum(1 for i in range(mask.size[0] * mask.size[1])
             if mask.getpixel((i % mask.size[0], i // mask.size[0])))
    _chk(nz > 0, "(4) 日本語文字列のグリフが描画される", "非ゼロピクセル=%d / font=%s" % (nz, f.getname()))
else:
    _chk(False, "(4) 実パスのフォントが無い")

print()
print("TT_RENDER_GLYPH_ALL_PASS" if fails == 0 else "TT_RENDER_GLYPH_FAILED (%d)" % fails)
sys.exit(0 if fails == 0 else 1)
