"""services/timetable_engine.build_timetable の単体テスト(段階C C-3・§52)。

純関数なので DB も LLM も実 API も不要。streamlit も引かない。

★検証はアプリ本体の utils.calculate_timetable_flow を通して行う。
  エンジンは duration / adjustment / goods_start_time を組むだけで、出番の時刻は
  アプリ側が積み上げて導出するため、自前の算術を突き合わせても「アプリでどう見えるか」
  の証明にはならない。実際の表示計算に食わせて初めてゴールデンを固定できる。
"""
from __future__ import annotations

import pytest

from models.timetable import draft_rows_to_df
from services.timetable_engine import build_timetable
from utils import calculate_timetable_flow

# ゴールデン受入の入力(グリッド番号 1〜7 の順)
GOLDEN_ARTISTS = [
    "アルテミスの翼",             # 1
    "Luna moon",                  # 2
    "ワンダーウィード天",         # 3
    "花いろは",                   # 4
    "One last bloom",             # 5
    "シークレットシャノワール",   # 6
    "リルリボン",                 # 7
]

# 期待する TT(出演順)。(出番, 名前, 物販, 場所)
GOLDEN_EXPECTED = [
    ("10:30 - 10:45", "リルリボン", "10:50 - 11:50", "A"),
    ("10:45 - 11:00", "シークレットシャノワール", "11:05 - 12:05", "B"),
    ("11:00 - 11:15", "One last bloom", "11:20 - 12:20", "C"),
    ("11:15 - 11:30", "花いろは", "11:35 - 12:35", "D"),
    ("11:30 - 11:45", "ワンダーウィード天", "11:50 - 12:50", "E"),
    ("11:45 - 12:00", "Luna moon", "12:05 - 13:05", "A"),
    # ここに転換 12:00-12:05(Luna moon の adjustment=5 として表現される)
    ("12:05 - 12:20", "アルテミスの翼", "12:25 - 13:25", "B"),
]


def _schedule(rows, open_time=None, start_time="10:30"):
    """エンジンの行をアプリの表示計算に通し、(出番, 名前, 物販, 場所) にする。"""
    calc = calculate_timetable_flow(draft_rows_to_df(rows), open_time, start_time)
    out = []
    for _, r in calc.iterrows():
        if r["ARTIST"] == "OPEN / START":
            continue
        out.append((r["TIME_DISPLAY"], r["ARTIST"], r["GOODS_DISPLAY"], r["PLACE"]))
    return out


# ---------------------------------------------------------------------------
# ゴールデン受入
# ---------------------------------------------------------------------------
def test_golden_acceptance():
    """§52 の検算済みゴールデンを厳密に再現する。"""
    rows = build_timetable(
        GOLDEN_ARTISTS,
        start_time="10:30",
        set_minutes=15,
        changeover_every_n=6,
        changeover_minutes=5,
        goods_offset_minutes=5,
        goods_duration_minutes=60,
        goods_spaces=("A", "B", "C", "D", "E"),
    )
    assert _schedule(rows) == GOLDEN_EXPECTED


def test_golden_changeover_is_on_the_sixth_row():
    """転換は「6 組目の後ろ」= 6 行目の adjustment として表現される。"""
    rows = build_timetable(GOLDEN_ARTISTS, start_time="10:30", changeover_every_n=6,
                           changeover_minutes=5)
    adjustments = [r.adjustment for r in rows]
    assert adjustments == [0, 0, 0, 0, 0, 5, 0], (
        "転換の位置が違う。adjustment は『その行のあとのすき間』"
    )


def test_golden_with_open_time_prepends_open_start_row():
    """OPEN/START 行はエンジンではなくアプリ側が合成する(二重に作らない)。"""
    rows = build_timetable(GOLDEN_ARTISTS, open_time="10:00", start_time="10:30",
                           changeover_every_n=6)
    assert all(r.artist_name != "OPEN / START" for r in rows)

    calc = calculate_timetable_flow(draft_rows_to_df(rows), "10:00", "10:30")
    first = calc.iloc[0]
    assert first["ARTIST"] == "OPEN / START"
    assert first["TIME_DISPLAY"] == "10:00 - 10:30"
    # 出番は START から始まる
    assert calc.iloc[1]["TIME_DISPLAY"].startswith("10:30")


# ---------------------------------------------------------------------------
# 出順(グリッド番号の逆)
# ---------------------------------------------------------------------------
def test_order_is_reverse_of_grid_number():
    rows = build_timetable(["1番", "2番", "3番"], start_time="10:00")
    assert [r.artist_name for r in rows] == ["3番", "2番", "1番"]


def test_grid_no_restores_the_original_grid_order():
    """出演順は逆でも grid_no は元のグリッド番号を保つ(§43 の並び順 SSOT)。"""
    rows = build_timetable(["1番", "2番", "3番"], start_time="10:00")
    assert [r.grid_no for r in rows] == [3, 2, 1]
    # grid_no 昇順に並べ直すと入力どおりのグリッド順に戻る
    by_grid = sorted(rows, key=lambda r: r.grid_no)
    assert [r.artist_name for r in by_grid] == ["1番", "2番", "3番"]


# ---------------------------------------------------------------------------
# 転換の挿入位置
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "count,every_n,expected",
    [
        (7, 6, [0, 0, 0, 0, 0, 5, 0]),      # ゴールデンと同条件
        (10, 5, [0, 0, 0, 0, 5, 0, 0, 0, 0, 0]),   # 10 組目は最後なので付けない
        (11, 5, [0, 0, 0, 0, 5, 0, 0, 0, 0, 5, 0]),
        (3, 5, [0, 0, 0]),                  # 組数が every_n 未満
        (5, 5, [0, 0, 0, 0, 0]),            # ちょうど 5 組 = 5 組目が最後
    ],
)
def test_changeover_positions(count, every_n, expected):
    rows = build_timetable(
        ["a%d" % i for i in range(count)], start_time="10:00",
        changeover_every_n=every_n, changeover_minutes=5)
    assert [r.adjustment for r in rows] == expected


def test_no_changeover_when_every_n_is_zero_or_negative():
    for every_n in (0, -1, None):
        rows = build_timetable(["a", "b", "c", "d", "e", "f"], start_time="10:00",
                               changeover_every_n=every_n, changeover_minutes=5)
        assert all(r.adjustment == 0 for r in rows), f"every_n={every_n}"


def test_changeover_shifts_following_start_times():
    """転換の分だけ後続の出番が後ろへずれる。"""
    rows = build_timetable(["a", "b", "c", "d"], start_time="10:00",
                           set_minutes=15, changeover_every_n=2, changeover_minutes=10)
    times = [t for t, _n, _g, _p in _schedule(rows, start_time="10:00")]
    # d,c(転換10分)b,a
    assert times == ["10:00 - 10:15", "10:15 - 10:30",
                     "10:40 - 10:55", "10:55 - 11:10"]


# ---------------------------------------------------------------------------
# 物販場所の循環
# ---------------------------------------------------------------------------
def test_goods_places_cycle_over_artist_rows_only():
    """A〜E は出演者行だけで数えて循環する(転換は行ではないので数に入らない)。"""
    rows = build_timetable(["a%d" % i for i in range(12)], start_time="10:00",
                           changeover_every_n=3, changeover_minutes=5)
    assert [r.place for r in rows] == list("ABCDEABCDEAB")


def test_goods_places_cycle_beyond_space_count():
    rows = build_timetable(["a%d" % i for i in range(7)], start_time="10:00",
                           goods_spaces=("A", "B"))
    assert [r.place for r in rows] == ["A", "B", "A", "B", "A", "B", "A"]


def test_empty_goods_spaces_leaves_place_blank():
    rows = build_timetable(["a", "b"], start_time="10:00", goods_spaces=())
    assert [r.place for r in rows] == ["", ""]


def test_goods_window_follows_each_set():
    """物販 = 出番終了 + offset から duration 分。"""
    rows = build_timetable(["a", "b"], start_time="10:00", set_minutes=20,
                           goods_offset_minutes=10, goods_duration_minutes=45)
    assert [r.goods_start_time for r in rows] == ["10:30", "10:50"]
    assert [r.goods_duration for r in rows] == [45, 45]
    sched = _schedule(rows, start_time="10:00")
    assert sched[0][2] == "10:30 - 11:15"
    assert sched[1][2] == "10:50 - 11:35"


# ---------------------------------------------------------------------------
# エッジケース
# ---------------------------------------------------------------------------
def test_no_artists_returns_empty():
    assert build_timetable([], start_time="10:00") == []
    assert build_timetable(None, start_time="10:00") == []


@pytest.mark.parametrize("start", [None, "", "未定", "あとで", "25:99"])
def test_unknown_start_time_still_builds_rows(start):
    """開始時刻が読めなくても行は作る(たたき台が丸ごと消えないように)。

    時刻計算だけを諦め、物販開始は空にする。
    """
    rows = build_timetable(["a", "b", "c"], start_time=start,
                           changeover_every_n=2, changeover_minutes=5)
    assert [r.artist_name for r in rows] == ["c", "b", "a"]
    assert [r.goods_start_time for r in rows] == ["", "", ""]
    # 時刻以外(尺・転換・場所・グリッド番号)は通常どおり組まれている
    assert [r.duration for r in rows] == [15, 15, 15]
    assert [r.adjustment for r in rows] == [0, 5, 0]
    assert [r.place for r in rows] == ["A", "B", "C"]
    assert [r.grid_no for r in rows] == [3, 2, 1]


def test_single_artist():
    rows = build_timetable(["ひとり"], start_time="10:00", changeover_every_n=1)
    assert len(rows) == 1
    assert rows[0].adjustment == 0, "最後の出演者に転換は付けない"
    assert _schedule(rows, start_time="10:00") == [
        ("10:00 - 10:15", "ひとり", "10:20 - 11:20", "A")
    ]


def test_defaults_match_the_agreed_values():
    """既定値が §52 の決定(とエコーの案内文)と一致していること。"""
    from services import event_intake, timetable_engine as te

    assert te.DEFAULT_SET_MINUTES == 15
    assert te.DEFAULT_GOODS_OFFSET_MINUTES == 5
    assert te.DEFAULT_GOODS_DURATION_MINUTES == 60
    assert te.DEFAULT_CHANGEOVER_EVERY_N == 5
    assert te.DEFAULT_CHANGEOVER_MINUTES == 5
    assert te.DEFAULT_GOODS_SPACES == ("A", "B", "C", "D", "E")

    # ユーザーに案内している既定値と食い違わないこと
    notice = event_intake.TT_DEFAULTS_NOTICE
    assert "出演尺%d分" % te.DEFAULT_SET_MINUTES in notice
    assert "終演%d分後から%d分" % (te.DEFAULT_GOODS_OFFSET_MINUTES,
                                  te.DEFAULT_GOODS_DURATION_MINUTES) in notice
    assert "%d組ごと%d分" % (te.DEFAULT_CHANGEOVER_EVERY_N,
                            te.DEFAULT_CHANGEOVER_MINUTES) in notice


def test_rows_are_plain_drafts_without_special_flags():
    """たたき台は通常の出演者行のみ(物販専用行や非表示フラグは立てない)。"""
    rows = build_timetable(["a", "b"], start_time="10:00")
    for r in rows:
        assert r.is_post_goods is False
        assert r.is_hidden is False
        assert r.is_grid_hidden is False
        assert r.is_delete_marked is False
        assert r.is_special_row is False


# ---------------------------------------------------------------------------
# 不変条件の機械証明
# ---------------------------------------------------------------------------
def test_engine_is_streamlit_free(monkeypatch):
    """streamlit が import 不能でもエンジンは import でき、streamlit を引かない。"""
    import builtins
    import importlib
    import sys

    real_import = builtins.__import__
    original = sys.modules.get("services.timetable_engine")
    import services as _services_pkg
    original_attr = getattr(_services_pkg, "timetable_engine", None)

    def _blocked(name, *a, **kw):
        if name == "streamlit" or name.startswith("streamlit."):
            raise ImportError("streamlit is unavailable (simulated Bot env)")
        return real_import(name, *a, **kw)

    try:
        for m in list(sys.modules):
            if (m == "services.timetable_engine" or m == "streamlit"
                    or m.startswith("streamlit.")):
                sys.modules.pop(m, None)
        monkeypatch.setattr(builtins, "__import__", _blocked)

        mod = importlib.import_module("services.timetable_engine")
        assert callable(mod.build_timetable)
        assert mod.build_timetable(["a"], start_time="10:00")[0].artist_name == "a"
        assert "streamlit" not in sys.modules
    finally:
        # sys.modules と親パッケージ属性の両方を戻す(片方だけだと後続が取り違える)
        if original is not None:
            sys.modules["services.timetable_engine"] = original
        if original_attr is not None:
            setattr(_services_pkg, "timetable_engine", original_attr)


def test_engine_does_not_touch_db(monkeypatch):
    """エンジンは DB セッションを開かない(純関数)。"""
    import database

    monkeypatch.setattr(database, "SessionLocal",
                        lambda *a, **k: pytest.fail("エンジンは DB に触ってはいけない"))
    rows = build_timetable(GOLDEN_ARTISTS, start_time="10:30", changeover_every_n=6)
    assert len(rows) == 7


def test_build_timetable_is_pure():
    """同じ入力なら常に同じ出力。入力リストも書き換えない。"""
    artists = list(GOLDEN_ARTISTS)
    a = build_timetable(artists, start_time="10:30", changeover_every_n=6)
    b = build_timetable(artists, start_time="10:30", changeover_every_n=6)
    assert a == b, "呼ぶたびに結果が変わっている"
    assert artists == GOLDEN_ARTISTS, "入力リストを破壊している"
