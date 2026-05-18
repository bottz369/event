"""
TimetableRow の CRUD を担うリポジトリ。

このアプリの SSOT (Single Source of Truth) は
timetable_rows テーブル + ProjectDraft (DB 由来) と定める。
旧 projects_v4.data_json は移行期間中の読み込み専用フォールバックとしてのみ扱う。
"""
from __future__ import annotations

import json
from typing import List

from sqlalchemy.orm import Session

from database import TimetableRow, TimetableProject
from models import TimetableRowDraft
from utils.logger import get_logger

logger = get_logger(__name__)


def load_rows(db: Session, project_id: int) -> List[TimetableRowDraft]:
    """
    指定プロジェクトの行データをドラフトのリストとして返す。

    優先順位:
      1. timetable_rows テーブル(正)
      2. projects_v4.data_json (旧データのフォールバック・読み込みのみ)

    どちらも無ければ空リスト。
    """
    if project_id is None:
        return []

    try:
        rows = (
            db.query(TimetableRow)
            .filter(TimetableRow.project_id == project_id)
            .order_by(TimetableRow.sort_order)
            .all()
        )
    except Exception as e:
        logger.error(f"load_rows: timetable_rows query failed: {e}", exc_info=True)
        rows = []

    if rows:
        return [_row_to_draft(r) for r in rows]

    # フォールバック: 旧 data_json から読み込む(読み込みのみ・保存しない)
    proj = db.query(TimetableProject).filter(TimetableProject.id == project_id).first()
    if proj and proj.data_json:
        try:
            data = json.loads(proj.data_json)
            if isinstance(data, list):
                logger.info(
                    f"load_rows: timetable_rows empty for project {project_id}, "
                    f"falling back to legacy data_json ({len(data)} items)"
                )
                return [TimetableRowDraft.from_dict(d) for d in data if isinstance(d, dict)]
        except Exception as e:
            logger.warning(f"load_rows: legacy data_json parse failed: {e}", exc_info=True)

    return []


def save_rows(db: Session, project_id: int, drafts: List[TimetableRowDraft]) -> bool:
    """
    指定プロジェクトの行データを置き換える(全削除→挿入)。
    """
    if project_id is None:
        logger.error("save_rows: project_id is None")
        return False

    try:
        db.query(TimetableRow).filter(TimetableRow.project_id == project_id).delete()
        new_rows = [_draft_to_row(project_id, idx, d) for idx, d in enumerate(drafts)]
        db.add_all(new_rows)
        db.commit()
        logger.info(f"save_rows: project={project_id}, count={len(new_rows)}")
        return True
    except Exception as e:
        logger.error(f"save_rows failed: {e}", exc_info=True)
        db.rollback()
        return False


def copy_rows(db: Session, src_project_id: int, dest_project_id: int) -> bool:
    """src の行データを dest にコピーする(複製機能で使う)。"""
    drafts = load_rows(db, src_project_id)
    return save_rows(db, dest_project_id, drafts)


# ---------------------------------------------------------
# 変換
# ---------------------------------------------------------
def _row_to_draft(r: TimetableRow) -> TimetableRowDraft:
    return TimetableRowDraft(
        artist_name=r.artist_name or "",
        duration=int(r.duration or 0),
        adjustment=int(r.adjustment or 0),
        is_post_goods=bool(r.is_post_goods),
        is_hidden=bool(getattr(r, "is_hidden", False)),
        goods_start_time=r.goods_start_time or "",
        goods_duration=int(r.goods_duration or 60),
        place=r.place or "",
        add_goods_start_time=r.add_goods_start_time or "",
        add_goods_duration=(int(r.add_goods_duration) if r.add_goods_duration is not None else None),
        add_goods_place=r.add_goods_place or "",
    )


def _draft_to_row(project_id: int, sort_order: int, d: TimetableRowDraft) -> TimetableRow:
    return TimetableRow(
        project_id=project_id,
        sort_order=sort_order,
        artist_name=d.artist_name,
        duration=int(d.duration or 0),
        is_post_goods=bool(d.is_post_goods),
        adjustment=int(d.adjustment or 0),
        goods_start_time=d.goods_start_time,
        goods_duration=int(d.goods_duration or 60),
        place=d.place,
        add_goods_start_time=d.add_goods_start_time,
        add_goods_duration=d.add_goods_duration,
        add_goods_place=d.add_goods_place,
        is_hidden=bool(d.is_hidden),
    )
