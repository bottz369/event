"""イベント検索(段階B B-3)。

LINE Bot から「〇〇が出演する直近イベント」をクイックリプライで提示するための read service。

★ 画面非依存: streamlit を import しない(罠39 / §42 の read 経路非依存化を踏襲)。
★ 3層規律: bot → services → repositories。DB セッションはこの層で開閉し、DTO を返す。
read only(commit しない)。
"""
from __future__ import annotations

import datetime
from typing import List, Optional, Tuple

from database import SessionLocal
from models.event import EventOption
from repositories import project_repo, timetable_repo
from utils.logger import get_logger

logger = get_logger(__name__)

# アーティスト絞り込みありのときの既定件数(§48)
DEFAULT_LIMIT = 4

# ボタン一覧 1 ページの件数(B-3.1)。
# LINE の quick reply は items <= 13。「12 件 + ページングボタン 1 = 13」に収める。
PAGE_SIZE = 12

# 出演者一覧から除く行(アー写を持たない運用行)。logic_timetable.SKIP_NAMES と同集合。
_NON_ARTIST_ROW_NAMES = frozenset({"OPEN / START", "開演前物販", "終演後物販"})


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

    return _sort_recent_first(options, today)[:limit]


def _sort_recent_first(
    options: List[EventOption], today: datetime.date
) -> List[EventOption]:
    """「これから優先」の並びに揃える(§48 と B-3.1 で共用)。

      1. 今日以降を event_date 昇順(近い順)
      2. 続けて過去を event_date 降順(新しい順)
      3. 日付未設定は最後
    """
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
    return upcoming + past


# ---------------------------------------------------------
# B-3.1: 完全ボタン対話用(絞り込みなし列挙 + ページング)
# ---------------------------------------------------------
def list_recent_events(
    limit: int = PAGE_SIZE,
    page: int = 0,
    today: Optional[datetime.date] = None,
) -> Tuple[List[EventOption], bool]:
    """全プロジェクトを「これから優先」で並べ、page 番目のスライスと次ページ有無を返す。

    戻り値: (そのページの EventOption リスト, has_more)

    並びは list_recent_events_for_artist と同じ _sort_recent_first(§48 の合意仕様)。
    ※ projects_v4 に is_deleted は無く削除は物理削除なので、テーブルに残っている
      = 生きているプロジェクト。
    today は注入可能(テストの決定性)。
    """
    if limit <= 0:
        return ([], False)
    page = max(0, int(page or 0))
    today = today or datetime.date.today()

    db = SessionLocal()
    try:
        options = [
            EventOption(
                project_id=p.id,
                title=p.title or "(無題)",
                event_date=_parse_event_date(p.event_date),
            )
            for p in project_repo.list_projects(db)
        ]
    finally:
        db.close()

    ordered = _sort_recent_first(options, today)
    start = page * limit
    chunk = ordered[start:start + limit]
    has_more = len(ordered) > start + limit
    return (chunk, has_more)


def list_event_artists(
    project_id: int, limit: int = PAGE_SIZE, page: int = 0
) -> Tuple[List[str], bool]:
    """そのイベントの出演アーティスト名を **タイムテーブル順のまま** ページングして返す。

    戻り値: (そのページの名前リスト, has_more)

    除外: OPEN / START・開演前物販・終演後物販(アー写を持たない運用行)と空名。
    重複名は最初の 1 件だけ残す(順序は保つ)。
    ※ 「タイムテーブル非表示」「アー写グリッド非表示」は**除外しない**。
      差し替え対象として選びたいことがあるため(表示フラグと差し替え可否は別物)。
    """
    if limit <= 0:
        return ([], False)
    page = max(0, int(page or 0))

    db = SessionLocal()
    try:
        rows = timetable_repo.load_rows(db, project_id)
    finally:
        db.close()

    names: List[str] = []
    seen = set()
    for r in rows:
        name = (r.artist_name or "").strip()
        if not name or name in _NON_ARTIST_ROW_NAMES or name in seen:
            continue
        seen.add(name)
        names.append(name)

    start = page * limit
    chunk = names[start:start + limit]
    has_more = len(names) > start + limit
    return (chunk, has_more)
