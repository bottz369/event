"""
アセット(ロゴ/背景/フォント等)の読み取り用 DTO 定義。

ArtistView と同じ流儀: DB(database.Asset)の内容を view へ渡すための読み取り専用
ビュー。ORM を view に直接渡すことによる DetachedInstanceError を避ける目的で
frozen dataclass に写し替えて返す。

flyer の Asset read(ロゴ/背景の一覧・id 取得)が読む最小集合のみを持つ。
URL 化(get_image_url)は view 側に残すため url は持たない(image_filename まで)。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class AssetView:
    """アセット 1 件の読み取り用ビュー(不変)。"""
    id: int
    image_filename: Optional[str]
    name: Optional[str]
