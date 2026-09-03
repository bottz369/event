"""
タイムテーブル(行データ)関連のビジネスロジック。

view 層からはこの service を呼び、直接 repository / DB は触らない。
session の生成/クローズは service が所有する(artist_service と同じ流儀)。
load_rows は read only(repo は commit しない)。
"""
from __future__ import annotations

from typing import List

from database import SessionLocal
from models.timetable import TimetableRowDraft, draft_rows_to_df
from repositories import timetable_repo
from utils import calculate_timetable_flow


def get_rows_for_project(project_id: int) -> List[TimetableRowDraft]:
    """project_id の行データを DTO リストで返す。

    timetable_rows テーブル優先、無ければ data_json フォールバック
    (load_rows が内部で吸収)。どちらも無ければ空リスト。
    """
    db = SessionLocal()
    try:
        return timetable_repo.load_rows(db, project_id)
    finally:
        db.close()


def build_tt_gen_list_from_rows(
    rows: List[TimetableRowDraft], open_time: str, start_time: str
) -> List[list]:
    """draft_rows からタイムテーブル画像生成用の gen_list を組み立てる純関数。

    views/timetable.py の「画像生成用リスト (IS_HIDDEN対応)」ブロックの移植。
    出力は `[[TIME_DISPLAY, ARTIST, GOODS_DISPLAY, PLACE], ...]` で、
    logic_timetable.generate_timetable_image の第 1 引数にそのまま渡せる形。

    除外:
      - 先頭の "OPEN / START" 行(calculate_timetable_flow が付ける見出し行)
      - ★IS_HIDDEN(=「タイムテーブル非表示」)が立っている行
        グリッド側の is_grid_hidden とは別のフラグなので混同しないこと
        (グリッドの除外は build_grid_order_from_rows が is_grid_hidden で行う)。

    index 整合の根拠: calculate_timetable_flow は入力 df の 1 行につき必ず 1 行を
    出力する(開演前物販 / 終演後物販 / 通常行の 3 分岐すべてが append + continue)。
    先頭に "OPEN / START" を 1 行足すだけなので、その行を skip してから
    カウンタを進めれば入力行と 1 対 1 で対応する(view の実装と同じ)。

    24 組以上の強制 2 列は logic_timetable 側にも入っているため、ここでは扱わない。
    streamlit に依存しない(API / Bot から呼べる)。
    """
    df = draft_rows_to_df(rows)
    calculated = calculate_timetable_flow(df, open_time, start_time)

    if "IS_HIDDEN" in df.columns:
        hidden_flags = df["IS_HIDDEN"].tolist()
    else:
        hidden_flags = [False] * len(df)

    gen_list: List[list] = []
    row_idx = 0
    for _, row in calculated.iterrows():
        if row["ARTIST"] == "OPEN / START":
            continue

        is_hidden = False
        if row_idx < len(hidden_flags):
            is_hidden = hidden_flags[row_idx]
        row_idx += 1

        if is_hidden:
            continue

        gen_list.append([row["TIME_DISPLAY"], row["ARTIST"], row["GOODS_DISPLAY"], row["PLACE"]])

    return gen_list
