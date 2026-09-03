# -*- coding: utf-8 -*-
"""render_flyer_png_for_project の豆腐検証(§45 A2 と同型)。

まっさらな FONT_DIR で、実ファイルパスの truetype が使われ、日本語グリフが
描けることを機械判定する。read-only DB / 書き込みは一時 FONT_DIR のみ。
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
os.environ.update(SUPABASE_DB_URL=sec["DB_URL"], SUPABASE_URL=sec["URL"], SUPABASE_KEY=sec["KEY"])

from sqlalchemy import create_engine, text  # noqa: E402
_e = create_engine(sec["DB_URL"], connect_args={"sslmode": "require"})
with _e.connect() as c:
    assert c.execute(text("SELECT current_user")).scalar() == "event_app_readonly"
_e.dispose()
print("[safety] current_user = event_app_readonly")

PID = int(sys.argv[1]) if len(sys.argv) > 1 else 39
VARIANT = sys.argv[2] if len(sys.argv) > 2 else "grid"

import logic_grid as lg                    # noqa: E402
import logic_timetable as lt               # noqa: E402
import utils.flyer_generator as fg         # noqa: E402
import utils.flyer_helpers as fh           # noqa: E402
from services import font_service          # noqa: E402
import services.generation_service as gs   # noqa: E402
from PIL import ImageFont                  # noqa: E402

tmp = tempfile.mkdtemp(prefix="pristine_flyer_fonts_")
font_service.FONT_DIR = tmp
gs.FONT_DIR = tmp
lg.FONT_DIR = tmp
fg.FONT_DIR = tmp
# ★ensure_font_path → utils.flyer_helpers.ensure_font_file_exists は
#   自モジュールの FONT_DIR を見るので、ここも差し替えないと実 FONT_DIR を掴む。
fh.FONT_DIR = tmp
print("[setup] FONT_DIR = %s  中身=%s" % (tmp, sorted(os.listdir(tmp))))

calls = {"ok": [], "exc": [], "load_default": 0}
_rt, _rl = ImageFont.truetype, ImageFont.load_default


def _spy_tt(font=None, size=10, *a, **k):
    try:
        r = _rt(font, size, *a, **k); calls["ok"].append(str(font)); return r
    except Exception as e:
        calls["exc"].append((str(font), repr(e))); raise


def _spy_ld(*a, **k):
    calls["load_default"] += 1
    return _rl(*a, **k)


for mod in (ImageFont, lg.ImageFont, lt.ImageFont, fg.ImageFont):
    mod.truetype, mod.load_default = _spy_tt, _spy_ld

print("[run] render_flyer_png_for_project(%d, variant=%s) ..." % (PID, VARIANT))
png = gs.render_flyer_png_for_project(PID, variant=VARIANT)

path_calls = sorted({p for p in calls["ok"] if not p.startswith("<")})
fails = 0


def _chk(ok, label, extra=""):
    global fails
    print(("  PASS  " if ok else "  FAIL  ") + label + (("  " + extra) if extra else ""))
    if not ok:
        fails += 1


print()
print("  PNG bytes           =", len(png) if png else None)
print("  FONT_DIR 実行後      =", sorted(os.listdir(tmp)))
print("  truetype 実パス種類  =", len(path_calls))
for p in path_calls:
    print("     -", p)
print("  truetype 例外       =", len(calls["exc"]))
print("  load_default 呼出   =", calls["load_default"])
print()

_chk(bool(png), "(1) PNG が生成された")
_chk(len(path_calls) > 0 and len(calls["exc"]) == 0,
     "(2) 実ファイルパスで truetype が使われた(例外なし)")
_chk(all(p.startswith(tmp) for p in path_calls),
     "(3) materialize した FONT_DIR のフォントだけを使っている")

# ★(4) は「全フォントが日本語を持つ」ではない。
# create_flyer_image_shadow の draw_text_mixed は文字ごとに is_glyph_available で
# 判定し、持っていない文字だけ fallback フォントへ切り替える設計なので、
# 欧文フォント(Anzeigen Grotesk 等)が日本語を持たないのは正常。
# 日本語が豆腐にならない条件は「fallback フォントが日本語グリフを持つこと」。
kw = gs.build_flyer_kwargs_for_project(PID, variant=VARIANT)
fb = kw.get("system_fallback_filename") if kw else None
print("  fallback フォント     =", fb)
if fb and os.path.exists(str(fb)):
    f = _rt(str(fb), 40)
    m = f.getmask("日本語テスト")
    nz = sum(1 for i in range(m.size[0] * m.size[1])
             if m.getpixel((i % m.size[0], i // m.size[0])))
    _chk(nz > 0, "(4) ★fallback フォントが日本語グリフを描ける",
         "非ゼロ=%d / font=%s" % (nz, f.getname()))
else:
    _chk(False, "(4) fallback フォントが実パスとして存在しない", "-> %r" % fb)

# (5) 各スタイルフォントが実在パスに解決されている(未解決=豆腐警告の対象)
unresolved = [k for k in gs._FLYER_FONT_STYLE_KEYS
              if kw and kw["styles"].get(k) and not os.path.exists(str(kw["styles"][k]))]
_chk(not unresolved, "(5) スタイルフォントが全て実パスへ解決されている", "-> 未解決 %r" % unresolved)

print()
print("FLYER_GLYPH_ALL_PASS" if fails == 0 else "FLYER_GLYPH_FAILED (%d)" % fails)
sys.exit(0 if fails == 0 else 1)
