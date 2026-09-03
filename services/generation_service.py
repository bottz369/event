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
from logic_grid import generate_grid_image, resolve_font_path
from logic_timetable import generate_timetable_image
from repositories import project_repo
from services import artist_service, font_service, timetable_service
from utils.flyer_helpers import format_time_str
from utils.logger import get_logger
from utils.text_generator import build_event_summary_text

logger = get_logger(__name__)

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

        # フォントを DB から FONT_DIR へ materialize する(Railway 等 API/Bot 経路では
        # Streamlit view の ensure_font_available を通らず FONT_DIR が空のままになり、
        # generate_grid_image が PIL 既定フォントにフォールバック → 日本語ラベルが豆腐化する)。
        # grid_font 本体と、resolve_font_path の最終フォールバック先 "keifont.ttf" の両方を確保。
        # DB read + ローカル一時 FS write のみ(本番 Storage/DB 書き込みは無い)。
        # 失敗しても生成は続行(従来どおりフォールバックで画像自体は出る)。
        for _fname in dict.fromkeys([grid_font, "keifont.ttf"]):
            try:
                _status = font_service.ensure_font_available(_fname)
                logger.info("ensure_font_available(%r) -> %r", _fname, _status)
            except Exception as e:
                logger.warning("ensure_font_available(%r) failed: %s", _fname, e, exc_info=True)

        # materialize の結果を必ずログに残す。generate_grid_image は font 未解決でも
        # 黙って PIL 既定フォント(= 日本語が豆腐)にフォールバックして画像を返すため、
        # ここで警告を出さないと本番で豆腐が出ていることに誰も気づけない
        # (段階A2 のフォント materialize 修正 6a95fe2 が 6 週間見逃された実因。§45/罠40)。
        # 判定は logic_grid と同じ resolve_font_path を使う。
        _resolved = resolve_font_path(font_path) or resolve_font_path("keifont.ttf")
        if _resolved:
            logger.info("grid font resolved: %s", _resolved)
        else:
            try:
                _listing = sorted(os.listdir(FONT_DIR))
            except Exception:
                _listing = None
            logger.warning(
                "grid font NOT resolved (font_path=%r FONT_DIR=%r listing=%r). "
                "generate_grid_image will fall back to the PIL default font and "
                "Japanese labels will render as tofu.",
                font_path, FONT_DIR, _listing,
            )

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


def render_timetable_png_for_project(project_id: int) -> Optional[bytes]:
    """project_id のタイムテーブル画像を DB 設定から生成し PNG bytes で返す。

    未検出 project / 描画対象ゼロ(全行が「タイムテーブル非表示」等)は None。

    gather(views/timetable.py の画像生成ブロックを streamlit フリーに移植):
      - rows は timetable_service.get_rows_for_project(timetable_rows → data_json fallback)
      - open_time / start_time は project_repo.to_draft と同じ正規化を通す
        (アプリの session_state.tt_open_time / tt_start_time と同値)
      - gen_list は timetable_service.build_tt_gen_list_from_rows
        (OPEN / START 行と ★IS_HIDDEN=「タイムテーブル非表示」行を除外)
      - settings_json: tt_font(無ければ keifont.ttf)/ tt_columns(無ければ 2)
      - 24 組以上の強制 2 列は logic_timetable 側にあるのでここでは扱わない
    生成物は RGBA 透過なので PNG で bytes 化する(JPEG 不可)。

    OOM 対策: grid と同じ _render_lock を共有し、同時に 1 件だけ生成する
    (段階B でフライヤーが grid + TT + 合成を連続実行するため、両者を跨いで直列化する)。
    """
    with _render_lock:
        db = SessionLocal()
        try:
            proj = project_repo.get_project(db, project_id)
            if proj is None:
                return None
            draft = project_repo.to_draft(proj)  # open_time / start_time の正規化を再利用
            settings_raw = proj.settings_json
        finally:
            db.close()

        rows = timetable_service.get_rows_for_project(project_id)
        if not rows:
            return None

        settings = _loads_dict(settings_raw)
        tt_font = settings.get("tt_font") or "keifont.ttf"
        try:
            tt_columns = int(settings.get("tt_columns") or 2)
        except Exception:
            tt_columns = 2

        gen_list = timetable_service.build_tt_gen_list_from_rows(
            rows, draft.open_time, draft.start_time
        )
        if not gen_list:
            return None

        # フォントを DB から FONT_DIR へ materialize する(grid と同型・§45 A2)。
        # DB read + ローカル一時 FS write のみ(本番 Storage/DB 書き込みは無い)。
        for _fname in dict.fromkeys([tt_font, "keifont.ttf"]):
            try:
                _status = font_service.ensure_font_available(_fname)
                logger.info("ensure_font_available(%r) -> %r", _fname, _status)
            except Exception as e:
                logger.warning("ensure_font_available(%r) failed: %s", _fname, e, exc_info=True)

        # ★ grid との違い: logic_timetable.get_font の候補は
        #   [渡された path, assets/fonts/keifont.ttf, fonts/keifont.ttf, keifont.ttf] で
        #   **FONT_DIR を見ない**(logic_grid.resolve_font_path とは異なる)。
        #   つまり keifont.ttf を materialize してあっても、渡す path が実在しなければ
        #   PIL 既定フォントに落ちて日本語ラベルが豆腐になる。
        #   そこで service 側で FONT_DIR 内の keifont.ttf へ明示フォールバックする。
        font_path = os.path.join(FONT_DIR, tt_font)
        if not os.path.exists(font_path):
            fallback = os.path.join(FONT_DIR, "keifont.ttf")
            if os.path.exists(fallback):
                logger.warning(
                    "tt font not materialized (%r); falling back to %s", font_path, fallback
                )
                font_path = fallback
            else:
                try:
                    _listing = sorted(os.listdir(FONT_DIR))
                except Exception:
                    _listing = None
                logger.warning(
                    "timetable font NOT resolved (font_path=%r FONT_DIR=%r listing=%r). "
                    "generate_timetable_image will fall back to the PIL default font and "
                    "Japanese labels will render as tofu.",
                    font_path, FONT_DIR, _listing,
                )
        else:
            logger.info("timetable font resolved: %s", font_path)

        img = generate_timetable_image(gen_list, font_path=font_path, columns=tt_columns)
        if img is None:
            return None

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
