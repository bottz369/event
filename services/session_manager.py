"""
Streamlit セッションステートの一元管理。

このアプリの「最新情報がバグる」現象の根本原因は、
- ロード処理が複数箇所(workspace.py, timetable.py, overview.py)に存在し
- それぞれが独自のロード判定を持っていた
ことだった。

この session_manager で以下を保証する:

1. プロジェクト ID が変わったときに「必ず」セッションを完全クリアしてから再ロードする。
2. ロード処理はこの 1 箇所からしか呼ばれない。
3. session_state には「編集中のドラフト」だけが入る(SSOT は DB)。

セッションで管理するキーは原則 SESSION_PROJECT_KEYS に定義する。
他のビューはこれを参照すること(直接 st.session_state を漁らない)。
"""
from __future__ import annotations

from typing import List, Optional

import streamlit as st

from database import SessionLocal
from models import ProjectDraft, TimetableRowDraft
from repositories import project_repo, timetable_repo
from utils.logger import get_logger

logger = get_logger(__name__)


# =========================================================
# セッションキー定数
# =========================================================
# プロジェクトを開いている間だけ保持する状態のキー一覧。
# プロジェクト切替時はこれらすべてが消去される。
SESSION_PROJECT_KEYS = [
    # プロジェクトドラフト本体
    "draft_project",
    "draft_rows",
    # 直近 DB に保存した内容のスナップショット(未保存判定用)
    "saved_project_snapshot",
    "saved_rows_snapshot",
    # 生成済み画像のキャッシュ
    "last_generated_tt_image",
    "last_generated_grid_image",
    "last_generated_flyer_image",
    "flyer_result_grid",
    "flyer_result_tt",
    "flyer_layout_meta",
    # 旧キー(段階的削除のため一旦リストに含める)
    # フェーズ2 以降で実コードから消していくが、安全のため切替時には常に飛ばす
    "tt_artists_order",
    "tt_artist_settings",
    "tt_row_settings",
    "tt_has_pre_goods",
    "tt_pre_goods_settings",
    "tt_post_goods_settings",
    "tt_editor_key",
    "binding_df",
    "rebuild_table_flag",
    "tt_title",
    "tt_event_date",
    "tt_venue",
    "tt_open_time",
    "tt_start_time",
    "tt_goods_offset",
    "request_calc",
    "tt_current_proj_id",
    "tt_tickets",
    "tt_ticket_notes",
    "tt_unsaved_changes",
    "tt_columns",
    "tt_font",
    "tt_gen_list",
    "tt_last_generated_params",
    "tt_last_check_times_",
    "grid_order",
    "grid_cols",
    "grid_rows",
    "grid_row_counts_str",
    "grid_alignment",
    "grid_layout_mode",
    "grid_font",
    "grid_last_generated_params",
    "grid_settings_loaded",
    "current_proj_id_check",
    "proj_title",
    "proj_subtitle",
    "proj_venue",
    "proj_url",
    "proj_date",
    "proj_tickets",
    "proj_ticket_notes",
    "proj_free_text",
    "overview_last_saved_params",
    "overview_text_preview",
    "current_grid_proj_id",
]


ACTIVE_PROJECT_ID_KEY = "ws_active_project_id"


# =========================================================
# 公開 API
# =========================================================
def get_active_project_id() -> Optional[int]:
    """現在編集中のプロジェクト ID を返す。なければ None。"""
    return st.session_state.get(ACTIVE_PROJECT_ID_KEY)


def set_active_project_id(project_id: Optional[int]) -> None:
    """編集中プロジェクト ID をセット。実際の切替は ensure_project_loaded で。"""
    st.session_state[ACTIVE_PROJECT_ID_KEY] = project_id


def get_draft_project() -> Optional[ProjectDraft]:
    return st.session_state.get("draft_project")


def get_draft_rows() -> List[TimetableRowDraft]:
    rows = st.session_state.get("draft_rows")
    if rows is None:
        return []
    return rows


def set_draft_project(draft: ProjectDraft) -> None:
    st.session_state["draft_project"] = draft


def set_draft_rows(rows: List[TimetableRowDraft]) -> None:
    st.session_state["draft_rows"] = rows


def ensure_project_loaded(project_id: int) -> bool:
    """
    指定プロジェクトのドラフトが session_state に乗っているか確認し、
    乗っていなければ DB から読み直す。

    切替判定:
      - draft_project が無い、または draft_project.id != project_id のとき
        → セッションをクリアして再ロード
      - 一致しているなら何もしない(編集中の内容を保護)

    戻り値: ロード成功なら True、失敗なら False
    """
    current = get_draft_project()
    if current is not None and current.id == project_id:
        # すでに正しいプロジェクトがロード済み
        return True

    # 違うプロジェクトを開いていた / または未ロード
    return reload_project(project_id)


def reload_project(project_id: int) -> bool:
    """
    指定プロジェクトを DB から強制再ロードする。
    既存の編集中状態は破棄される。
    """
    clear_project_session()

    db = SessionLocal()
    try:
        proj = project_repo.get_project(db, project_id)
        if not proj:
            logger.error(f"reload_project: project not found id={project_id}")
            return False

        draft = project_repo.to_draft(proj)
        rows = timetable_repo.load_rows(db, project_id)

        set_draft_project(draft)
        set_draft_rows(rows)
        _save_snapshot(draft, rows)
        set_active_project_id(project_id)

        # 旧キーを期待しているビューのために互換層を呼ぶ
        # (フェーズ2 以降、各ビューを書き換えるたびにここの依存を減らしていく)
        from services import legacy_adapter
        legacy_adapter.sync_draft_to_legacy_session()

        logger.info(f"reload_project: loaded id={project_id}, rows={len(rows)}")
        return True
    except Exception as e:
        logger.error(f"reload_project failed: {e}", exc_info=True)
        return False
    finally:
        db.close()


def clear_project_session() -> None:
    """プロジェクトに紐づくセッション項目を一括削除する。"""
    for key in SESSION_PROJECT_KEYS:
        if key in st.session_state:
            del st.session_state[key]

    # 動的に作られるキー(プレフィックス一致で消すもの)
    dynamic_prefixes = (
        "tt_last_check_times_",
        "t_name_",
        "t_price_",
        "t_note_",
        "t_common_note_",
        "f_title_",
        "f_content_",
        "tt_editor_",
        "coord_grid",
        "coord_tt",
        "last_coord_",
        "ov_tt_open_time",
        "ov_tt_start_time",
    )
    for key in list(st.session_state.keys()):
        if isinstance(key, str) and key.startswith(dynamic_prefixes):
            del st.session_state[key]


# =========================================================
# 未保存変更の検知
# =========================================================
def has_unsaved_changes() -> bool:
    """draft と最後にセーブしたスナップショットを比較して差分があるか判定。"""
    draft = get_draft_project()
    rows = get_draft_rows()
    snap_proj = st.session_state.get("saved_project_snapshot")
    snap_rows = st.session_state.get("saved_rows_snapshot")

    if draft is None or snap_proj is None:
        return False

    return _project_to_comparable(draft) != snap_proj or _rows_to_comparable(rows) != snap_rows


def mark_saved() -> None:
    """現在のドラフト内容を「最後に保存した状態」として記録する。"""
    draft = get_draft_project()
    rows = get_draft_rows()
    if draft is not None:
        _save_snapshot(draft, rows)


def _save_snapshot(draft: ProjectDraft, rows: List[TimetableRowDraft]) -> None:
    st.session_state["saved_project_snapshot"] = _project_to_comparable(draft)
    st.session_state["saved_rows_snapshot"] = _rows_to_comparable(rows)


def _project_to_comparable(draft: ProjectDraft):
    """ProjectDraft を比較可能な tuple/dict 構造に変換する。"""
    return (
        draft.id,
        draft.title,
        draft.subtitle,
        str(draft.event_date) if draft.event_date else None,
        draft.venue_name,
        draft.venue_url,
        draft.open_time,
        draft.start_time,
        draft.goods_start_offset,
        tuple((t.name, t.price, t.note) for t in draft.tickets),
        tuple(draft.ticket_notes),
        tuple((f.title, f.content) for f in draft.free_texts),
        # settings/grid_settings/flyer_settings は dict のまま比較できるよう json 化
        _stable_repr(draft.settings),
        _stable_repr(draft.grid_settings),
        _stable_repr(draft.flyer_settings),
    )


def _rows_to_comparable(rows: List[TimetableRowDraft]):
    return tuple(
        (
            r.artist_name, r.duration, r.adjustment, r.is_post_goods, r.is_hidden,
            r.goods_start_time, r.goods_duration, r.place,
            r.add_goods_start_time, r.add_goods_duration, r.add_goods_place,
        )
        for r in rows
    )


def _stable_repr(obj):
    """dict の中身比較用。順序を安定化させる。"""
    import json
    try:
        return json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:
        return repr(obj)
