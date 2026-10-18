"""
Asset(ロゴ/背景/フォント等)の一覧取得と明示的な画像アップロード。

view 層からはこの service を呼び、直接 repository / DB は触らない。
session の生成/クローズは service が所有する(artist_service / font_service と同流儀)。
read は AssetView(frozen dataclass)で返し ORM を
view に渡さない。

★ 画面非依存: streamlit を import しない(将来 API / LINE Bot 化の前提 §11.3)。
  URL 化(get_image_url)は view 側に残す(案B)。AssetView は image_filename までを持つ。

提供(汎用窓口・今回は flyer だけが使う):
- list_assets_by_type(asset_type) -> List[AssetView]
- get_asset_view(asset_id)        -> Optional[AssetView]
- upload_image_asset(...)        -> AssetView(明示保存時のみ画像・DBに登録)
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


IMAGE_UPLOAD_LIMIT = 20 * 1024 * 1024


def upload_image_asset(data: bytes, original_name: str, asset_type: str, name: str = "") -> AssetView:
    """Persist an explicitly submitted background/logo, never on widget rerender."""
    import io
    from pathlib import Path
    from uuid import uuid4
    import warnings
    from PIL import Image, UnidentifiedImageError
    from database import upload_image_to_supabase

    if asset_type not in ("background", "logo"):
        raise ValueError("背景またはロゴを選択してください。")
    if not data or len(data) > IMAGE_UPLOAD_LIMIT:
        raise ValueError("画像は20MB以下のファイルを選択してください。")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                extension = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}.get(image.format)
                if extension is None:
                    raise ValueError("PNG・JPEG・WebPの画像を選択してください。")
                image.verify()
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError,
            Image.DecompressionBombWarning) as exc:
        raise ValueError("画像を開けませんでした。PNG・JPEG・WebPの画像を選択してください。") from exc
    filename = f"asset_{uuid4().hex}{extension}"
    if not upload_image_to_supabase(io.BytesIO(data), filename):
        raise ValueError("画像を保存できませんでした。時間をおいて再度お試しください。")
    db = SessionLocal()
    try:
        asset = asset_repo.add_image_asset(db, name.strip() or Path(original_name).stem or "画像素材",
                                            asset_type, filename)
        result = _to_view(asset)
        db.commit()
        return result
    except Exception as exc:
        db.rollback()
        raise ValueError("アセットの登録に失敗しました。再度お試しください。") from exc
    finally:
        db.close()
