# -*- coding: utf-8 -*-
"""TT 画像を生成して指定ディレクトリへ保存する(downscale 導入の前後比較用)。

使い方: .venv/bin/python3 scratch/gen_tt_images.py <out_dir> <project_id> [...]
read-only(SELECT のみ / 書き込みは out_dir と FONT_DIR)。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
try:
    import tomllib as _toml
except ModuleNotFoundError:
    import tomli as _toml
sec = _toml.loads((REPO / ".streamlit" / "secrets.readonly.toml").read_text())["supabase"]
os.environ.update(SUPABASE_DB_URL=sec["DB_URL"], SUPABASE_URL=sec["URL"], SUPABASE_KEY=sec["KEY"])

from services import generation_service as gs  # noqa: E402

out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
for a in sys.argv[2:]:
    pid = int(a)
    png = gs.render_timetable_png_for_project(pid)
    if png is None:
        print("  id=%-4s (生成不能)" % pid); continue
    p = out / ("tt_%d.png" % pid)
    p.write_bytes(png)
    print("  id=%-4s -> %s  (%.2f MB)" % (pid, p.name, len(png) / 1e6))
