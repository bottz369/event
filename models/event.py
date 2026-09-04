"""イベント選択用の読み取り専用 DTO(段階B B-3)。

LINE のクイックリプライで「〇〇が出演する直近イベント」を提示するために使う。
ORM を bot 層へ escape させないための薄い射影。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional


@dataclass(frozen=True)
class EventOption:
    """イベント選択ボタン 1 個ぶんの情報。

    event_date は None(日付未設定のプロジェクト)もありうる。
    """
    project_id: int
    title: str
    event_date: Optional[date] = None
