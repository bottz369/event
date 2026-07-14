"""
フライヤーテンプレート(flyer_templates)の読み取り用 DTO 定義。

ArtistView / AssetView と同じ流儀: DB(database.FlyerTemplate)の内容を view へ
渡すための読み取り専用ビュー。ORM を view に直接渡すことによる
DetachedInstanceError を避けるため frozen dataclass に写し替えて返す。

data_json は中身を解釈せず raw 文字列のまま保持する(キーの意味は view 側の
FLYER_KEY_REGISTRY / gather_flyer_settings_from_session が扱う=罠22 の
projects_v4.flyer_json とは別テーブル・別責務)。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class TemplateView:
    """フライヤーテンプレート 1 件の読み取り用ビュー(不変)。"""
    id: int
    name: Optional[str]
    data_json: Optional[str]
    created_at: Optional[str]
