"""
プロジェクト関連のビジネスロジック。

view 層からはこの service を呼び、直接 repository / DB は触らない。
"""
from __future__ import annotations

import datetime
from typing import Optional

from database import SessionLocal, TimetableProject
from models import ProjectDraft
from repositories import project_repo, timetable_repo
from services import session_manager
from utils.logger import get_logger

logger = get_logger(__name__)


def create_new_project(
    title: str,
    event_date: Optional[datetime.date],
    venue_name: str,
    venue_url: str = "",
) -> Optional[int]:
    """
    新規プロジェクトを作成し、その ID を返す。
    作成後はそのプロジェクトを active にセットしてセッションへロード済みにする。
    """
    db = SessionLocal()
    try:
        proj = project_repo.create_project(
            db,
            title=title,
            event_date=event_date,
            venue_name=venue_name,
            venue_url=venue_url,
        )
        new_id = proj.id
    except Exception as e:
        logger.error(f"create_new_project failed: {e}", exc_info=True)
        return None
    finally:
        db.close()

    # 新規プロジェクトをロード(セッションをクリアして読み直す)
    session_manager.reload_project(new_id)
    return new_id


def save_active_project() -> bool:
    """
    session_state にあるドラフトを DB に書き出す。
    成功したら mark_saved を呼んで未保存判定をリセットする。

    保存直前に sync_session_to_draft() を呼んで、widget で編集された
    session_state の生キーを draft に書き戻す。これにより view 層は
    本関数を呼ぶだけで「画面入力が DB に反映される」状態になる。

    戻り値:
        True: 成功
        False: 失敗(または対象なし)
    """
    import time as _time
    _t0 = _time.perf_counter()
    # widget で編集された session_state の値を draft に同期(★Phase 2B-1a で追加)
    session_manager.sync_session_to_draft()

    draft = session_manager.get_draft_project()
    rows = session_manager.get_draft_rows()

    if draft is None or draft.id is None:
        logger.warning("save_active_project: no active draft")
        return False

    db = SessionLocal()
    try:
        # rows を渡すと、apply_draft 内で過渡期互換のため data_json も同時書き出しされる
        ok_proj = project_repo.update_project_from_draft(db, draft, rows=rows)
        if not ok_proj:
            return False

        ok_rows = timetable_repo.save_rows(db, draft.id, rows)
        if not ok_rows:
            return False

        session_manager.mark_saved()
        logger.info(f"save_active_project: saved id={draft.id}, rows={len(rows)}")
        logger.info(
            f"[PERF] save_active_project total took {(_time.perf_counter()-_t0)*1000:.0f} ms "
            f"(id={draft.id}, rows={len(rows)})"
        )
        return True
    except Exception as e:
        logger.error(f"save_active_project failed: {e}", exc_info=True)
        return False
    finally:
        db.close()


def duplicate_active_project() -> Optional[int]:
    """
    現在 active なプロジェクトを複製する。
    複製後は新しい方を active にして読み直す。
    """
    draft = session_manager.get_draft_project()
    if draft is None or draft.id is None:
        logger.warning("duplicate_active_project: no active project")
        return None

    # 複製前に現在の編集状態を保存(複製は DB ベースで行うため)
    if not save_active_project():
        logger.warning("duplicate_active_project: save_active_project failed before duplicate")
        # 保存失敗でも複製は試みる(既に保存済みの状態で複製される)

    db = SessionLocal()
    try:
        new_proj = project_repo.duplicate_project(db, draft.id)
        if not new_proj:
            return None
        # 行データもコピー
        timetable_repo.copy_rows(db, draft.id, new_proj.id)
        new_id = new_proj.id
    except Exception as e:
        logger.error(f"duplicate_active_project failed: {e}", exc_info=True)
        return None
    finally:
        db.close()

    session_manager.reload_project(new_id)
    return new_id


def delete_project_by_id(project_id: int) -> bool:
    """プロジェクトを削除する。"""
    db = SessionLocal()
    try:
        ok = project_repo.delete_project(db, project_id)
        if ok:
            # active を消した場合はセッションもクリア
            if session_manager.get_active_project_id() == project_id:
                session_manager.clear_project_session()
                session_manager.set_active_project_id(None)
        return ok
    finally:
        db.close()


# ---------------------------------------------------------
# 一覧取得(view から軽く呼ぶ用)
# ---------------------------------------------------------
def list_projects_for_selector():
    """
    プロジェクト選択 UI 用に、軽量な (id, label) のリストを返す。
    DB アクセスを view から切り離すために用意。
    """
    import time as _time
    _t0 = _time.perf_counter()
    db = SessionLocal()
    try:
        projects = project_repo.list_projects(db)
        result = [(p.id, f"{p.event_date or '----'} {p.title}") for p in projects]
        logger.info(
            f"[PERF] list_projects_for_selector took {(_time.perf_counter()-_t0)*1000:.0f} ms "
            f"(rows={len(result)})"
        )
        return result
    finally:
        db.close()
