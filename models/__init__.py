"""
データモデル(dataclass)を集約するパッケージ。

役割:
- DB と Session State の間に立つ「型のしっかりした中間表現」
- 各 view はこの型を介してデータをやり取りする
"""
from models.project import (
    ProjectDraft,
    ProjectView,
    TicketDraft,
    FreeTextDraft,
)
from models.timetable import (
    TimetableRowDraft,
    PRE_GOODS_ARTIST_NAME,
    POST_GOODS_ARTIST_NAME,
)

__all__ = [
    "ProjectDraft",
    "ProjectView",
    "TicketDraft",
    "FreeTextDraft",
    "TimetableRowDraft",
    "PRE_GOODS_ARTIST_NAME",
    "POST_GOODS_ARTIST_NAME",
]
