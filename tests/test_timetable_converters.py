"""
Phase 2B-2-a: draft_rows <-> DataFrame 純粋変換のユニットテスト。

pytest があれば pytest test_timetable_converters.py で、
なくても python3 tests/test_timetable_converters.py で回る。
DB / Streamlit 不要。pandas / numpy のみ。
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

# ファイル直接実行時、リポジトリ root をパスに通す
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from models.timetable import (  # noqa: E402
    POST_GOODS_ARTIST_NAME,
    PRE_GOODS_ARTIST_NAME,
    TIMETABLE_DF_COLUMNS,
    TimetableRowDraft,
    df_to_draft_rows,
    draft_rows_to_df,
)


# views/timetable.py:409 の column_order と完全一致確認用 (写経)
_EXPECTED_COLUMNS = [
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


def _make_normal_row(name: str = "Artist A") -> TimetableRowDraft:
    return TimetableRowDraft(
        artist_name=name,
        duration=30,
        adjustment=5,
        is_post_goods=False,
        is_hidden=False,
        goods_start_time="10:30",
        goods_duration=60,
        place="A",
        add_goods_start_time="11:00",
        add_goods_duration=30,
        add_goods_place="B",
    )


def _make_pre_goods_row() -> TimetableRowDraft:
    return TimetableRowDraft(
        artist_name=PRE_GOODS_ARTIST_NAME,
        duration=0,
        adjustment=0,
        is_post_goods=False,
        is_hidden=False,
        goods_start_time="10:00",
        goods_duration=30,
        place="",
    )


def _make_post_goods_row() -> TimetableRowDraft:
    return TimetableRowDraft(
        artist_name=POST_GOODS_ARTIST_NAME,
        duration=0,
        adjustment=0,
        is_post_goods=False,
        is_hidden=False,
        goods_start_time="20:00",
        goods_duration=60,
        place="",
    )


# ---------- a. 通常行 N 行 round-trip ----------
def test_roundtrip_normal_rows():
    rows = [_make_normal_row(f"A{i}") for i in range(3)]
    rows[1].is_post_goods = True
    rows[2].is_hidden = True

    df = draft_rows_to_df(rows)
    assert list(df.columns) == _EXPECTED_COLUMNS, df.columns.tolist()
    assert len(df) == 3

    rebuilt = df_to_draft_rows(df)
    assert len(rebuilt) == 3
    for src, dst in zip(rows, rebuilt):
        assert src == dst, (src, dst)


# ---------- b. 空リスト ----------
def test_empty_list_roundtrip():
    df = draft_rows_to_df([])
    assert list(df.columns) == _EXPECTED_COLUMNS
    assert len(df) == 0
    rebuilt = df_to_draft_rows(df)
    assert rebuilt == []


# ---------- c. 1 行のみ ----------
def test_single_row():
    rows = [_make_normal_row("Solo")]
    df = draft_rows_to_df(rows)
    assert len(df) == 1
    rebuilt = df_to_draft_rows(df)
    assert rebuilt == rows


# ---------- d. 開演前物販を先頭 ----------
def test_pre_goods_first():
    rows = [_make_pre_goods_row(), _make_normal_row("A"), _make_normal_row("B")]
    df = draft_rows_to_df(rows)
    assert df.iloc[0]["ARTIST"] == PRE_GOODS_ARTIST_NAME
    rebuilt = df_to_draft_rows(df)
    assert rebuilt == rows


# ---------- e. 終演後物販を末尾 ----------
def test_post_goods_last():
    rows = [_make_normal_row("A"), _make_normal_row("B"), _make_post_goods_row()]
    df = draft_rows_to_df(rows)
    assert df.iloc[-1]["ARTIST"] == POST_GOODS_ARTIST_NAME
    rebuilt = df_to_draft_rows(df)
    assert rebuilt == rows


# ---------- f. 開演前 + 終演後 両方 ----------
def test_pre_and_post_goods():
    rows = [_make_pre_goods_row(), _make_normal_row("A"), _make_post_goods_row()]
    df = draft_rows_to_df(rows)
    assert df.iloc[0]["ARTIST"] == PRE_GOODS_ARTIST_NAME
    assert df.iloc[-1]["ARTIST"] == POST_GOODS_ARTIST_NAME
    rebuilt = df_to_draft_rows(df)
    assert rebuilt == rows


# ---------- g. add_goods_duration=None ----------
def test_add_goods_duration_none_roundtrip():
    row = _make_normal_row("A")
    row.add_goods_duration = None
    rows = [row]
    df = draft_rows_to_df(rows)
    rebuilt = df_to_draft_rows(df)
    assert rebuilt[0].add_goods_duration is None


# ---------- h. 型保持 ----------
def test_types_preserved():
    rows = [_make_normal_row("A")]
    df = draft_rows_to_df(rows)
    rebuilt = df_to_draft_rows(df)
    r = rebuilt[0]
    # bool が int 化されないことを厳密にチェック
    assert isinstance(r.is_hidden, bool)
    assert isinstance(r.is_post_goods, bool)
    # int が float のまま戻らないことを厳密にチェック
    assert isinstance(r.duration, int) and not isinstance(r.duration, bool)
    assert isinstance(r.adjustment, int) and not isinstance(r.adjustment, bool)
    assert isinstance(r.goods_duration, int) and not isinstance(r.goods_duration, bool)
    assert isinstance(r.add_goods_duration, int)
    assert isinstance(r.artist_name, str)
    assert isinstance(r.goods_start_time, str)
    assert isinstance(r.place, str)


# ---------- i. data_editor 通過後を模した dtype 揺れ ----------
def test_dtype_drift_recovery():
    """
    pandas / data_editor 経由で起きがちな dtype 揺れを再現:
    - bool 列が numpy.bool_ や 0/1 で来る
    - int 列が float64 で来る (NaN 混入時に起きる)
    - 欠損が NaN
    """
    df = pd.DataFrame(
        [
            {
                "IS_HIDDEN": np.bool_(False),
                "ARTIST": "X",
                "DURATION": 25.0,
                "IS_POST_GOODS": 1,
                "ADJUSTMENT": np.int64(5),
                "GOODS_START_MANUAL": "10:30",
                "GOODS_DURATION": 60.0,
                "PLACE": "A",
                "ADD_GOODS_START": "",
                "ADD_GOODS_DURATION": float("nan"),
                "ADD_GOODS_PLACE": "",
            },
            {
                "IS_HIDDEN": 0,
                "ARTIST": "Y",
                "DURATION": float("nan"),
                "IS_POST_GOODS": np.bool_(True),
                "ADJUSTMENT": 0,
                "GOODS_START_MANUAL": float("nan"),
                "GOODS_DURATION": 30.0,
                "PLACE": float("nan"),
                "ADD_GOODS_START": float("nan"),
                "ADD_GOODS_DURATION": float("nan"),
                "ADD_GOODS_PLACE": float("nan"),
            },
        ],
        columns=_EXPECTED_COLUMNS,
    )

    rebuilt = df_to_draft_rows(df)
    assert len(rebuilt) == 2

    r0 = rebuilt[0]
    assert r0.is_hidden is False
    assert r0.artist_name == "X"
    assert r0.duration == 25 and isinstance(r0.duration, int) and not isinstance(r0.duration, bool)
    assert r0.is_post_goods is True
    assert r0.adjustment == 5 and isinstance(r0.adjustment, int)
    assert r0.goods_start_time == "10:30"
    assert r0.goods_duration == 60 and isinstance(r0.goods_duration, int)
    assert r0.place == "A"
    assert r0.add_goods_start_time == ""
    assert r0.add_goods_duration is None  # NaN → None
    assert r0.add_goods_place == ""

    r1 = rebuilt[1]
    assert r1.is_hidden is False  # 0 → False
    assert r1.artist_name == "Y"
    assert r1.duration == 20  # NaN → default 20
    assert r1.is_post_goods is True
    assert r1.goods_start_time == ""  # NaN → ""
    assert r1.place == ""
    assert r1.add_goods_duration is None


# ---------- 写経一致確認 ----------
def test_columns_match_views_timetable():
    """TIMETABLE_DF_COLUMNS が views/timetable.py:409 の写経と完全一致。"""
    assert TIMETABLE_DF_COLUMNS == _EXPECTED_COLUMNS


_TESTS = [
    test_roundtrip_normal_rows,
    test_empty_list_roundtrip,
    test_single_row,
    test_pre_goods_first,
    test_post_goods_last,
    test_pre_and_post_goods,
    test_add_goods_duration_none_roundtrip,
    test_types_preserved,
    test_dtype_drift_recovery,
    test_columns_match_views_timetable,
]


if __name__ == "__main__":
    failed = 0
    for t in _TESTS:
        name = t.__name__
        try:
            t()
            print(f"PASS  {name}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {name}: {e}")
        except Exception as e:
            failed += 1
            print(f"ERROR {name}: {type(e).__name__}: {e}")
    print()
    print(f"=== {len(_TESTS) - failed} / {len(_TESTS)} passed ===")
    sys.exit(0 if failed == 0 else 1)
