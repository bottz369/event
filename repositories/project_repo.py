"""
TimetableProject の CRUD を担うリポジトリ。

DB スキーマには触らない方針なので、既存の TimetableProject ORM をそのまま使う。
"""
from __future__ import annotations

import datetime
import json
from typing import List, Optional

from sqlalchemy.orm import Session

from database import TimetableProject
from models import (
    PRE_GOODS_ARTIST_NAME,
    POST_GOODS_ARTIST_NAME,
    FreeTextDraft,
    ProjectDraft,
    TicketDraft,
    TimetableRowDraft,
)
from utils.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------
# JSON ヘルパー
# ---------------------------------------------------------
def _parse_json(raw, default):
    """安全な JSON パース。失敗したら warning を出して default を返す。"""
    if raw is None:
        return default
    if isinstance(raw, (list, dict)):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception as e:
            logger.warning(f"JSON parse failed: {e}", exc_info=True)
            return default
    return default


def _parse_date(v) -> Optional[datetime.date]:
    if v is None or v == "":
        return None
    if isinstance(v, datetime.date) and not isinstance(v, datetime.datetime):
        return v
    if isinstance(v, datetime.datetime):
        return v.date()
    try:
        return datetime.datetime.strptime(str(v), "%Y-%m-%d").date()
    except Exception:
        logger.warning(f"Cannot parse event_date: {v!r}")
        return None


def _format_time_str(t_val, default: str = "10:00") -> str:
    if t_val is None or t_val == "":
        return default
    if isinstance(t_val, str):
        return t_val[:5] if len(t_val) >= 5 else t_val
    if isinstance(t_val, (datetime.time, datetime.datetime)):
        return t_val.strftime("%H:%M")
    return default


# ---------------------------------------------------------
# クエリ系
# ---------------------------------------------------------
def list_projects(db: Session) -> List[TimetableProject]:
    """全プロジェクトを日付降順で返す。"""
    projects = db.query(TimetableProject).all()
    projects.sort(key=lambda x: x.event_date or "0000-00-00", reverse=True)
    return projects


def get_project(db: Session, project_id: int) -> Optional[TimetableProject]:
    """ID 指定で 1 件取得。"""
    if project_id is None:
        return None
    return db.query(TimetableProject).filter(TimetableProject.id == project_id).first()


# ---------------------------------------------------------
# ORM <-> Draft 変換
# ---------------------------------------------------------
def to_draft(proj: TimetableProject) -> ProjectDraft:
    """
    DB の ORM オブジェクトから ProjectDraft を生成する。
    JSON カラムは展開して dataclass / dict として保持する。
    """
    tickets_raw = _parse_json(proj.tickets_json, [])
    if not isinstance(tickets_raw, list):
        tickets_raw = []

    notes_raw = _parse_json(getattr(proj, "ticket_notes_json", None), [])
    if not isinstance(notes_raw, list):
        notes_raw = []
    # 文字列だけのリストに正規化
    notes_clean: List[str] = []
    for n in notes_raw:
        if n is None:
            continue
        notes_clean.append(str(n))

    free_raw = _parse_json(proj.free_text_json, [])
    if not isinstance(free_raw, list):
        free_raw = []

    settings = _parse_json(proj.settings_json, {})
    if not isinstance(settings, dict):
        settings = {}

    grid_settings = _parse_json(proj.grid_order_json, {})
    # 旧仕様で配列だったケースも吸収
    if isinstance(grid_settings, list):
        grid_settings = {"order": grid_settings}
    elif not isinstance(grid_settings, dict):
        grid_settings = {}

    flyer_settings = _parse_json(proj.flyer_json, {})
    if not isinstance(flyer_settings, dict):
        flyer_settings = {}

    return ProjectDraft(
        id=proj.id,
        title=proj.title or "",
        subtitle=getattr(proj, "subtitle", "") or "",
        event_date=_parse_date(proj.event_date),
        venue_name=proj.venue_name or "",
        venue_url=proj.venue_url or "",
        open_time=_format_time_str(proj.open_time, "10:00"),
        start_time=_format_time_str(proj.start_time, "10:30"),
        goods_start_offset=int(proj.goods_start_offset) if proj.goods_start_offset is not None else 5,
        tickets=[TicketDraft.from_dict(t) for t in tickets_raw],
        ticket_notes=notes_clean,
        free_texts=[FreeTextDraft.from_dict(f) for f in free_raw],
        settings=settings,
        grid_settings=grid_settings,
        flyer_settings=flyer_settings,
    )


def _build_legacy_data_json_from_rows(rows: List[TimetableRowDraft]) -> List[dict]:
    """
    draft_rows を logic_project.save_current_project() と同じ形式の
    list of dicts に変換して返す(大文字キー)。

    フェーズ2B 中の過渡期、grid.py / overview.py / flyer_helpers.py 等の
    フォールバック読み込みが古い data_json を参照し続けるのを防ぐため、
    apply_draft() で同時書き出しする。
    フェーズ4 で data_json 廃止時に本関数ごと削除予定。
    """
    result: List[dict] = []
    for r in rows:
        d = r.to_legacy_dict()
        if r.artist_name in (PRE_GOODS_ARTIST_NAME, POST_GOODS_ARTIST_NAME):
            # legacy 仕様: 開演前/終演後物販の特殊行は特定フィールドを強制リセット
            # (logic_project.save_current_project と完全一致させる)
            d["DURATION"] = 0
            d["ADJUSTMENT"] = 0
            d["IS_POST_GOODS"] = False
            d["PLACE"] = ""
            d["ADD_GOODS_START"] = ""
            d["ADD_GOODS_DURATION"] = None
            d["ADD_GOODS_PLACE"] = ""
        result.append(d)
    return result


def apply_draft(
    proj: TimetableProject,
    draft: ProjectDraft,
    rows: Optional[List[TimetableRowDraft]] = None,
) -> None:
    """
    Draft の内容を ORM オブジェクトに反映する(commit はしない)。
    DB スキーマには手を入れない方針なので、JSON カラムへの書き戻しはここで行う。

    rows を渡すと、過渡期互換のため projects_v4.data_json も同時書き出しする
    (grid.py / overview.py / flyer_helpers.py のフォールバック経路のため、
     フェーズ4 で削除予定)。
    rows=None の場合は data_json には触らない(既存値を保持)。

    flyer_json は既存 JSON と draft.flyer_settings をマージする
    (init_s 由来の動的キーが消失するのを防ぐ)。
    """
    proj.title = draft.title
    if hasattr(proj, "subtitle"):
        proj.subtitle = draft.subtitle
    proj.event_date = draft.event_date.strftime("%Y-%m-%d") if draft.event_date else None
    proj.venue_name = draft.venue_name
    proj.venue_url = draft.venue_url
    proj.open_time = draft.open_time
    proj.start_time = draft.start_time
    proj.goods_start_offset = draft.goods_start_offset

    proj.tickets_json = json.dumps([t.to_dict() for t in draft.tickets], ensure_ascii=False)
    proj.ticket_notes_json = json.dumps(list(draft.ticket_notes), ensure_ascii=False)
    proj.free_text_json = json.dumps([f.to_dict() for f in draft.free_texts], ensure_ascii=False)
    proj.settings_json = json.dumps(draft.settings, ensure_ascii=False)
    proj.grid_order_json = json.dumps(draft.grid_settings, ensure_ascii=False)

    # --- flyer_json: 既存値と draft.flyer_settings をマージ ---
    # 全消し上書きすると init_s 由来の動的キー(flyer_grid_scale_w 等 30+ 個)が
    # 失われるため、既存 JSON を読んでから draft の値で update する。
    existing_flyer: dict = {}
    if proj.flyer_json:
        try:
            parsed = json.loads(proj.flyer_json)
            if isinstance(parsed, dict):
                existing_flyer = parsed
        except json.JSONDecodeError as e:
            logger.warning(
                f"apply_draft: flyer_json parse failed for project {proj.id}, "
                f"treating as empty: {e}"
            )
    merged_flyer = dict(existing_flyer)
    merged_flyer.update(draft.flyer_settings or {})
    proj.flyer_json = json.dumps(merged_flyer, ensure_ascii=False)

    # --- data_json: 過渡期の互換書き出し(rows が渡されたときのみ) ---
    if rows is not None:
        data_payload = _build_legacy_data_json_from_rows(rows)
        proj.data_json = json.dumps(data_payload, ensure_ascii=False)
        logger.debug(
            f"apply_draft: wrote data_json with {len(data_payload)} rows, "
            f"flyer_json keys={len(merged_flyer)}"
        )
    else:
        logger.debug(
            f"apply_draft: data_json untouched (rows=None), "
            f"flyer_json keys={len(merged_flyer)}"
        )


# ---------------------------------------------------------
# 書き込み系
# ---------------------------------------------------------
def create_project(
    db: Session,
    title: str,
    event_date: Optional[datetime.date],
    venue_name: str,
    venue_url: str = "",
    open_time: str = "10:00",
    start_time: str = "10:30",
) -> TimetableProject:
    """新規プロジェクト作成。"""
    new_proj = TimetableProject(
        title=title,
        event_date=event_date.strftime("%Y-%m-%d") if event_date else None,
        venue_name=venue_name,
        venue_url=venue_url,
        open_time=open_time,
        start_time=start_time,
    )
    db.add(new_proj)
    db.commit()
    db.refresh(new_proj)
    logger.info(f"Created project id={new_proj.id} title={title!r}")
    return new_proj


def update_project_from_draft(
    db: Session,
    draft: ProjectDraft,
    rows: Optional[List[TimetableRowDraft]] = None,
) -> bool:
    """
    Draft の内容で既存プロジェクトを更新。
    rows を渡すと apply_draft が data_json も同時書き出しする(過渡期互換)。
    """
    if draft.id is None:
        logger.error("update_project_from_draft: draft.id is None")
        return False
    proj = get_project(db, draft.id)
    if not proj:
        logger.error(f"update_project_from_draft: project not found id={draft.id}")
        return False
    apply_draft(proj, draft, rows=rows)
    db.commit()
    logger.info(f"Updated project id={draft.id}")
    return True


def duplicate_project(db: Session, project_id: int) -> Optional[TimetableProject]:
    """既存プロジェクトを複製。行データの複製は呼び出し側で行うこと。"""
    src = get_project(db, project_id)
    if not src:
        logger.warning(f"duplicate_project: source not found id={project_id}")
        return None

    new_proj = TimetableProject(
        title=f"{src.title} (コピー)",
        subtitle=getattr(src, "subtitle", None),
        event_date=src.event_date,
        venue_name=src.venue_name,
        venue_url=src.venue_url,
        open_time=src.open_time,
        start_time=src.start_time,
        goods_start_offset=src.goods_start_offset,
        data_json=src.data_json,
        grid_order_json=src.grid_order_json,
        tickets_json=src.tickets_json,
        free_text_json=src.free_text_json,
        ticket_notes_json=src.ticket_notes_json,
        flyer_json=src.flyer_json,
        settings_json=src.settings_json,
    )
    db.add(new_proj)
    db.commit()
    db.refresh(new_proj)
    logger.info(f"Duplicated project: src={project_id} -> new={new_proj.id}")
    return new_proj


def delete_project(db: Session, project_id: int) -> bool:
    """プロジェクト削除(cascade で行も消える)。"""
    proj = get_project(db, project_id)
    if not proj:
        return False
    db.delete(proj)
    db.commit()
    logger.info(f"Deleted project id={project_id}")
    return True
