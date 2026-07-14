"""
プロジェクト関連のドラフト型定義。

「ドラフト」というのは、編集中(=未保存かもしれない)の状態を表す中間表現のこと。
DB のレコードそのものではなく、UI で扱いやすい形にした値。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional


@dataclass
class TicketDraft:
    """チケット 1 行のドラフト。"""
    name: str = ""
    price: str = ""
    note: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "TicketDraft":
        if not isinstance(d, dict):
            # 文字列だけが入っているレガシーデータも一応救う
            return cls(name=str(d), price="", note="")
        return cls(
            name=str(d.get("name", "") or ""),
            price=str(d.get("price", "") or ""),
            note=str(d.get("note", "") or ""),
        )

    def to_dict(self) -> dict:
        return {"name": self.name, "price": self.price, "note": self.note}


@dataclass
class FreeTextDraft:
    """自由記述ブロック 1 つのドラフト。"""
    title: str = ""
    content: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "FreeTextDraft":
        if not isinstance(d, dict):
            return cls(title=str(d), content="")
        return cls(
            title=str(d.get("title", "") or ""),
            content=str(d.get("content", "") or ""),
        )

    def to_dict(self) -> dict:
        return {"title": self.title, "content": self.content}


@dataclass
class ProjectDraft:
    """
    プロジェクトのドラフト(編集中の状態)。

    DB の TimetableProject 1 レコードに対応するが、
    JSON カラムは展開済みのオブジェクトとして保持する。
    """
    # --- 基本情報 ---
    id: Optional[int] = None
    title: str = ""
    subtitle: str = ""
    event_date: Optional[date] = None
    venue_name: str = ""
    venue_url: str = ""

    # --- 時間 ---
    open_time: str = "10:00"
    start_time: str = "10:30"
    goods_start_offset: int = 5

    # --- 共通要素 ---
    tickets: List[TicketDraft] = field(default_factory=list)
    ticket_notes: List[str] = field(default_factory=list)
    free_texts: List[FreeTextDraft] = field(default_factory=list)

    # --- フォント/レイアウト設定など(辞書のまま保持) ---
    settings: dict = field(default_factory=dict)
    grid_settings: dict = field(default_factory=dict)
    flyer_settings: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ProjectView:
    """
    読み取り専用のプロジェクト射影(生値ミラー)。

    ProjectDraft(編集用・JSON 展開済み)とは別物。こちらは DB の
    TimetableProject の生カラム値を「そのまま」写した読み取り専用の型で、
    JSON カラムは raw 文字列のまま保持する。消費側(views/flyer.py)が
    自前で json.loads / format_time_str / format_event_date する既存挙動を
    byte 単位で保つのが目的なので、ここでは一切変換・正規化しない
    (event_date も date 化せず str のまま。None もそのまま保持する)。
    """
    id: Optional[int] = None
    title: Optional[str] = None
    subtitle: Optional[str] = None
    event_date: Optional[str] = None
    venue_name: Optional[str] = None
    venue_url: Optional[str] = None
    open_time: Optional[str] = None
    start_time: Optional[str] = None
    tickets_json: Optional[str] = None
    ticket_notes_json: Optional[str] = None
    free_text_json: Optional[str] = None
    flyer_json: Optional[str] = None
    grid_order_json: Optional[str] = None
