"""イベント検索(段階B B-3)。

LINE Bot から「〇〇が出演する直近イベント」をクイックリプライで提示するための read service。

★ 画面非依存: streamlit を import しない(罠39 / §42 の read 経路非依存化を踏襲)。
★ 3層規律: bot → services → repositories。DB セッションはこの層で開閉し、DTO を返す。
read only(commit しない)。
"""
from __future__ import annotations

import datetime
from typing import List, Optional

from database import SessionLocal
from models.event import EventOption
from repositories import timetable_repo
from utils.logger import get_logger

logger = get_logger(__name__)

# クイックリプライで出す既定の件数(LINE の items 上限 13 より十分小さい)
DEFAULT_LIMIT = 4


def _parse_event_date(v) -> Optional[datetime.date]:
    """projects_v4.event_date("YYYY-MM-DD" 文字列想定)を date へ。壊れていれば None。"""
    if v is None or v == "":
        return None
    if isinstance(v, datetime.datetime):
        return v.date()
    if isinstance(v, datetime.date):
        return v
    try:
        return datetime.datetime.strptime(str(v), "%Y-%m-%d").date()
    except Exception:
        logger.warning("cannot parse event_date: %r", v)
        return None


def list_recent_events_for_artist(
    name: str,
    limit: int = DEFAULT_LIMIT,
    today: Optional[datetime.date] = None,
) -> List[EventOption]:
    """name が出演する「直近イベント」を最大 limit 件返す。

    並び(合意済み仕様):
      1. **これから優先** — 今日以降を event_date の昇順(近い順)
      2. 足りなければ **過去を event_date の降順**(新しい順)で補完
      3. 日付未設定のプロジェクトは最後(過去枠の末尾)

    「出演」判定は timetable_repo.find_projects_by_artist_name(完全一致 → ilike)。
    today は注入可能(テストの決定性のため。PendingStore の now 注入と同思想)。
    該当なしは空リスト。
    """
    if not name:
        return []
    if limit <= 0:
        return []

    today = today or datetime.date.today()

    db = SessionLocal()
    try:
        rows = timetable_repo.find_projects_by_artist_name(db, name)
    finally:
        db.close()

    options = [
        EventOption(
            project_id=pid,
            title=title or "(無題)",
            event_date=_parse_event_date(event_date),
        )
        for (pid, title, event_date) in rows
    ]

    upcoming = sorted(
        (o for o in options if o.event_date is not None and o.event_date >= today),
        key=lambda o: (o.event_date, o.project_id),
    )
    past = sorted(
        (o for o in options if not (o.event_date is not None and o.event_date >= today)),
        # 日付ありを新しい順 → 日付なしを最後に
        key=lambda o: (o.event_date is not None, o.event_date or datetime.date.min, o.project_id),
        reverse=True,
    )

    return (upcoming + past)[:limit]
