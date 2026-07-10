"""
Asset(ロゴ/背景/フォント等)の read 用ビジネスロジック。

view 層からはこの service を呼び、直接 repository / DB は触らない。
session の生成/クローズは service が所有する(artist_service / font_service と同流儀)。
read only(repo は commit しない)。read は AssetView(frozen dataclass)で返し ORM を
view に渡さない。

★ 画面非依存: streamlit を import しない(将来 API / LINE Bot 化の前提 §11.3)。
  URL 化(get_image_url)は view 側に残す(案B)。AssetView は image_filename までを持つ。

提供(汎用窓口・今回は flyer だけが使う):
- list_assets_by_type(asset_type) -> List[AssetView]
- get_asset_view(asset_id)        -> Optional[AssetView]
"""
from __future__ import annotations

from typing import List, Optional

from database import SessionLocal
from models.asset import AssetView
from repositories import asset_repo


def _to_view(asset) -> AssetView:
    """ORM Asset を AssetView(id/image_filename/name)に写し替える。"""
    return AssetView(
        id=asset.id,
        image_filename=asset.image_filename,
        name=asset.name,
    )


def list_assets_by_type(asset_type: str) -> List[AssetView]:
    """asset_type 一致 かつ is_deleted==False の一覧を AssetView リストで返す。"""
    db = SessionLocal()
    try:
        return [_to_view(a) for a in asset_repo.list_assets_by_type(db, asset_type)]
    finally:
        db.close()


def get_asset_view(asset_id) -> Optional[AssetView]:
    """id 一致の 1 件を AssetView で返す。無ければ None(旧 .get(id) の Optional 挙動)。"""
    db = SessionLocal()
    try:
        asset = asset_repo.get_asset(db, asset_id)
        return _to_view(asset) if asset else None
    finally:
        db.close()
