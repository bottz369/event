# -*- coding: utf-8 -*-
"""§42 豆腐化 診断/検証: まっさらな FONT_DIR で render_grid_png_for_project が
実際に truetype(keifont) を使ったか load_default(豆腐) に落ちたかを機械判定する。

- FONT_DIR を空の一時ディレクトリに差し替える(logic_grid / font_service /
  generation_service の3モジュールが値で持つ FONT_DIR をすべて patch)。
- ImageFont.truetype / load_default をラップして呼び出しを記録。
- read-only DB。書き込みは一時 FONT_DIR への materialize のみ。

引数: [project_id] [font_dir_mode]
  font_dir_mode: "empty"(既定・空の一時ディレクトリ) / "real"(実 FONT_DIR)
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

try:
    import tomllib as _toml
except ModuleNotFoundError:
    import tomli as _toml

# 認証情報: ローカルは read-only secrets ファイル、Docker(本番相当)は env 変数。
_SEC = REPO_ROOT / ".streamlit" / "secrets.readonly.toml"
if _SEC.exists():
    creds = _toml.load(open(_SEC, "rb"))["supabase"]
    import streamlit.runtime.secrets as st_secrets
    st_secrets.secrets_singleton._secrets = {"supabase": dict(creds)}
else:
    creds = {
        "DB_URL": os.environ["SUPABASE_DB_URL"],
        "URL": os.environ["SUPABASE_URL"],
        "KEY": os.environ["SUPABASE_KEY"],
    }

from sqlalchemy import create_engine, text
_e = create_engine(creds["DB_URL"], connect_args={"sslmode": "require"})
with _e.connect() as c:
    u = c.execute(text("SELECT current_user")).scalar()
_e.dispose()
assert u == "event_app_readonly", "read-only 以外では実行しない: %r" % u
print("[safety] current_user =", u)

PROJECT_ID = int(sys.argv[1]) if len(sys.argv) > 1 else 13
MODE = sys.argv[2] if len(sys.argv) > 2 else "empty"

import logic_grid                                  # noqa: E402
from services import font_service                  # noqa: E402
import services.generation_service as gs           # noqa: E402
from PIL import ImageFont                          # noqa: E402

# --- FONT_DIR をまっさらな一時ディレクトリへ差し替え ---
if MODE == "empty":
    tmp_font_dir = tempfile.mkdtemp(prefix="pristine_fonts_")
    logic_grid.FONT_DIR = tmp_font_dir
    font_service.FONT_DIR = tmp_font_dir
    gs.FONT_DIR = tmp_font_dir
    FONT_DIR = tmp_font_dir
else:
    from constants import FONT_DIR
print("[setup] FONT_DIR = %s  (mode=%s)" % (FONT_DIR, MODE))
print("[setup] 中身 =", sorted(os.listdir(FONT_DIR)))

# --- ImageFont の呼び出しを記録 ---
calls = {"truetype_ok": [], "truetype_exc": [], "load_default": 0}
_real_tt = ImageFont.truetype
_real_ld = ImageFont.load_default


def _spy_truetype(font=None, size=10, *a, **k):
    try:
        r = _real_tt(font, size, *a, **k)
        calls["truetype_ok"].append((str(font), size))
        return r
    except Exception as e:
        calls["truetype_exc"].append((str(font), size, repr(e)))
        raise


def _spy_load_default(*a, **k):
    calls["load_default"] += 1
    return _real_ld(*a, **k)


ImageFont.truetype = _spy_truetype
ImageFont.load_default = _spy_load_default
logic_grid.ImageFont.truetype = _spy_truetype
logic_grid.ImageFont.load_default = _spy_load_default

print("[run] render_grid_png_for_project(%d) ..." % PROJECT_ID)
png = gs.render_grid_png_for_project(PROJECT_ID)

print()
print("=" * 70)
print("結果")
print("=" * 70)
print("  PNG bytes            =", len(png) if png else None)
print("  FONT_DIR 実行後       =", sorted(os.listdir(FONT_DIR)))
print("  truetype 成功回数     =", len(calls["truetype_ok"]))
print("  truetype 例外回数     =", len(calls["truetype_exc"]))
print("  load_default 呼出回数 =", calls["load_default"])
uniq = sorted({p for p, _ in calls["truetype_ok"]})
print("  truetype に渡された実パス:")
for p in uniq:
    print("     -", p)
for p, s, e in calls["truetype_exc"][:5]:
    print("  truetype 例外:", p, s, e)

# --- 判定 ---
fails = 0
ok = bool(png)
print()
print(("  PASS  " if ok else "  FAIL  ") + "(1) PNG が生成された")
fails += 0 if ok else 1

# 注意: load_default() は内部で truetype(BytesIO) を呼ぶ。これを成功に数えると
# 豆腐でも PASS してしまうので、実ファイルパスでの truetype のみを数える。
path_calls = [p for p, _ in calls["truetype_ok"] if not p.startswith("<")]
ok = len(path_calls) > 0 and len(calls["truetype_exc"]) == 0
print(("  PASS  " if ok else "  FAIL  ")
      + "(2) 実ファイルパスで truetype が使われた (= font_exists=True, 例外なし) x%d" % len(path_calls))
fails += 0 if ok else 1

expected = os.path.join(FONT_DIR, "keifont.ttf")
ok = any(p == expected for p in uniq)
print(("  PASS  " if ok else "  FAIL  ") + "(3) 実パス %s で描画された (load_default に落ちていない)" % expected)
fails += 0 if ok else 1

# --- グリフ実在チェック: 日本語が本当に描けるフォントか ---
if os.path.exists(expected):
    f = _real_tt(expected, 40)
    try:
        mask = f.getmask("手羽先センセーション")
        nonzero = sum(1 for i in range(mask.size[0] * mask.size[1]) if mask.getpixel((i % mask.size[0], i // mask.size[0])))
    except Exception as e:
        nonzero = -1
        print("  getmask EXC:", repr(e))
    ok = nonzero > 0
    print(("  PASS  " if ok else "  FAIL  ")
          + "(4) 日本語文字列のグリフが描画される (非ゼロピクセル=%s)" % nonzero)
    fails += 0 if ok else 1
    try:
        print("       font family/style =", f.getname())
    except Exception:
        pass
else:
    print("  FAIL  (4) keifont.ttf が FONT_DIR に無い")
    fails += 1

if png:
    out = REPO_ROOT / "scratch" / ("diag_grid_%d_%s.png" % (PROJECT_ID, MODE))
    out.write_bytes(png)
    print("  生成物 ->", out)

print()
print("GRID_GLYPH_ALL_PASS" if fails == 0 else "GRID_GLYPH_FAILED (%d)" % fails)
sys.exit(0 if fails == 0 else 1)
