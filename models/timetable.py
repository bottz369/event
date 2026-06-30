"""
タイムテーブル行のドラフト型定義。

旧コードでは tt_artists_order / tt_row_settings / tt_artist_settings /
binding_df の4つに分散していたが、ここでは TimetableRowDraft のリスト
1 つで完結する。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import pandas as pd


# 開演前/終演後物販を表す特殊なアーティスト名(既存仕様を維持)
PRE_GOODS_ARTIST_NAME = "開演前物販"
POST_GOODS_ARTIST_NAME = "終演後物販"


@dataclass
class TimetableRowDraft:
    """
    タイムテーブル 1 行分のドラフト。

    DB の TimetableRow と 1 対 1 対応。
    画面では、開演前物販 / アーティスト行 / 終演後物販 すべてをこの型で表現する。
    sort_order はリスト内インデックスで決まるためフィールドには持たない。
    """
    artist_name: str = ""
    duration: int = 20            # 出演時間(分)
    adjustment: int = 0            # 転換時間(分)
    is_post_goods: bool = False    # 「終演後物販」扱いするか
    is_hidden: bool = False        # 画像生成時に非表示にするか

    # 物販(メイン)
    goods_start_time: str = ""
    goods_duration: int = 60
    place: str = ""

    # 物販(追加・並行物販)
    add_goods_start_time: str = ""
    add_goods_duration: Optional[int] = None
    add_goods_place: str = ""

    # ----- 判定ヘルパー -----
    @property
    def is_pre_goods_row(self) -> bool:
        return self.artist_name == PRE_GOODS_ARTIST_NAME

    @property
    def is_post_goods_row(self) -> bool:
        return self.artist_name == POST_GOODS_ARTIST_NAME

    @property
    def is_special_row(self) -> bool:
        """物販専用行(開演前/終演後)かどうか。アーティスト一覧から除外する判定に使う。"""
        return self.is_pre_goods_row or self.is_post_goods_row

    # ----- dict との相互変換(JSON 互換のため当面残す) -----
    @classmethod
    def from_dict(cls, d: dict) -> "TimetableRowDraft":
        """
        旧 data_json / load_timetable_rows の戻り値辞書からドラフトを作る。
        utils.safe_int / safe_str に頼っていた箇所も内側で吸収。
        """
        def _to_int(v, default=0):
            try:
                if v is None:
                    return default
                s = str(v).strip()
                if s == "" or s.lower() in ("nan", "none"):
                    return default
                return int(float(s))
            except Exception:
                return default

        def _to_int_or_none(v):
            r = _to_int(v, default=None) if v is not None else None
            # _to_int は default を返してしまうので個別ハンドリング
            try:
                if v is None or v == "" or str(v).lower() in ("nan", "none"):
                    return None
                return int(float(v))
            except Exception:
                return None

        def _to_str(v):
            if v is None:
                return ""
            s = str(v)
            return "" if s.lower() == "nan" else s

        return cls(
            artist_name=_to_str(d.get("ARTIST") or d.get("artist_name")),
            duration=_to_int(d.get("DURATION") or d.get("duration"), 20),
            adjustment=_to_int(d.get("ADJUSTMENT") or d.get("adjustment"), 0),
            is_post_goods=bool(d.get("IS_POST_GOODS") or d.get("is_post_goods") or False),
            is_hidden=bool(d.get("IS_HIDDEN") or d.get("is_hidden") or False),
            goods_start_time=_to_str(d.get("GOODS_START_MANUAL") or d.get("goods_start_time")),
            goods_duration=_to_int(d.get("GOODS_DURATION") or d.get("goods_duration"), 60),
            place=_to_str(d.get("PLACE") or d.get("place")),
            add_goods_start_time=_to_str(d.get("ADD_GOODS_START") or d.get("add_goods_start_time")),
            add_goods_duration=_to_int_or_none(d.get("ADD_GOODS_DURATION") or d.get("add_goods_duration")),
            add_goods_place=_to_str(d.get("ADD_GOODS_PLACE") or d.get("add_goods_place")),
        )

    def to_legacy_dict(self) -> dict:
        """
        既存コードが期待する大文字キーの辞書として書き出す。
        新コードへの移行中、画像生成ロジックなどがまだ大文字キーを期待しているので、
        その互換のために用意する。
        """
        return {
            "ARTIST": self.artist_name,
            "DURATION": self.duration,
            "IS_POST_GOODS": self.is_post_goods,
            "ADJUSTMENT": self.adjustment,
            "GOODS_START_MANUAL": self.goods_start_time,
            "GOODS_DURATION": self.goods_duration,
            "PLACE": self.place,
            "ADD_GOODS_START": self.add_goods_start_time,
            "ADD_GOODS_DURATION": self.add_goods_duration,
            "ADD_GOODS_PLACE": self.add_goods_place,
            "IS_HIDDEN": self.is_hidden,
        }


# ============================================================
# Phase 2B-2-a: draft_rows <-> DataFrame 純粋変換
# ============================================================
# views/timetable.py:409 の column_order と完全一致(同順 11 列)。
# 将来 views 側がこの定数を import して重複解消する想定 (今フェーズでは views 無変更)。
TIMETABLE_DF_COLUMNS: list[str] = [
    "IS_HIDDEN",
    "ARTIST",
    "DURATION",
    "IS_POST_GOODS",
    "ADJUSTMENT",
    "GOODS_START_MANUAL",
    "GOODS_DURATION",
    "PLACE",
    "ADD_GOODS_START",
    "ADD_GOODS_DURATION",
    "ADD_GOODS_PLACE",
]


def draft_rows_to_df(rows: list["TimetableRowDraft"]) -> pd.DataFrame:
    """
    draft_rows を st.data_editor 入力用 DataFrame に変換する。
    既存 to_legacy_dict() を流用し、TIMETABLE_DF_COLUMNS で列順を固定する。
    特殊行(開演前物販 / 終演後物販)もビジネスロジックを混ぜず純粋に field 写像する。
    空リスト → 列名 11 列・行 0 の空 DataFrame。
    """
    records = [r.to_legacy_dict() for r in (rows or [])]
    return pd.DataFrame(records, columns=TIMETABLE_DF_COLUMNS)


def _normalize_cell(v):
    """
    pandas / st.data_editor 経由の値を Python ネイティブ型に正規化する。
    - float('nan') → None (bool/int 復元時の NaN 罠を避ける)
    - numpy.bool_ / numpy.int64 / numpy.float64 → bool / int / float (item() 経由)
    その他はそのまま返す。
    """
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    if not isinstance(v, str) and hasattr(v, "item"):
        try:
            return v.item()
        except Exception:
            pass
    return v


# 大文字キー → snake_case の写像。from_dict は両方を試すが
# 「`d.get("DURATION") or d.get("duration")`」の truthiness 評価で
# DURATION=0 が消える既存挙動があるため、ここで snake_case 単一キーに正規化して
# from_dict に渡し、第一項が None、第二項に 0 等の正値が入る形にする。
_DF_KEY_TO_DRAFT_KEY = {
    "ARTIST": "artist_name",
    "DURATION": "duration",
    "IS_POST_GOODS": "is_post_goods",
    "ADJUSTMENT": "adjustment",
    "GOODS_START_MANUAL": "goods_start_time",
    "GOODS_DURATION": "goods_duration",
    "PLACE": "place",
    "ADD_GOODS_START": "add_goods_start_time",
    "ADD_GOODS_DURATION": "add_goods_duration",
    "ADD_GOODS_PLACE": "add_goods_place",
    "IS_HIDDEN": "is_hidden",
}


def df_to_draft_rows(df: pd.DataFrame) -> list["TimetableRowDraft"]:
    """
    st.data_editor から戻った DataFrame を draft_rows に逆変換する。
    既存 from_dict() を流用。data_editor 由来の dtype 揺れ
    (NaN / numpy scalar / float 化した int) は _normalize_cell で吸収する。
    None / NaN セル → from_dict の各ヘルパーがデフォルト値にフォールバック。
    """
    if df is None or df.empty:
        return []
    rows: list[TimetableRowDraft] = []
    for record in df.to_dict(orient="records"):
        normalized = {
            _DF_KEY_TO_DRAFT_KEY.get(k, k): _normalize_cell(v)
            for k, v in record.items()
        }
        rows.append(TimetableRowDraft.from_dict(normalized))
    return rows
