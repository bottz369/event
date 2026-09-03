# -*- coding: utf-8 -*-
"""TT 画像生成のピーク RSS を実測(read-only・書き込みなし)。

使い方: .venv/bin/python3 scratch/measure_tt_mem.py <project_id>
1プロセス1計測(ru_maxrss は高水位マークで単調増加のため)。
scratch/measure_grid_mem.py と同手法・同じ出力形式で比較できるようにする。
"""
from __future__ import annotations

import io
import json
import os
import resource
import sys
from pathlib import Path

try:
    import tomllib as _toml
except ModuleNotFoundError:
    import tomli as _toml

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sec = _toml.loads((REPO / ".streamlit" / "secrets.readonly.toml").read_text())["supabase"]
os.environ["SUPABASE_DB_URL"] = sec["DB_URL"]
os.environ["SUPABASE_URL"] = sec["URL"]
os.environ["SUPABASE_KEY"] = sec["KEY"]

import pandas as pd  # noqa: E402

from constants import FONT_DIR  # noqa: E402
from database import SessionLocal  # noqa: E402
from logic_timetable import generate_timetable_image  # noqa: E402
from models.timetable import draft_rows_to_df  # noqa: E402
from repositories import project_repo, timetable_repo  # noqa: E402
from services import font_service  # noqa: E402
from utils import calculate_timetable_flow  # noqa: E402

pid = int(sys.argv[1])


def maxrss_mb() -> float:
    ru = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":
        return ru / (1024 * 1024)
    return ru / 1024


# --- gather (views/timetable.py:735-757 のロジックを inline。step2 で純関数化する) ---
db = SessionLocal()
try:
    proj = project_repo.get_project(db, pid)
    rows = timetable_repo.load_rows(db, pid)
    settings = json.loads(proj.settings_json) if proj and proj.settings_json else {}
    open_time = (proj.open_time or "10:00")[:5]
    start_time = (proj.start_time or "10:30")[:5]
finally:
    db.close()

tt_font = settings.get("tt_font") or "keifont.ttf"
tt_columns = int(settings.get("tt_columns") or 2)

df = draft_rows_to_df(rows)
calculated = calculate_timetable_flow(df, open_time, start_time)
hidden_flags = df["IS_HIDDEN"].tolist() if "IS_HIDDEN" in df.columns else [False] * len(df)

gen_list = []
idx = 0
for _, r in calculated.iterrows():
    if r["ARTIST"] == "OPEN / START":
        continue
    hidden = hidden_flags[idx] if idx < len(hidden_flags) else False
    idx += 1
    if hidden:
        continue
    gen_list.append([r["TIME_DISPLAY"], r["ARTIST"], r["GOODS_DISPLAY"], r["PLACE"]])

font_service.ensure_font_available(tt_font)
font_service.ensure_font_available("keifont.ttf")
font_path = os.path.join(os.path.abspath(FONT_DIR), tt_font)

baseline_mb = maxrss_mb()  # imports + DB + gather 済みの高水位(生成前)
img = generate_timetable_image(gen_list, font_path=font_path, columns=tt_columns)
peak_mb = maxrss_mb()

buf = io.BytesIO()
if img is not None:
    img.save(buf, format="PNG")
png_bytes = len(buf.getvalue())
after_png_mb = maxrss_mb()

print("project_id      : %d" % pid)
print("DB 行数         : %d  (うち非表示 %d)" % (len(rows), sum(1 for x in hidden_flags if x)))
print("描画行数        : %d" % len(gen_list))
print("tt_font         : %s / columns=%d" % (tt_font, tt_columns))
print("出力サイズ      : %dx%d  mode=%s" % (img.width, img.height, img.mode) if img else "出力なし")
print("PNG bytes       : %.1f MB" % (png_bytes / 1e6))
print("-" * 46)
print("baseline RSS    : %7.1f MB  (生成前)" % baseline_mb)
print("peak RSS        : %7.1f MB  (generate 直後)" % peak_mb)
print("after PNG 化    : %7.1f MB" % after_png_mb)
print("生成による増分  : %7.1f MB" % (peak_mb - baseline_mb))
