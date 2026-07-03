"""
アーティスト関連の読み取り用 DTO 定義。

ProjectDraft 等の「編集中ドラフト」とは異なり、ArtistView は
DB(database.Artist)の内容を view へ渡すための読み取り専用ビュー。
artists は session_state 往復がほぼ無いため編集用 draft は作らず、
ORM を view に直接渡すことによる DetachedInstanceError を避ける目的で
frozen dataclass に写し替えて返す。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ArtistView:
    """アーティスト 1 件の読み取り用ビュー(不変)。"""
    id: int
    name: str
    image_filename: Optional[str]
    crop_scale: float
    crop_x: int
    crop_y: int
