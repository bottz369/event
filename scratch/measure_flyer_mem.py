# -*- coding: utf-8 -*-
"""フライヤー生成のピーク RSS を実測(read-only)。

使い方: .venv/bin/python3 scratch/measure_flyer_mem.py <project_id> <variant>
1プロセス1計測(ru_maxrss は高水位マーク=単調増加のため)。
"""
from __future__ import annotations

import os
import resource
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

pid = int(sys.argv[1])
variant = sys.argv[2] if len(sys.argv) > 2 else "grid"


def maxrss_mb() -> float:
    ru = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return ru / (1024 * 1024) if sys.platform == "darwin" else ru / 1024


baseline = maxrss_mb()
png = gs.render_flyer_png_for_project(pid, variant=variant)
peak = maxrss_mb()

print("project_id / variant : %d / %s" % (pid, variant))
print("PNG bytes            : %.2f MB" % ((len(png) / 1e6) if png else 0))
print("baseline RSS         : %7.1f MB  (生成前)" % baseline)
print("peak RSS             : %7.1f MB" % peak)
print("生成による増分       : %7.1f MB" % (peak - baseline))
print("1GB に対する余裕     : %7.1f MB" % (1024.0 - peak))
