"""
フライヤーテンプレート(flyer_templates)の CRUD ビジネスロジック。

view 層からはこの service を呼び、直接 repository / DB は触らない。
session の生成/クローズと commit/rollback は service が所有する
(artist_service と同じ流儀)。repository は「書くだけ・commit しない」ので、
トランザクション境界(commit/rollback)はすべてここで握る。

★ 画面非依存: streamlit を import しない(将来 API / LINE Bot 化の前提 §11.3)。
  data_json は解釈せず raw 文字列を素通しする(キーの意味は view 側の責務=罠22 別テーブル)。

キャッシュは入れない(罠17: 導入するなら create/update/rename/delete 全経路の
invalidation とセット設計が必要。その判断は Phase 6)。

提供:
- list_templates()                       -> List[TemplateView]  (created_at 降順)
- create_template(name, data_json)       -> bool  (同名が既に存在すれば作成せず False)
- update_template_data(name, data_json)  -> bool  (created_at も now で更新)
- rename_template(template_id, new_name) -> bool
- delete_template(template_id)           -> bool  (物理削除)
"""
from __future__ import annotations

from datetime import datetime
from typing import List

from database import SessionLocal
from models.template import TemplateView
from repositories import template_repo
from utils.logger import get_logger

logger = get_logger(__name__)


def _now() -> str:
    """created_at 用のタイムスタンプ文字列(既存 view と同一形式 "%Y-%m-%d %H:%M:%S")。"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def list_templates() -> List[TemplateView]:
    """全テンプレートを created_at 降順の TemplateView リストで返す。"""
    db = SessionLocal()
    try:
        return template_repo.list_templates(db)
    finally:
        db.close()


def create_template(name: str, data_json: str) -> bool:
    """新規テンプレートを作成する。同名が既に存在すれば作成せず False を返す。"""
    db = SessionLocal()
    try:
        if template_repo.get_by_name(db, name) is not None:
            return False
        template_repo.create(db, name, data_json, _now())
        db.commit()
        return True
    except Exception as e:
        db.rollback()
        logger.error(f"create_template failed: {e}", exc_info=True)
        return False
    finally:
        db.close()


def update_template_data(name: str, data_json: str) -> bool:
    """name 一致テンプレの data_json を上書きし、created_at を now で更新する。

    対象が無ければ False。
    """
    db = SessionLocal()
    try:
        ok = template_repo.update_data(db, name, data_json, _now())
        if not ok:
            db.rollback()
            return False
        db.commit()
        return True
    except Exception as e:
        db.rollback()
        logger.error(f"update_template_data failed: {e}", exc_info=True)
        return False
    finally:
        db.close()


def rename_template(template_id: int, new_name: str) -> bool:
    """id 一致テンプレの name を更新する。対象が無ければ False。"""
    db = SessionLocal()
    try:
        ok = template_repo.rename(db, template_id, new_name)
        if not ok:
            db.rollback()
            return False
        db.commit()
        return True
    except Exception as e:
        db.rollback()
        logger.error(f"rename_template failed: {e}", exc_info=True)
        return False
    finally:
        db.close()


def delete_template(template_id: int) -> bool:
    """id 一致テンプレを物理削除する。対象が無ければ False。"""
    db = SessionLocal()
    try:
        ok = template_repo.delete(db, template_id)
        if not ok:
            db.rollback()
            return False
        db.commit()
        return True
    except Exception as e:
        db.rollback()
        logger.error(f"delete_template failed: {e}", exc_info=True)
        return False
    finally:
        db.close()
