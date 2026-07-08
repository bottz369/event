"""
タイムテーブル(行データ)関連のビジネスロジック。

view 層からはこの service を呼び、直接 repository / DB は触らない。
session の生成/クローズは service が所有する(artist_service と同じ流儀)。
load_rows は read only(repo は commit しない)。
"""
from __future__ import annotations

from typing import List

from database import SessionLocal
from models.timetable import TimetableRowDraft
from repositories import timetable_repo


def get_rows_for_project(project_id: int) -> List[TimetableRowDraft]:
    """project_id の行データを DTO リストで返す。

    timetable_rows テーブル優先、無ければ data_json フォールバック
    (load_rows が内部で吸収)。どちらも無ければ空リスト。
    """
    db = SessionLocal()
    try:
        return timetable_repo.load_rows(db, project_id)
    finally:
        db.close()
