"""
FlyerTemplate(flyer_templates)の CRUD リポジトリ。

- DB スキーマには触らない(既存 FlyerTemplate ORM をそのまま使う)。
- repository は db.commit() を【しない】。commit / rollback 境界は service が握る
  (artist_repo / asset_repo と同じ 3 層規律)。
- read は ORM を返さず TemplateView(frozen DTO)で返す。
- data_json は解釈しない(raw 文字列を素通し)。
- FlyerTemplate に is_deleted 列は無いため delete は物理削除(現行 template.py 挙動を維持)。
"""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy.orm import Session

from database import FlyerTemplate
from models.template import TemplateView
from utils.logger import get_logger

logger = get_logger(__name__)


def _to_view(tmpl: FlyerTemplate) -> TemplateView:
    """ORM FlyerTemplate を TemplateView(id/name/data_json/created_at)に写し替える。"""
    return TemplateView(
        id=tmpl.id,
        name=tmpl.name,
        data_json=tmpl.data_json,
        created_at=tmpl.created_at,
    )


def list_templates(db: Session) -> List[TemplateView]:
    """全テンプレートを created_at 降順で返す(既存 flyer/template ページと同順)。"""
    tmpls = (
        db.query(FlyerTemplate)
        .order_by(FlyerTemplate.created_at.desc())
        .all()
    )
    return [_to_view(t) for t in tmpls]


def get_by_name(db: Session, name: str) -> Optional[TemplateView]:
    """name 一致の 1 件を返す。無ければ None。"""
    tmpl = db.query(FlyerTemplate).filter(FlyerTemplate.name == name).first()
    return _to_view(tmpl) if tmpl else None


def create(db: Session, name: str, data_json: str, created_at: str) -> TemplateView:
    """新規テンプレートを追加する(commit はしない)。

    id を確定させるため db.flush() までは行う(artist_repo.create_artist と同流儀)。
    """
    tmpl = FlyerTemplate(name=name, data_json=data_json, created_at=created_at)
    db.add(tmpl)
    db.flush()  # id 採番のため。commit は service。
    logger.info(f"template_repo.create: added name={name!r} id={tmpl.id}")
    return _to_view(tmpl)


def update_data(db: Session, name: str, data_json: str, created_at: str) -> bool:
    """name 一致テンプレの data_json / created_at を上書きする(commit はしない)。

    対象が無ければ False、成功したら True。
    """
    tmpl = db.query(FlyerTemplate).filter(FlyerTemplate.name == name).first()
    if tmpl is None:
        return False
    tmpl.data_json = data_json
    tmpl.created_at = created_at
    logger.info(f"template_repo.update_data: name={name!r}")
    return True


def rename(db: Session, template_id: int, new_name: str) -> bool:
    """id 一致テンプレの name を更新する(commit はしない)。

    対象が無ければ False、成功したら True。
    """
    tmpl = db.query(FlyerTemplate).filter(FlyerTemplate.id == template_id).first()
    if tmpl is None:
        return False
    tmpl.name = new_name
    logger.info(f"template_repo.rename: id={template_id} name={new_name!r}")
    return True


def delete(db: Session, template_id: int) -> bool:
    """id 一致テンプレを物理削除する(commit はしない)。

    対象が無ければ False、成功したら True。
    """
    tmpl = db.query(FlyerTemplate).filter(FlyerTemplate.id == template_id).first()
    if tmpl is None:
        return False
    db.delete(tmpl)
    logger.info(f"template_repo.delete: id={template_id}")
    return True
