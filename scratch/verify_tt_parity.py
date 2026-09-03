# -*- coding: utf-8 -*-
"""TT 画像の生成結果ハッシュを出す(streamlit optional 化の前後でバイト一致を証明する)。

使い方: .venv/bin/python3 scratch/verify_tt_parity.py <project_id> [<project_id> ...]
read-only(DB は SELECT のみ / 書き込みは FONT_DIR への materialize だけ)。
"""
from __future__ import annotations

import hashlib
import io
import json
import os
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

from constants import FONT_DIR  # noqa: E402
from database import SessionLocal  # noqa: E402
from logic_timetable import generate_timetable_image  # noqa: E402
from models.timetable import draft_rows_to_df  # noqa: E402
from repositories import project_repo, timetable_repo  # noqa: E402
from services import font_service  # noqa: E402
from utils import calculate_timetable_flow  # noqa: E402


def gather(pid):
    db = SessionLocal()
    try:
        proj = project_repo.get_project(db, pid)
        if proj is None:
            return None
        rows = timetable_repo.load_rows(db, pid)
        settings = json.loads(proj.settings_json) if proj.settings_json else {}
        open_time = (proj.open_time or "10:00")[:5]
        start_time = (proj.start_time or "10:30")[:5]
    finally:
        db.close()

    df = draft_rows_to_df(rows)
    calculated = calculate_timetable_flow(df, open_time, start_time)
    flags = df["IS_HIDDEN"].tolist() if "IS_HIDDEN" in df.columns else [False] * len(df)
    gen_list, idx = [], 0
    for _, r in calculated.iterrows():
        if r["ARTIST"] == "OPEN / START":
            continue
        hid = flags[idx] if idx < len(flags) else False
        idx += 1
        if hid:
            continue
        gen_list.append([r["TIME_DISPLAY"], r["ARTIST"], r["GOODS_DISPLAY"], r["PLACE"]])

    return gen_list, (settings.get("tt_font") or "keifont.ttf"), int(settings.get("tt_columns") or 2)


for arg in sys.argv[1:]:
    pid = int(arg)
    g = gather(pid)
    if g is None:
        print("  id=%-4s (未検出)" % pid)
        continue
    gen_list, tt_font, cols = g
    font_service.ensure_font_available(tt_font)
    font_service.ensure_font_available("keifont.ttf")
    fp = os.path.join(os.path.abspath(FONT_DIR), tt_font)
    img = generate_timetable_image(gen_list, font_path=fp, columns=cols)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    raw = img.tobytes()
    print("  id=%-4s rows=%-3d font=%-26s cols=%d  size=%dx%d"
          % (pid, len(gen_list), tt_font, cols, img.width, img.height))
    print("        pixels sha256 = %s" % hashlib.sha256(raw).hexdigest())
    print("        png    sha256 = %s  (%d bytes)"
          % (hashlib.sha256(buf.getvalue()).hexdigest(), len(buf.getvalue())))
