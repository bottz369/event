"""
レガシー互換層。

フェーズ1では既存の views/overview.py, views/timetable.py, views/grid.py, views/flyer.py が
古いセッションキー(proj_title, tt_artists_order, など)を期待している。
それらを書き換えるのはフェーズ2以降。

それまでの間、新しい draft_project / draft_rows を古いキーに「写像」して
既存ビューを動かし続けるためのアダプタを置く。

フェーズ2以降、対応するビューを書き換えるたびにここの該当部分を削除していく。
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from models import POST_GOODS_ARTIST_NAME, PRE_GOODS_ARTIST_NAME
from services import session_manager
from utils.logger import get_logger

logger = get_logger(__name__)


def sync_draft_to_legacy_session() -> None:
    """
    draft_project / draft_rows の内容を、旧キーに反映する。
    既存ビューはこの旧キーを参照しているので、ここで橋渡しする。

    重要: この関数は reload_project() の中で clear_project_session() の直後
    にのみ呼ばれる前提。よってここでは常に強制上書きし、setdefault や
    「既にキーがあればスキップ」のパターンは使わない。
    そうしないと、clear が何らかの理由で残った旧データが新プロジェクト側に
    紛れ込む(= フェーズ1 の動作確認で見つかったバグ)。

    フェーズ1 ではプロジェクトロード直後に1回だけ呼ぶ。
    """
    draft = session_manager.get_draft_project()
    rows = session_manager.get_draft_rows()
    if draft is None:
        return

    # --- 基本情報 ---
    st.session_state.proj_title = draft.title
    st.session_state.proj_subtitle = draft.subtitle
    st.session_state.proj_date = draft.event_date
    st.session_state.proj_venue = draft.venue_name
    st.session_state.proj_url = draft.venue_url

    # --- 時間関連 ---
    st.session_state.tt_open_time = draft.open_time
    st.session_state.tt_start_time = draft.start_time
    st.session_state.tt_goods_offset = draft.goods_start_offset
    st.session_state.tt_current_proj_id = draft.id

    # --- チケット / 自由記述 / 共通備考 ---
    st.session_state.proj_tickets = (
        [t.to_dict() for t in draft.tickets]
        if draft.tickets
        else [{"name": "", "price": "", "note": ""}]
    )
    st.session_state.proj_ticket_notes = list(draft.ticket_notes)
    st.session_state.proj_free_text = (
        [f.to_dict() for f in draft.free_texts]
        if draft.free_texts
        else [{"title": "", "content": ""}]
    )

    # --- フォント・列数などの設定 ---
    settings = draft.settings or {}
    st.session_state.tt_font = settings.get("tt_font", "keifont.ttf")
    st.session_state.tt_columns = settings.get("tt_columns", 2)
    st.session_state.grid_font = settings.get("grid_font", "keifont.ttf")

    # --- グリッド設定 ---
    gs = draft.grid_settings or {}
    st.session_state.grid_order = gs.get("order", [])
    st.session_state.grid_cols = gs.get("cols", 5)
    st.session_state.grid_rows = gs.get("rows", 5)
    st.session_state.grid_row_counts_str = gs.get("row_counts_str", "5,5,5,5,5")
    st.session_state.grid_alignment = gs.get("alignment", "中央揃え")
    st.session_state.grid_layout_mode = gs.get("layout_mode", "レンガ (サイズ統一)")

    # --- フライヤー設定 ---
    # Phase 2B-1c-①: 「全消し→入れ直し」に変更。
    # 旧コードは draft.flyer_settings.items() を上書きするだけだったため、
    # 新プロジェクトに存在しないキーは旧プロジェクトの値が session_state に
    # 残留し、他タブ保存時の apply_draft merge で flyer_json を汚染していた。
    # clear_project_session でも flyer_ は消しているが、本関数の不変条件
    # (常に強制上書き)を維持する意図でここでも明示的に消す。
    for key in list(st.session_state.keys()):
        if isinstance(key, str) and key.startswith("flyer_"):
            del st.session_state[key]
    flyer = draft.flyer_settings or {}
    for k, v in flyer.items():
        sess_key = f"flyer_{k}"
        st.session_state[sess_key] = v

    # --- タイムテーブル行データを旧 3 分散形式に展開 ---
    _expand_rows_to_legacy(rows)

    # --- 制御フラグの初期化 ---
    # clear_project_session() の直後に views/timetable.py が attribute syntax
    # で参照するキーを setdefault しておく。これが無いと Streamlit Cloud などで
    # ensure_project_loaded() 経由の reload(=st.rerun を挟まない経路) を通った
    # ときに AttributeError になる。app.py の top-level defaults だけでは
    # clear と timetable レンダーが同一 run に乗ったケースを救えない。
    # フェーズ2 で views/timetable.py を書き換えて binding_df を廃止する際に、
    # これら 3 行も一緒に削除できる予定。
    st.session_state.setdefault("request_calc", False)
    st.session_state.setdefault("tt_editor_key", 0)
    st.session_state.setdefault("binding_df", pd.DataFrame())


def _expand_rows_to_legacy(rows) -> None:
    """
    draft_rows(TimetableRowDraft のリスト) を、
    既存 views/timetable.py 等が期待する以下のキーに展開する:
      - tt_artists_order: List[str]
      - tt_artist_settings: Dict[str, dict]
      - tt_row_settings: List[dict]
      - tt_has_pre_goods: bool
      - tt_pre_goods_settings: dict
      - tt_post_goods_settings: dict

    sync_draft_to_legacy_session() と同じ前提(clear 直後にのみ呼ばれる)で
    常に上書きする。早期 return はしない。
    """
    order = []
    artist_settings = {}
    row_settings = []
    has_pre_goods = False
    pre_settings = {
        "GOODS_START_MANUAL": "",
        "GOODS_DURATION": 60,
        "PLACE": "",
        "IS_HIDDEN": False,
    }
    post_settings = {
        "GOODS_START_MANUAL": "",
        "GOODS_DURATION": 60,
        "PLACE": "",
        "IS_HIDDEN": False,
    }

    for r in rows or []:
        if r.artist_name == PRE_GOODS_ARTIST_NAME:
            has_pre_goods = True
            pre_settings = {
                "GOODS_START_MANUAL": r.goods_start_time,
                "GOODS_DURATION": r.goods_duration,
                "PLACE": r.place,
                "IS_HIDDEN": r.is_hidden,
            }
            continue
        if r.artist_name == POST_GOODS_ARTIST_NAME:
            post_settings = {
                "GOODS_START_MANUAL": r.goods_start_time,
                "GOODS_DURATION": r.goods_duration,
                "PLACE": r.place,
                "IS_HIDDEN": r.is_hidden,
            }
            continue
        if not r.artist_name:
            continue

        order.append(r.artist_name)
        artist_settings[r.artist_name] = {"DURATION": r.duration}
        row_settings.append({
            "ADJUSTMENT": r.adjustment,
            "GOODS_START_MANUAL": r.goods_start_time,
            "GOODS_DURATION": r.goods_duration,
            "PLACE": r.place,
            "ADD_GOODS_START": r.add_goods_start_time,
            "ADD_GOODS_DURATION": r.add_goods_duration,
            "ADD_GOODS_PLACE": r.add_goods_place,
            "IS_POST_GOODS": r.is_post_goods,
            "IS_HIDDEN": r.is_hidden,
        })

    st.session_state.tt_artists_order = order
    st.session_state.tt_artist_settings = artist_settings
    st.session_state.tt_row_settings = row_settings
    st.session_state.tt_has_pre_goods = has_pre_goods
    st.session_state.tt_pre_goods_settings = pre_settings
    st.session_state.tt_post_goods_settings = post_settings
    st.session_state.rebuild_table_flag = True
