"""記入テンプレの解析結果からたたき台プロジェクトを作る(段階C C-2a・§52)。

C-1 が読み取った内容(services.event_intake.parse_event_template の data)を、
アプリのプロジェクト 1 件に落とし込む。段階C で初めて本番 DB に書くところ。

★書き込みはアプリ既存の repo 経路のみ:
    repositories.project_repo.create_project / apply_draft
    repositories.timetable_repo.save_rows
  生 INSERT / UPDATE は書かない。DELETE も呼ばない
  (save_rows が行の入れ替えで内部的に消すのは既存の保存仕様そのまま)。

★ streamlit を import しない(罠39)。
  services.project_service.create_new_project は session_manager(= streamlit)を
  引くので Bot からは使えない。よってここは repo を直接使う。

保存先の対応:
    名前 / サブ / 日付 / 会場 / URL / OPEN / START → projects_v4 の各カラム
    チケット                                      → tickets_json   (draft.tickets)
    チケット共通備考                               → ticket_notes_json
    自由記述(件数可変)                           → free_text_json
    出演者(グリッド順)                           → grid_order_json["order"]
    イベント種別                                   → flyer_json["event_type"]
    タイムテーブル行                               → timetable_rows(build_timetable)
"""
from __future__ import annotations

import datetime
from typing import List, Optional

from database import SessionLocal
from models import FreeTextDraft, ProjectDraft, TicketDraft
from repositories import project_repo, timetable_repo
from services.timetable_engine import build_timetable
from utils.logger import get_logger

logger = get_logger(__name__)

# flyer_json に載せるイベント種別のキー(スキーマ変更を避けるため JSON に持つ)
EVENT_TYPE_FLYER_KEY = "event_type"

# 抽出できなかったときの既定。アプリ側の既定(project_repo._format_time_str)と揃える。
DEFAULT_OPEN_TIME = "10:00"
DEFAULT_START_TIME = "10:30"
DEFAULT_TITLE = "(無題)"


def _parse_date(value) -> Optional[datetime.date]:
    """"YYYY-MM-DD" を date にする。読めなければ None。"""
    if not value:
        return None
    try:
        return datetime.datetime.strptime(str(value).strip(), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _price_to_str(price) -> str:
    """TicketDraft.price は表示文字列。

    抽出側(event_intake)が告知文の表記のまま("¥6,000" / "各+¥1,000")返すので、
    ここでは加工しない。None だけ空文字にそろえる。
    ★数値化しないこと: Web のチケット欄は text_input で、そこに入る値が
      そのままフライヤーに出る(通貨記号や「各+」を落とすと表示が変わる)。
    """
    if price is None:
        return ""
    return str(price)


def find_projects_by_event_date(event_date) -> List[dict]:
    """同じ開催日の既存プロジェクトを探す(read only)。

    返り値: [{"id":, "title":, "event_date":}] の新しい順。日付が無ければ空。
    """
    d = _parse_date(event_date)
    if d is None:
        return []
    key = d.strftime("%Y-%m-%d")

    db = SessionLocal()
    try:
        found = [
            {"id": p.id, "title": p.title or "", "event_date": p.event_date}
            for p in project_repo.list_projects(db)
            if (p.event_date or "") == key
        ]
    except Exception as e:
        logger.error("find_projects_by_event_date failed: %s", e, exc_info=True)
        return []
    finally:
        db.close()

    found.sort(key=lambda r: r["id"], reverse=True)
    return found


def build_draft_from_intake(data: dict, event_type=None, project_id=None) -> ProjectDraft:
    """解析結果 → ProjectDraft(純粋な写像。DB に触らない)。

    ★既存プロジェクトを上書きする場合も、ここで作った draft を apply_draft に渡す。
      apply_draft は flyer_json だけ「既存とマージ」するので、フライヤーの見た目
      (フォント・位置・サイズ等 100 キー超)は残り、こちらが持つキー
      (チケット系の値ではなく event_type)だけが上書きされる。
      基本情報 / 自由記述 / グリッド順 / TT 行は総入れ替えになる。
    """
    data = data or {}

    tickets = [
        TicketDraft(
            name=str(t.get("name") or ""),
            price=_price_to_str(t.get("price")),
            note=str(t.get("note") or ""),
        )
        for t in (data.get("tickets") or [])
    ]

    notes = []
    common_note = data.get("ticket_common_note")
    if common_note:
        notes.append(str(common_note))

    free_texts = [
        FreeTextDraft(
            title=str(f.get("title") or ""),
            content=str(f.get("body") or ""),
        )
        for f in (data.get("free_texts") or [])
    ]

    # 出演者はグリッド番号順(テンプレの「1.」が①)。TT 行の並びは別途 build_timetable が逆にする。
    artists = [str(a) for a in (data.get("artists") or []) if str(a).strip()]

    et = event_type or data.get("event_type")

    return ProjectDraft(
        id=project_id,
        title=str(data.get("event_name") or DEFAULT_TITLE),
        subtitle=str(data.get("subtitle") or ""),
        event_date=_parse_date(data.get("event_date")),
        venue_name=str(data.get("venue") or ""),
        venue_url=str(data.get("venue_url") or ""),
        open_time=str(data.get("open_time") or DEFAULT_OPEN_TIME),
        start_time=str(data.get("start_time") or DEFAULT_START_TIME),
        tickets=tickets,
        ticket_notes=notes,
        free_texts=free_texts,
        # settings_json は apply_draft が丸ごと置き換えるので、アプリ既定に合わせて明示する
        settings={"tt_font": "keifont.ttf", "grid_font": "keifont.ttf", "tt_columns": 2},
        grid_settings={"order": artists},
        # flyer_json はマージされる。種別だけ載せ、見た目のキーには触らない。
        flyer_settings=({EVENT_TYPE_FLYER_KEY: et} if et else {}),
    )


def build_rows_from_intake(data: dict):
    """解析結果 → タイムテーブル行(C-3 の純関数に既定値で委譲)。"""
    data = data or {}
    artists = [str(a) for a in (data.get("artists") or []) if str(a).strip()]
    return build_timetable(
        artists,
        open_time=data.get("open_time"),
        start_time=data.get("start_time"),
    )


def create_project_from_intake(parsed: dict, event_type=None,
                               overwrite_project_id=None) -> Optional[int]:
    """解析結果からプロジェクトを作る(または既存を新しい解釈で置き換える)。

    overwrite_project_id を渡すとその既存プロジェクトを置き換える。
    返り値は project_id。失敗は None(例外は投げない)。

    ★DB に触るのは既存 repo 経由だけ。
    ★新規作成のときだけ commit が 2 回になる(create_project が id を採番するため
      自前で commit する)。内容の書き込みが失敗すると中身の無いプロジェクトが
      1 件残りうるので、失敗はログに残して呼び出し側へ None を返す。
      DELETE は使わない方針なので、その掃除は人の判断に委ねる。
    """
    data = (parsed or {}).get("data") if isinstance(parsed, dict) and "data" in parsed \
        else parsed
    if not isinstance(data, dict):
        logger.error("create_project_from_intake: 解析結果が dict ではない")
        return None

    # DB に触る前に、失敗しうる組み立てを先に済ませる(作成後の失敗窓を最小化)
    rows = build_rows_from_intake(data)

    db = SessionLocal()
    try:
        if overwrite_project_id is not None:
            proj = project_repo.get_project(db, int(overwrite_project_id))
            if proj is None:
                logger.error("overwrite target not found: id=%s", overwrite_project_id)
                return None
        else:
            draft_for_create = build_draft_from_intake(data, event_type)
            proj = project_repo.create_project(
                db,
                title=draft_for_create.title,
                event_date=draft_for_create.event_date,
                venue_name=draft_for_create.venue_name,
                venue_url=draft_for_create.venue_url,
                open_time=draft_for_create.open_time,
                start_time=draft_for_create.start_time,
            )

        draft = build_draft_from_intake(data, event_type, project_id=proj.id)
        project_repo.apply_draft(proj, draft)
        db.commit()

        if not timetable_repo.save_rows(db, proj.id, rows):
            logger.error("save_rows failed for project id=%s", proj.id)
            return None

        logger.info(
            "intake project %s: id=%s artists=%d rows=%d",
            "overwritten" if overwrite_project_id is not None else "created",
            proj.id, len(draft.grid_settings.get("order") or []), len(rows),
        )
        return proj.id
    except Exception as e:
        logger.error("create_project_from_intake failed: %s", e, exc_info=True)
        try:
            db.rollback()
        except Exception:
            pass
        return None
    finally:
        db.close()
