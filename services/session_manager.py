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

import datetime
from typing import List, Optional

import streamlit as st

from database import SessionLocal
from models import (
    POST_GOODS_ARTIST_NAME,
    PRE_GOODS_ARTIST_NAME,
    FreeTextDraft,
    ProjectDraft,
    TicketDraft,
    TimetableRowDraft,
)
from models.flyer_keys import non_persisted_session_keys
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


# =========================================================
# session_state -> draft 同期(保存直前に呼ぶ)
# =========================================================
# session_state には view 層が widget 経由で書き込んだ生キー
# (proj_title, tt_open_time, proj_tickets, ...) が入っている。
# 一方 draft_project は reload 時にしか更新されず、編集中の値が反映されていない。
# このため、save_active_project() を view から呼んだだけでは画面入力が保存されない。
#
# sync_session_to_draft() は保存直前に呼び、session_state -> draft の写像を行う。
# フェーズ2B で view を draft_rows 直接編集に書き換える際、本関数は不要になり削除予定。
# =========================================================

# レジストリに乗らない transient な session_state キー(設定値ではなく一時状態)。
# ここに該当: PIL.Image などの生成物 / クリック追跡用フラグ。
_FLYER_TRANSIENT_KEYS = {
    # PIL.Image など serializable でない transient データ
    "flyer_result_grid",
    "flyer_result_tt",
    "flyer_layout_meta",
    # UI のクリック追跡用、永続化しない
    "flyer_click_target",
}

# Phase 2B-2b-2: UI 専用フラグ (flyer_grid_link / flyer_tt_link / flyer_preview_width)
# は models/flyer_keys.py の FLYER_KEY_REGISTRY で persist=False と定義済み。
# 二重管理を解消し SSOT を registry に統一するため、ここではレジストリから動的に
# 取得する (Phase 2B-2a で手書きだった 3 行を削除)。
# 変更前後で _FLYER_EXCLUDED_KEYS の集合は同一 (7 キー: transient 4 + UI 3)。
_FLYER_EXCLUDED_KEYS = _FLYER_TRANSIENT_KEYS | non_persisted_session_keys()

# session_state のキーから draft.grid_settings のキーへの写像
_GRID_KEY_MAP = {
    "grid_order": "order",
    "grid_cols": "cols",
    "grid_rows": "rows",
    "grid_row_counts_str": "row_counts_str",
    "grid_alignment": "alignment",
    "grid_layout_mode": "layout_mode",
}


def _coerce_int(value, default: int) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _coerce_optional_int(value) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _coerce_str(value) -> str:
    if value is None:
        return ""
    s = str(value)
    return "" if s.lower() == "nan" else s


def _rebuild_draft_rows_from_legacy() -> Optional[List[TimetableRowDraft]]:
    """
    session_state のレガシーキーから draft_rows を再構築する
    (legacy_adapter._expand_rows_to_legacy の逆変換)。

    参照キー:
      - tt_artists_order      : List[str]   (並び順 = sort_order)
      - tt_artist_settings    : Dict[str, {"DURATION": int}]
      - tt_row_settings       : List[dict]  (ADJUSTMENT / GOODS_* / ADD_GOODS_* / IS_POST_GOODS / IS_HIDDEN)
      - tt_has_pre_goods      : bool
      - tt_pre_goods_settings : dict
      - tt_post_goods_settings: dict

    返り値:
      - None: tt_artists_order が未初期化(キー無し or None)。呼び出し側は
              既存 draft_rows を維持すること。
              これにより、TT タブをまだ開いていないプロジェクトや、
              ロード直後で legacy_adapter による sync が走る前に
              空リストで上書きする事故を防ぐ。
      - List[TimetableRowDraft]: 再構築結果。[] も有効値(アーティスト 0 件)。
    """
    if "tt_artists_order" not in st.session_state:
        return None
    order = st.session_state.get("tt_artists_order")
    if order is None:
        return None

    artist_settings = st.session_state.get("tt_artist_settings", {}) or {}
    row_settings = st.session_state.get("tt_row_settings", []) or []
    has_pre = bool(st.session_state.get("tt_has_pre_goods", False))
    pre = st.session_state.get("tt_pre_goods_settings", {}) or {}
    post = st.session_state.get("tt_post_goods_settings", {}) or {}

    rebuilt: List[TimetableRowDraft] = []

    if has_pre:
        rebuilt.append(TimetableRowDraft(
            artist_name=PRE_GOODS_ARTIST_NAME,
            duration=0,
            adjustment=0,
            is_post_goods=False,
            is_hidden=bool(pre.get("IS_HIDDEN", False)),
            goods_start_time=_coerce_str(pre.get("GOODS_START_MANUAL")),
            goods_duration=_coerce_int(pre.get("GOODS_DURATION"), 60),
            place=_coerce_str(pre.get("PLACE")),
        ))

    has_post = False
    for i, name in enumerate(order):
        if not name:
            continue
        ad = artist_settings.get(name, {}) or {}
        rd = (row_settings[i] if i < len(row_settings) else {}) or {}
        is_post = bool(rd.get("IS_POST_GOODS", False))
        if is_post:
            has_post = True

        rebuilt.append(TimetableRowDraft(
            artist_name=_coerce_str(name),
            duration=_coerce_int(ad.get("DURATION"), 20),
            adjustment=_coerce_int(rd.get("ADJUSTMENT"), 0),
            is_post_goods=is_post,
            is_hidden=bool(rd.get("IS_HIDDEN", False)),
            goods_start_time=_coerce_str(rd.get("GOODS_START_MANUAL")),
            goods_duration=_coerce_int(rd.get("GOODS_DURATION"), 60),
            place=_coerce_str(rd.get("PLACE")),
            add_goods_start_time=_coerce_str(rd.get("ADD_GOODS_START")),
            add_goods_duration=_coerce_optional_int(rd.get("ADD_GOODS_DURATION")),
            add_goods_place=_coerce_str(rd.get("ADD_GOODS_PLACE")),
        ))

    if has_post:
        rebuilt.append(TimetableRowDraft(
            artist_name=POST_GOODS_ARTIST_NAME,
            duration=0,
            adjustment=0,
            is_post_goods=False,
            is_hidden=bool(post.get("IS_HIDDEN", False)),
            goods_start_time=_coerce_str(post.get("GOODS_START_MANUAL")),
            goods_duration=_coerce_int(post.get("GOODS_DURATION"), 60),
            place=_coerce_str(post.get("PLACE")),
        ))

    return rebuilt


def _is_persistable(value) -> bool:
    """JSON 化可能か簡易判定(scalar / list / dict のみ許容)。"""
    if value is None or isinstance(value, (str, int, float, bool)):
        return True
    if isinstance(value, (list, tuple)):
        return all(_is_persistable(v) for v in value)
    if isinstance(value, dict):
        return all(isinstance(k, str) and _is_persistable(v) for k, v in value.items())
    return False


def sync_session_to_draft() -> bool:
    """
    st.session_state の現在値を draft_project に書き戻す。

    save_active_project() の冒頭で呼ぶことで、view 側は session_state の
    生キー(proj_title, tt_open_time, proj_tickets, ...) を更新するだけで済む。

    対象キー(ProjectDraft 側):
      - proj_title → draft.title
      - proj_subtitle → draft.subtitle
      - proj_date → draft.event_date (date 型に変換)
      - proj_venue → draft.venue_name
      - proj_url → draft.venue_url
      - tt_open_time → draft.open_time
      - tt_start_time → draft.start_time
      - tt_goods_offset → draft.goods_start_offset
      - proj_tickets → draft.tickets (TicketDraft への正規化)
      - proj_ticket_notes → draft.ticket_notes
      - proj_free_text → draft.free_texts (FreeTextDraft への正規化)
      - tt_font / tt_columns / grid_font → draft.settings(既存 dict に merge)
      - flyer_* → draft.flyer_settings(prefix を strip, transient を除外して merge)
      - grid_* → draft.grid_settings(_GRID_KEY_MAP の通り merge)

    draft_rows は、tt_artists_order / tt_artist_settings / tt_row_settings /
    tt_has_pre_goods / tt_pre_goods_settings / tt_post_goods_settings から
    _rebuild_draft_rows_from_legacy() で再構築する
    (legacy_adapter._expand_rows_to_legacy の逆変換)。
    tt_artists_order が未初期化のときは既存 draft_rows を維持する。
    フェーズ2B-2 以降で view を書き換えて draft_rows を直接編集するように
    したら、この再構築は不要になり削除予定。

    Returns:
        True: draft を更新した
        False: アクティブな draft が無いなどで更新できなかった
    """
    draft = get_draft_project()
    if draft is None:
        logger.debug("sync_session_to_draft: no active draft, skipping")
        return False

    updated_fields: List[str] = []

    # --- 基本情報 ---
    if "proj_title" in st.session_state:
        draft.title = str(st.session_state.proj_title or "")
        updated_fields.append("title")
    if "proj_subtitle" in st.session_state:
        draft.subtitle = str(st.session_state.proj_subtitle or "")
        updated_fields.append("subtitle")
    if "proj_date" in st.session_state:
        v = st.session_state.proj_date
        try:
            if v is None or v == "":
                draft.event_date = None
            elif isinstance(v, datetime.datetime):
                draft.event_date = v.date()
            elif isinstance(v, datetime.date):
                draft.event_date = v
            else:
                draft.event_date = datetime.datetime.strptime(str(v), "%Y-%m-%d").date()
            updated_fields.append("event_date")
        except Exception as e:
            logger.warning(f"sync_session_to_draft: cannot parse proj_date {v!r}: {e}")
    if "proj_venue" in st.session_state:
        draft.venue_name = str(st.session_state.proj_venue or "")
        updated_fields.append("venue_name")
    if "proj_url" in st.session_state:
        draft.venue_url = str(st.session_state.proj_url or "")
        updated_fields.append("venue_url")

    # --- 時間 ---
    if "tt_open_time" in st.session_state:
        draft.open_time = str(st.session_state.tt_open_time or "")
        updated_fields.append("open_time")
    if "tt_start_time" in st.session_state:
        draft.start_time = str(st.session_state.tt_start_time or "")
        updated_fields.append("start_time")
    if "tt_goods_offset" in st.session_state:
        try:
            draft.goods_start_offset = int(st.session_state.tt_goods_offset or 0)
            updated_fields.append("goods_start_offset")
        except Exception as e:
            logger.warning(f"sync_session_to_draft: cannot parse tt_goods_offset: {e}")

    # --- チケット / 自由記述 / 共通備考 ---
    if "proj_tickets" in st.session_state:
        raw = st.session_state.proj_tickets or []
        if isinstance(raw, list):
            draft.tickets = [TicketDraft.from_dict(t) for t in raw]
            updated_fields.append(f"tickets[{len(draft.tickets)}]")
    if "proj_ticket_notes" in st.session_state:
        raw = st.session_state.proj_ticket_notes or []
        if isinstance(raw, list):
            draft.ticket_notes = [str(n) for n in raw if n is not None]
            updated_fields.append(f"ticket_notes[{len(draft.ticket_notes)}]")
    if "proj_free_text" in st.session_state:
        raw = st.session_state.proj_free_text or []
        if isinstance(raw, list):
            draft.free_texts = [FreeTextDraft.from_dict(f) for f in raw]
            updated_fields.append(f"free_texts[{len(draft.free_texts)}]")

    # --- settings (tt_font / tt_columns / grid_font を既存 dict にマージ) ---
    settings = dict(draft.settings or {})
    if "tt_font" in st.session_state:
        settings["tt_font"] = st.session_state.tt_font
    if "tt_columns" in st.session_state:
        settings["tt_columns"] = st.session_state.tt_columns
    if "grid_font" in st.session_state:
        settings["grid_font"] = st.session_state.grid_font
    draft.settings = settings

    # --- grid_settings (grid_* → draft.grid_settings、prefix strip) ---
    grid_settings = dict(draft.grid_settings or {})
    for sess_key, settings_key in _GRID_KEY_MAP.items():
        if sess_key in st.session_state:
            grid_settings[settings_key] = st.session_state[sess_key]
    draft.grid_settings = grid_settings

    # --- flyer_settings (flyer_* → draft.flyer_settings、prefix strip, transient 除外) ---
    flyer_settings = dict(draft.flyer_settings or {})
    flyer_added = 0
    for key in list(st.session_state.keys()):
        if not isinstance(key, str) or not key.startswith("flyer_"):
            continue
        if key in _FLYER_EXCLUDED_KEYS:
            continue
        value = st.session_state[key]
        if not _is_persistable(value):
            continue
        short_key = key[len("flyer_"):]
        flyer_settings[short_key] = value
        flyer_added += 1
    draft.flyer_settings = flyer_settings

    # dataclass は mutable なので set_draft_project は厳密には不要だが、明示的に書き戻す
    set_draft_project(draft)

    # --- draft_rows: レガシーキーから再構築(_expand_rows_to_legacy の逆) ---
    # tt_artists_order が未初期化なら既存 draft_rows を維持(ロード直後や
    # TT タブ未表示時に空で上書きしない安全策)。
    rebuilt_rows = _rebuild_draft_rows_from_legacy()
    if rebuilt_rows is not None:
        set_draft_rows(rebuilt_rows)
        updated_fields.append(f"rows[{len(rebuilt_rows)}]")

    logger.info(
        f"sync_session_to_draft: draft.id={draft.id} "
        f"fields={updated_fields} "
        f"settings_keys={len(settings)} grid_keys={len(grid_settings)} flyer_keys={len(flyer_settings)}"
    )
    return True


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
    import time as _time
    _t0 = _time.perf_counter()
    current = get_draft_project()
    if current is not None and current.id == project_id:
        # すでに正しいプロジェクトがロード済み
        logger.info(
            f"[PERF] ensure_project_loaded SHORT-CIRCUIT id={project_id} "
            f"took {(_time.perf_counter()-_t0)*1000:.1f} ms"
        )
        return True

    # 違うプロジェクトを開いていた / または未ロード
    logger.info(
        f"[PERF] ensure_project_loaded FULL-RELOAD id={project_id} "
        f"(current_id={current.id if current else None}) -> calling reload_project"
    )
    ok = reload_project(project_id)
    logger.info(
        f"[PERF] ensure_project_loaded done id={project_id} "
        f"took {(_time.perf_counter()-_t0)*1000:.0f} ms ok={ok}"
    )
    return ok


def reload_project(project_id: int) -> bool:
    """
    指定プロジェクトを DB から強制再ロードする。
    既存の編集中状態は破棄される。
    """
    import time as _time
    _t0 = _time.perf_counter()
    logger.info(f"[PERF] reload fired id={project_id}")
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
        logger.info(
            f"[PERF] reload_project total took {(_time.perf_counter()-_t0)*1000:.0f} ms "
            f"(id={project_id}, rows={len(rows)})"
        )
        return True
    except Exception as e:
        logger.error(f"reload_project failed: {e}", exc_info=True)
        return False
    finally:
        db.close()


def clear_project_session() -> None:
    """プロジェクトに紐づくセッション項目を一括削除する。"""
    logger.info("[PERF] clear fired")
    for key in SESSION_PROJECT_KEYS:
        if key in st.session_state:
            del st.session_state[key]

    # 動的に作られるキー(プレフィックス一致で消すもの)
    # Phase 2B-1c-①: flyer_ を追加。プロジェクト切替時に旧プロジェクトの
    # flyer_* キーが session_state に残留し、他タブの「設定反映」で
    # apply_draft の merge 書き戻し時に flyer_json を破壊していた。
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
        "flyer_",
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
