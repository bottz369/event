"""utils.text_generator.build_event_summary_text のテスト(#3a / #3c)。

純関数なので DB も streamlit も要らない。全プロジェクト共通の告知テキストを
組む関数なので、**変えると決めた挙動以外はバイト単位で不変**であることを守る。
"""
from __future__ import annotations

import datetime

import pytest

from utils.text_generator import build_event_summary_text

BASE = dict(
    date_val=datetime.date(2026, 11, 3),
    venue="上野恩賜公園野外ステージ",
    url="https://maps.example/xyz",
    open_time="11:30",
    start_time="12:00",
    tickets=[{"name": "Sチケット", "price": "¥6,000", "note": "前方エリア"}],
    ticket_notes=["※各ドリンク代別"],
    artists=["アルテミスの翼", "Luna moon", "リルリボン"],
    free_texts=[{"title": "■注意事項", "content": "ジャンプの禁止"}],
)


def _head(text):
    """【公演概要】ブロック(会場の前まで)を返す。"""
    return text.split("\n\n")[0]


# ---------------------------------------------------------------------------
# #3a: タイトル 1 行結合
# ---------------------------------------------------------------------------
def test_title_and_subtitle_are_joined_on_one_line():
    text = build_event_summary_text(title="テスト", subtitle="ガールズテストフェス", **BASE)
    assert _head(text) == (
        "【公演概要】\n2026年11月03日(火)\n『テスト - ガールズテストフェス』"
    )
    # 旧仕様(次行に ～サブタイトル～)が残っていないこと
    assert "～ガールズテストフェス～" not in text


def test_title_without_subtitle_is_unchanged():
    """サブタイトルが無いときの出力は従来と完全に同じ。"""
    text = build_event_summary_text(title="テスト", subtitle="", **BASE)
    assert _head(text) == "【公演概要】\n2026年11月03日(火)\n『テスト』"
    assert " - " not in _head(text), "区切りが混ざっている"


@pytest.mark.parametrize("subtitle", [None, "", 0])
def test_falsy_subtitle_is_treated_as_absent(subtitle):
    text = build_event_summary_text(title="テスト", subtitle=subtitle, **BASE)
    assert "『テスト』" in text


def test_subtitle_uses_ascii_hyphen_with_spaces():
    """区切りは半角ハイフン前後スペース(告知文フォーマットと同じ)。"""
    text = build_event_summary_text(title="A", subtitle="B", **BASE)
    assert "『A - B』" in text


# ---------------------------------------------------------------------------
# 出演者見出し(#3c の前提: 予定数を渡さないときは実組数)
# ---------------------------------------------------------------------------
def test_artist_count_defaults_to_actual_length():
    """予定数を渡さないときは従来どおり実組数(完全な後方互換)。"""
    text = build_event_summary_text(title="T", subtitle="", **BASE)
    assert "■出演者（3組予定）" in text


def test_output_is_byte_identical_without_planned_count():
    """★予定数を持たない既存プロジェクトの出力が変わっていないことの固定。

    #3a のタイトル行だけが意図的な変更点。それ以外は 1 バイトも動かさない。
    """
    text = build_event_summary_text(title="テスト", subtitle="", **BASE)
    assert text == (
        "【公演概要】\n"
        "2026年11月03日(火)\n"
        "『テスト』\n"
        "\n"
        "■会場: 上野恩賜公園野外ステージ\n"
        " https://maps.example/xyz\n"
        "\n"
        "OPEN▶11:30\n"
        "START▶12:00\n"
        "\n"
        "■チケット\n"
        "- Sチケット: ¥6,000 (前方エリア)\n"
        # Issue1: 保存値が "※各ドリンク代別" でも ※ は 1 個
        "※各ドリンク代別\n"
        "\n"
        "■出演者（3組予定）\n"
        "①アルテミスの翼\n"
        "②Luna moon\n"
        "③リルリボン\n"
        "\n"
        "■■注意事項\n"
        "ジャンプの禁止"
    )


# ---------------------------------------------------------------------------
# #3c: 予定組数
# ---------------------------------------------------------------------------
def test_planned_artist_count_is_used_when_given():
    text = build_event_summary_text(title="T", subtitle="",
                                    planned_artist_count=27, **BASE)
    assert "■出演者（27組予定）" in text
    assert "■出演者（3組予定）" not in text
    # 実際に並ぶ名前は変わらない(予定数は見出しの数字だけ)
    for name in BASE["artists"]:
        assert name in text


@pytest.mark.parametrize("planned", [None, 0, -1, "", "27", True, 1.5])
def test_invalid_or_absent_planned_count_falls_back_to_length(planned):
    """None / 0 / 負 / 文字列 / bool / float は保持していない扱いにして len へ。

    bool を弾くのは、True が int のサブクラスなので「1組予定」になってしまうため。
    """
    text = build_event_summary_text(title="T", subtitle="",
                                    planned_artist_count=planned, **BASE)
    assert "■出演者（3組予定）" in text


def test_planned_count_changes_only_the_headline_number():
    """予定数の有無で変わるのは出演者見出しの数字だけ(他はバイト一致)。"""
    without = build_event_summary_text(title="T", subtitle="S", **BASE)
    with_planned = build_event_summary_text(title="T", subtitle="S",
                                            planned_artist_count=27, **BASE)
    assert without.replace("（3組予定）", "（27組予定）") == with_planned


def test_planned_count_is_the_last_optional_argument():
    """位置引数で呼んでいる既存コードを壊さない(末尾のオプション引数)。"""
    import inspect

    params = list(inspect.signature(build_event_summary_text).parameters)
    assert params[-1] == "planned_artist_count"
    assert inspect.signature(build_event_summary_text).parameters[
        "planned_artist_count"].default is None


# ---------------------------------------------------------------------------
# Issue1: 共通備考の ※ は常に 1 個
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "stored,expected",
    [
        ("※各ドリンク代別", "※各ドリンク代別"),   # 告知文から ※ 込みで取り込んだ値
        ("各ドリンク代別", "※各ドリンク代別"),      # 手入力で ※ 無し
        ("※※x", "※x"),                            # 二重に保存されてしまった値
        ("  ※  y  ", "※y"),                        # 前後・間の空白
        ("※\u3000※ z", "※z"),                     # 全角スペース混じり
    ],
)
def test_ticket_note_always_gets_exactly_one_mark(stored, expected):
    text = build_event_summary_text(title="T", subtitle="",
                                    **dict(BASE, ticket_notes=[stored]))
    notes = [l for l in text.splitlines() if l.startswith("※")]
    assert notes == [expected]
    assert "※※" not in text


@pytest.mark.parametrize("stored", ["※", "※※", "   ", "※ 　"])
def test_note_that_is_only_marks_is_dropped(stored):
    """中身が ※ と空白だけなら行ごと出さない(「※」だけの行を作らない)。"""
    text = build_event_summary_text(title="T", subtitle="",
                                    **dict(BASE, ticket_notes=[stored]))
    assert not [l for l in text.splitlines() if l.startswith("※")]


def test_multiple_notes_are_each_normalized():
    text = build_event_summary_text(
        title="T", subtitle="",
        **dict(BASE, ticket_notes=["※各ドリンク代別", "未就学児入場不可"]))
    notes = [l for l in text.splitlines() if l.startswith("※")]
    assert notes == ["※各ドリンク代別", "※未就学児入場不可"]


def test_note_normalization_does_not_touch_inner_marks():
    """先頭の ※ だけを外す。文中の ※ はそのまま残す。"""
    text = build_event_summary_text(title="T", subtitle="",
                                    **dict(BASE, ticket_notes=["※A※B"]))
    notes = [l for l in text.splitlines() if l.startswith("※")]
    assert notes == ["※A※B"]
