"""
Asset(assets テーブル)の read を担うリポジトリ。

流儀は artist_repo / font_repo に合わせる:
- モジュールレベル関数。db: Session を第 1 引数で受ける。
- repository はセッションを作らない/閉じない(呼び出し側 service が所有)。
- repository は db.commit()/add() を【しない】(純 read)。
- ここで返す ORM は service スコープ内(session open 中)でのみ属性参照される
  想定(view へ escape させない)。asset_service が own_db open 中に
  id/image_filename/name を AssetView に写し替える。

読む対象(汎用窓口・flyer 以外にも将来流用可):
- list_assets_by_type(db, asset_type) -> List[Asset](type 一致 + is_deleted==False)
- get_asset(db, asset_id)             -> Asset(id 直引き・is_deleted フィルタ無し)
※ font 用の image_filename 一致 read は font_repo.get_font_asset に既存(温存)。
"""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy.orm import Session

from database import Asset


def list_assets_by_type(db: Session, asset_type: str) -> List[Asset]:
    """asset_type 一致 かつ is_deleted==False の一覧(旧 flyer L77/L78 と同条件)。"""
    return (
        db.query(Asset)
        .filter(Asset.asset_type == asset_type, Asset.is_deleted == False)
        .all()
    )


def get_asset(db: Session, asset_id) -> Optional[Asset]:
    """id 直引き 1 件(旧 flyer L565/L570 の .get(id) と同挙動・is_deleted フィルタ無し)。無ければ None。"""
    return db.query(Asset).get(asset_id)
