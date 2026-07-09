"""
Font(Asset / AssetFile)の read を担うリポジトリ。

流儀は artist_repo / timetable_repo / project_repo に合わせる:
- モジュールレベル関数。db: Session を第 1 引数で受ける。
- repository はセッションを作らない/閉じない(呼び出し側 service が所有)。
- repository は db.commit()/add() を【しない】(純 read)。
- ここで返す ORM は service スコープ内(session open 中)でのみ属性参照される
  想定(view へ escape させない)。font_service.ensure_font_available が
  own_db open 中に image_filename / file_data を読むためだけに使う。

読む対象:
- get_font_asset(db, filename)      -> Asset(assets.image_filename 一致)
- get_font_asset_file(db, filename) -> AssetFile(asset_files.filename 一致)
※ フォント一覧(get_sorted_font_list)/見本画像(create_font_specimen_img)は
  utils の共用 helper が内部で Asset/SystemFontConfig/FavoriteFont を読むため、
  font_service がそれらへ own_db を渡す。この repo は ensure_font_available が
  要求する 2 read のみを提供する(S0-2 確定)。
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from database import Asset, AssetFile


def get_font_asset(db: Session, filename: str) -> Optional[Asset]:
    """assets から image_filename 一致の 1 件(URL 経路 read)。無ければ None。"""
    return (
        db.query(Asset)
        .filter(Asset.image_filename == filename)
        .first()
    )


def get_font_asset_file(db: Session, filename: str) -> Optional[AssetFile]:
    """asset_files から filename 一致の 1 件(binary 経路 read)。無ければ None。"""
    return (
        db.query(AssetFile)
        .filter(AssetFile.filename == filename)
        .first()
    )
