"""
プロジェクト関連のビジネスロジック。

view 層からはこの service を呼び、直接 repository / DB は触らない。
"""
from __future__ import annotations

import datetime
from typing import List, Optional, Tuple

# streamlit は Streamlit アプリ / ローカル venv にのみ存在する。Bot 実環境(Railway・
# fastapi のみ / starlette 版数衝突)では import 不能なため optional 化する(database.py と同一方針)。
# ★streamlit がある環境では st は本物のモジュールになり、キャッシュ挙動は従来と完全に同一であること。
try:
    import streamlit as st
except Exception:
    st = None

from database import SessionLocal, TimetableProject
from models import ProjectDraft, ProjectView
from repositories import project_repo, timetable_repo
from utils.logger import get_logger

# session_manager は st.session_state 依存のため、read 経路(list_project_summaries /
# get_project_flyer_view)が streamlit を間接的に引かないよう top-level import しない。
# 使用する write/session 系関数の内部で遅延 import する(§11.7 段階0)。

logger = get_logger(__name__)


def _noop_cache_data(func=None, **_kwargs):
    """st 不在時(Bot 実環境)の @st.cache_data 代替(no-op)。

    関数をそのまま返し、Streamlit 版 API と互換の無害な .clear() を生やす
    (write 系 4 箇所が list_projects_for_selector.clear() を呼ぶため .clear 属性が要る。
     Bot はそれらを呼ばないので実際には走らない)。引数付き `@_cache_data(ttl=...)`
     形式も受ける。
    """
    def _wrap(f):
        f.clear = lambda *a, **k: None
        return f

    if callable(func):
        return _wrap(func)  # @_cache_data(引数なしのデコレータ適用)
    return _wrap            # @_cache_data(...)(引数付き)


# st 有り時は st.cache_data そのもの → @_cache_data は @st.cache_data と同一挙動。
_cache_data = st.cache_data if st is not None else _noop_cache_data


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
    from services import session_manager  # 遅延 import(read 経路を streamlit 非依存に保つ)

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

    # Phase 3 cache-selector: 新規行追加でセレクタ一覧が変わるため無効化。
    list_projects_for_selector.clear()

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
    from services import session_manager  # 遅延 import(read 経路を streamlit 非依存に保つ)

    # Phase 3 cache-selector: sync 前にセレクタ label に出る項目を snapshot。
    # 保存成功時に title/event_date が変化していた場合のみ list_projects_for_selector
    # を invalidate する (TT/Grid/Flyer の保存では label が変わらないので無駄な
    # invalidate を避ける)。except 経路では clear しない。
    before_draft = session_manager.get_draft_project()
    old_title = before_draft.title if before_draft else None
    old_date = before_draft.event_date if before_draft else None

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
        # Phase 3 cache-selector: 保存成功時、title or event_date が変化したときだけ
        # セレクタキャッシュを invalidate。
        if draft.title != old_title or draft.event_date != old_date:
            list_projects_for_selector.clear()
        logger.info(f"save_active_project: saved id={draft.id}, rows={len(rows)}")
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
    from services import session_manager  # 遅延 import(read 経路を streamlit 非依存に保つ)

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

    # Phase 3 cache-selector: 複製で新規行追加 → セレクタ一覧が変わる。
    list_projects_for_selector.clear()

    session_manager.reload_project(new_id)
    return new_id


def delete_project_by_id(project_id: int) -> bool:
    """プロジェクトを削除する。"""
    from services import session_manager  # 遅延 import(read 経路を streamlit 非依存に保つ)

    db = SessionLocal()
    try:
        ok = project_repo.delete_project(db, project_id)
        if ok:
            # Phase 3 cache-selector: 削除でセレクタ一覧が変わる。
            list_projects_for_selector.clear()
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
@_cache_data
def list_projects_for_selector() -> List[Tuple[int, str]]:
    """
    プロジェクト選択 UI 用に、軽量な (id, label) のリストを返す。
    DB アクセスを view から切り離すために用意。

    Phase 3 cache-selector: @st.cache_data でキャッシュ化 (毎 rerun ~460ms の
    固定費削減)。一覧を変える操作の直後に list_projects_for_selector.clear()
    を呼ぶことで明示的に無効化する。仕込み箇所:
      - create_new_project (成功時)
      - duplicate_active_project (成功時)
      - delete_project_by_id (成功時)
      - save_active_project (title/event_date 変化時のみ成功時)
      - views/projects.py:71 直接 db.delete 直後 (孤立経路、将来 services 統一予定)
    """
    db = SessionLocal()
    try:
        projects = project_repo.list_projects(db)
        result = [(p.id, f"{p.event_date or '----'} {p.title}") for p in projects]
        return result
    finally:
        db.close()


def list_project_summaries() -> List[ProjectView]:
    """プロジェクト一覧を ProjectView(読み取り専用 DTO)のリストで返す。

    @st.cache_data 付きの list_projects_for_selector とは別に、Bot / Web API から
    キャッシュ非依存で呼ぶための素の読み窓口(§11.7 段階A0)。ORM を返さず既存の
    to_flyer_view で ProjectView に写して返す(read-only・commit しない)。
    並び順は project_repo.list_projects(日付降順)をそのまま踏襲する。
    """
    db = SessionLocal()
    try:
        return [project_repo.to_flyer_view(p) for p in project_repo.list_projects(db)]
    finally:
        db.close()


def get_project_flyer_view(project_id: int) -> Optional[ProjectView]:
    """
    プロジェクト 1 件の読み取り専用射影(ProjectView)を返す。未検出なら None。

    views/flyer.py の db.query(TimetableProject) 直読みを service 経由へ
    置き換えるための読み窓口。ORM を view に渡さず DTO を返す。
    毎レンダの最新値を返すため、意図的にキャッシュしない(現行の直読みと同挙動)。
    """
    db = SessionLocal()
    try:
        return project_repo.get_project_view(db, project_id)
    finally:
        db.close()
