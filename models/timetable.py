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

    # UI 専用・非永続: 一括削除の「削除」チェック。
    # DB(timetable_rows)に対応カラムは持たない = スキーマ変更なし。
    # timetable_repo._draft_to_row は書き出さず、_row_to_draft は常に False で復元する。
    # ★ session_state に別持ちせず draft_rows に載せる理由: views/timetable.py の
    #   「先取り確定」(_apply_editor_state_to_df の `if col in new_df.columns` ガード)は
    #   draft_rows_to_df が出す列しか通さないため、別持ちすると毎 run チェックが捨てられる(罠33)。
    is_delete_marked: bool = False

    # UI 専用・非永続: アー写グリッドの表示順(昇順で左上から詰める)。
    # DB(timetable_rows)に対応カラムは持たない = スキーマ変更なし。
    # 永続化先は projects_v4.grid_order_json["order"](名前リスト)で、
    # 「🔄 設定反映」の保存直前に build_grid_order_from_rows が名前列へ変換する。
    # ★ is_delete_marked と違い grid_no は「保存される並び順」を左右するため、
    #   session_manager._rows_to_comparable に含める(番号を変えたら未保存扱いにし、
    #   保存し忘れで黙って失われないようにする)。
    grid_no: Optional[int] = None

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
            # DELETE を持たない旧 dict (data_json fallback / CSV 取込) は False。
            is_delete_marked=bool(d.get("DELETE") or d.get("is_delete_marked") or False),
            # GRID_NO は None と 0 を区別する必要があるため、他フィールドのような
            # truthiness 連鎖 (`A or B`) ではなく明示的な None 判定で拾う。
            # 列を持たない旧 dict (data_json fallback / CSV 取込) は None。
            grid_no=_to_int_or_none(
                d.get("GRID_NO") if d.get("GRID_NO") is not None else d.get("grid_no")
            ),
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
            # UI 専用列。DB へは書き出されず、draft_rows_to_df 経由で
            # data_editor に渡すためだけに存在する(models の is_delete_marked)。
            "DELETE": self.is_delete_marked,
            "ARTIST": self.artist_name,
            # UI 専用列。DB へは書き出されず、保存時に
            # build_grid_order_from_rows で grid_order_json["order"] へ畳まれる。
            "GRID_NO": self.grid_no,
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
# views/timetable.py の data_editor 列と完全一致(同順 13 列)。
# UI 専用・DB 非永続の列が 2 つある:
#   "DELETE"  … 一括削除チェック (is_delete_marked)
#   "GRID_NO" … アー写グリッド表示順 (grid_no)。保存時に grid_order_json["order"] へ畳む。
# 将来 views 側がこの定数を import して重複解消する想定 (今フェーズでは views 無変更)。
TIMETABLE_DF_COLUMNS: list[str] = [
    "DELETE",
    "IS_HIDDEN",
    "ARTIST",
    "GRID_NO",
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


def seed_grid_no_from_order(rows: list["TimetableRowDraft"], order: list) -> None:
    """保存済み grid_order["order"] における位置から各行の grid_no を復元する。

    grid_no は timetable_rows に持たない(非永続)ため、プロジェクトを読み込んだ
    直後は必ず None になる。そのままだと「番号列を足したら初期表示のグリッド並びが
    変わってしまう」ので、既存 order 内の位置 + 1 を番号として与えて見た目を保つ。
    order に無い行は None のまま(= 末尾へ回る)。

    ★ 呼び出しは session_manager.reload_project() の _save_snapshot() より前。
      後で呼ぶと、プロジェクトを開いただけで has_unsaved_changes() が True になり
      誤警告が出る(grid_no は _rows_to_comparable に含まれるため)。
    既に番号が入っている行は上書きしない(ユーザー入力が正)。rows を破壊的に更新する。
    """
    pos: dict[str, int] = {}
    for i, name in enumerate(order or []):
        clean = (name or "").strip() if isinstance(name, str) else ""
        if clean and clean not in pos:
            pos[clean] = i + 1
    if not pos:
        return
    for r in (rows or []):
        if r.grid_no is not None or r.is_special_row:
            continue
        r.grid_no = pos.get((r.artist_name or "").strip())


def build_grid_order_from_rows(rows: list["TimetableRowDraft"]) -> list[str]:
    """draft_rows から アー写グリッドの order(名前リスト)を組み立てる純関数。

    ★ grid_order_json["order"] は「アーティスト名の list」という契約で、消費者が
      views/grid.py / views/flyer.py / views/overview.py /
      services/generation_service.py / bot/api.py / project_repo.reassign_grid_orders
      と多岐にわたる。よって返すのは必ず名前の list[str](契約を変えない)。

    除外(views/grid.py の従来フィルタと同じ意味):
      - 特殊行(開演前物販 / 終演後物販): アー写を持たない
      - is_hidden 行: 画像生成から外す指定
      - 名前が空 / 空白のみの行(strip して判定)

    並び:
      - grid_no の昇順で左上から詰める。
      - 未入力(None)は末尾へ回し、その中では TT の出演順を保つ
        (除外にはしない。番号の振り忘れで人が黙って消えるのを避けるため)。
      - grid_no が重複したら TT の出演順(行 index)でタイブレークする。
      - 同名が複数行あるときは先に現れた方だけ残す(grid は名前で画像を引くので
        同名を 2 度並べても同じ画像が 2 枚出るだけ)。

    ★ 仕様変更(合意済み): rows(= TT)だけを見て組むので、TT にいない登録
      アーティストは order から落ちる。TT を並び順の唯一の正とするための意図的な挙動。

    streamlit / DB に非依存の純関数(scratch で機械検証できる形に保つこと)。
    """
    indexed: list[tuple[bool, int, int, str]] = []
    for i, r in enumerate(rows or []):
        if r.is_special_row or r.is_hidden:
            continue
        name = (r.artist_name or "").strip()
        if not name:
            continue
        # None と int を直接比較できないので、(未入力か, 番号, 行index) の
        # 3 段キーにする。sorted は安定だが行 index を明示して決定性を担保する。
        no_input = r.grid_no is None
        indexed.append((no_input, 0 if no_input else int(r.grid_no), i, name))

    indexed.sort(key=lambda t: (t[0], t[1], t[2]))
    return list(dict.fromkeys(name for _, _, _, name in indexed))


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
    "DELETE": "is_delete_marked",
    "ARTIST": "artist_name",
    "GRID_NO": "grid_no",
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
