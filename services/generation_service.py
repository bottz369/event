"""生成トリガー用サービス(§11.7 段階A1・§36 バケツ①)。

Web API(bot/api.py)から「告知テキスト」「grid 画像」を生成するための、
DB から引数を組む streamlit フリーの gather 層。

不変条件(絶対):
- このモジュールは streamlit を一切 import しない(直下も、辿る先も)。
  views/ や session_manager / project_service(いずれも streamlit を引く)は import しない。
- 既存ロジック関数(utils.text_generator.build_event_summary_text /
  logic_grid.generate_grid_image)は「呼ぶだけ」で中身は変更しない。
- read + generate のみ。DB / Storage への書き込みは行わない。

gather は既存 view(views/flyer.py:490-516 / views/grid.py の設定マッピング)の
導出を「そのまま」DB からに移植したもの。session_state フォールバックは持たない。
"""
from __future__ import annotations

import io
import json
import os
import threading
from typing import List, Optional

from constants import FONT_DIR
from database import SessionLocal
from logic_grid import generate_grid_image
from repositories import project_repo
from services import artist_service, timetable_service
from utils.flyer_helpers import format_time_str
from utils.text_generator import build_event_summary_text

# 物販専用行(出演者一覧から除外する。views/flyer.py:506 と同一)
_SPECIAL_ROW_NAMES = ("開演前物販", "終演後物販")

# grid 設定の日本語ラベル → 内部値(views/grid.py:242-244 と同一)
_ALIGN_MAP = {"左揃え": "left", "中央揃え": "center", "右揃え": "right"}
_BRICK_LABEL = "レンガ (サイズ統一)"

# OOM 対策: grid 画像生成を API 経路で直列化する(同時に1件だけ生成)。
# 複数 /grid-image 同時アクセスで full-res 生成のピークが積み上がるのを防ぐ。
# ※ logic_grid 自体はロックしない(アプリ側の単独利用は直列化しない)。
_render_lock = threading.Lock()


def _loads_list(raw) -> list:
    """JSON 文字列を list として読む。None / 壊れ / 非 list は []。"""
    if not raw:
        return []
    try:
        v = json.loads(raw)
    except Exception:
        return []
    return v if isinstance(v, list) else []


def _loads_dict(raw) -> dict:
    """JSON 文字列を dict として読む。None / 壊れ / 非 dict は {}。"""
    if not raw:
        return {}
    try:
        v = json.loads(raw)
    except Exception:
        return {}
    return v if isinstance(v, dict) else {}


def build_summary_text_for_project(project_id: int) -> Optional[str]:
    """project_id の告知テキストを DB から組んで返す。未検出は None。

    gather(views/flyer.py:490-516 の DB 経路を移植):
      - project は ProjectView(get_project_view 相当)で読む。
      - tickets / ticket_notes / free_texts は tickets_json / ticket_notes_json /
        free_text_json を json.loads した生 list(dict/str)をそのまま渡す
        (build_event_summary_text は isinstance(t, dict) 前提)。
      - open_time / start_time は format_time_str で整形。
      - 出演者名は grid_order_json["order"]、無ければ rows[].artist_name。
        特殊行(開演前/終演後物販)と is_hidden 行を除外。
    """
    db = SessionLocal()
    try:
        view = project_repo.get_project_view(db, project_id)  # ProjectView(frozen・close 後も安全)
    finally:
        db.close()
    if view is None:
        return None

    tickets = _loads_list(view.tickets_json)
    ticket_notes = _loads_list(view.ticket_notes_json)
    free_texts = _loads_list(view.free_text_json)

    rows = timetable_service.get_rows_for_project(project_id)
    hidden_map = {r.artist_name: r.is_hidden for r in rows if r.artist_name}

    raw_order: List[str] = []
    if view.grid_order_json:
        try:
            raw_order = json.loads(view.grid_order_json).get("order", []) or []
        except Exception:
            raw_order = []
    if not raw_order and rows:
        raw_order = [r.artist_name for r in rows]

    filtered_artists: List[str] = []
    for name in raw_order:
        if name in _SPECIAL_ROW_NAMES:
            continue
        if hidden_map.get(name, False):
            continue
        filtered_artists.append(name)

    return build_event_summary_text(
        title=view.title,
        subtitle=view.subtitle,
        date_val=view.event_date,
        venue=view.venue_name,
        url=view.venue_url,
        open_time=format_time_str(view.open_time),
        start_time=format_time_str(view.start_time),
        tickets=tickets,
        ticket_notes=ticket_notes,
        artists=filtered_artists,
        free_texts=free_texts,
    )


def render_grid_png_for_project(project_id: int) -> Optional[bytes]:
    """project_id の grid 画像を DB 設定から生成し PNG bytes で返す。

    未検出 project / 出演者ゼロ(generate_grid_image が None)は None。

    gather(views/grid.py の設定マッピングを streamlit フリーに移植):
      - grid_order_json: order(出演者名)/ row_counts_str / layout_mode / alignment
      - settings_json: grid_font(無ければ keifont.ttf)
      - alignment ラベル → left/center/right、layout_mode == "レンガ (サイズ統一)" → is_brick
      - row_counts_str を "," 区切りで int 化(空は None → generate 側で既定 [5]*10)
      - artists は get_artists_by_names(order)。generate_grid_image を直呼び。
    生成物は RGBA 透過なので PNG で bytes 化する(JPEG 不可)。

    OOM 対策: モジュールレベルの _render_lock で全体を囲み、同時に1件だけ生成する。
    """
    with _render_lock:
        db = SessionLocal()
        try:
            proj = project_repo.get_project(db, project_id)  # ORM(settings_json も要るため)
            if proj is None:
                return None
            grid_order_raw = proj.grid_order_json
            settings_raw = proj.settings_json
        finally:
            db.close()

        grid = _loads_dict(grid_order_raw)
        settings = _loads_dict(settings_raw)

        order = grid.get("order") or []
        row_counts_str = grid.get("row_counts_str") or ""
        layout_mode = grid.get("layout_mode")
        alignment_label = grid.get("alignment")

        alignment = _ALIGN_MAP.get(alignment_label, "center")
        is_brick = layout_mode == _BRICK_LABEL
        try:
            row_counts = [int(x.strip()) for x in row_counts_str.split(",") if x.strip()]
        except Exception:
            row_counts = []
        row_counts = row_counts or None  # 空は None → generate_grid_image が既定 [5]*10 を使う

        grid_font = settings.get("grid_font") or "keifont.ttf"
        font_path = os.path.join(FONT_DIR, grid_font)

        artists = artist_service.get_artists_by_names(order)
        if not artists:
            return None

        img = generate_grid_image(
            artists,
            "",  # image_dir_unused(logic_grid 側で未使用)
            font_path=font_path,
            row_counts=row_counts,
            is_brick_mode=is_brick,
            alignment=alignment,
        )
        if img is None:
            return None

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
