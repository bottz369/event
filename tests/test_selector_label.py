"""プロジェクト選択セレクタのラベル(サブタイトル付き)のテスト。

ラベルは「開催日 イベント名 - サブタイトル」。サブタイトルが無ければ従来どおり
「開催日 イベント名」。区切りは告知テキストのタイトル行(#3a)と揃える。

★キャッシュ無効化も一緒に守る: セレクタは @st.cache_data なので、
  サブタイトルだけ変えて保存したときに clear() されないとラベルが古いままになる。

実 DB には書かない(保存経路は monkeypatch でスタブ)。
"""
from __future__ import annotations

import pytest

from services import project_service as ps


# ---------------------------------------------------------------------------
# ラベル生成(純関数)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "event_date,title,subtitle,expected",
    [
        ("2026-11-03", "テスト", "ガールズフェス", "2026-11-03 テスト - ガールズフェス"),
        ("2026-11-03", "テスト", None, "2026-11-03 テスト"),
        ("2026-11-03", "テスト", "", "2026-11-03 テスト"),
        (None, "テスト", "サブ", "---- テスト - サブ"),
        (None, "テスト", None, "---- テスト"),
    ],
)
def test_build_selector_label(event_date, title, subtitle, expected):
    assert ps.build_selector_label(event_date, title, subtitle) == expected


def test_separator_matches_the_summary_title_format():
    """区切りは告知テキストのタイトル行(#3a)と同じ半角ハイフン前後スペース。"""
    label = ps.build_selector_label("2026-11-03", "A", "B")
    assert " - " in label
    assert "－" not in label and "-" in label


# ---------------------------------------------------------------------------
# 一覧生成
# ---------------------------------------------------------------------------
class _P:
    def __init__(self, pid, event_date, title, subtitle=None):
        self.id, self.event_date, self.title, self.subtitle = (
            pid, event_date, title, subtitle)


def test_list_projects_for_selector_includes_subtitle(monkeypatch):
    monkeypatch.setattr(ps, "SessionLocal", lambda: _FakeDB())
    monkeypatch.setattr(ps.project_repo, "list_projects", lambda db: [
        _P(1, "2026-11-03", "サブ有り", "ガールズフェス"),
        _P(2, "2026-11-04", "サブ無し", None),
        _P(3, None, "日付無し", "サブ"),
    ])
    # cache 経由ではなく素の関数を呼ぶ(キャッシュの有無に依存しない)
    result = ps.list_projects_for_selector.__wrapped__() \
        if hasattr(ps.list_projects_for_selector, "__wrapped__") \
        else ps.list_projects_for_selector()

    assert result == [
        (1, "2026-11-03 サブ有り - ガールズフェス"),
        (2, "2026-11-04 サブ無し"),
        (3, "---- 日付無し - サブ"),
    ]


class _FakeDB:
    def close(self):
        pass


def test_projects_without_subtitle_attribute_do_not_crash(monkeypatch):
    """subtitle 属性を持たないオブジェクトが来ても落ちない(getattr 経由)。"""
    class _Legacy:
        def __init__(self):
            self.id, self.event_date, self.title = 9, "2026-01-01", "旧"

    monkeypatch.setattr(ps, "SessionLocal", lambda: _FakeDB())
    monkeypatch.setattr(ps.project_repo, "list_projects", lambda db: [_Legacy()])
    result = ps.list_projects_for_selector.__wrapped__() \
        if hasattr(ps.list_projects_for_selector, "__wrapped__") \
        else ps.list_projects_for_selector()
    assert result == [(9, "2026-01-01 旧")]


# ---------------------------------------------------------------------------
# キャッシュ無効化
# ---------------------------------------------------------------------------
@pytest.fixture
def save_spy(monkeypatch):
    """save_active_project の中身をスタブし、clear() が呼ばれたかを見る。

    実 DB には一切書かない。
    """
    from models import ProjectDraft
    from services import session_manager

    state = {"cleared": 0, "before": None, "after": None}

    monkeypatch.setattr(ps.list_projects_for_selector, "clear",
                        lambda: state.__setitem__("cleared", state["cleared"] + 1))
    monkeypatch.setattr(session_manager, "sync_session_to_draft", lambda: True)
    monkeypatch.setattr(session_manager, "get_draft_rows", lambda: [])
    monkeypatch.setattr(session_manager, "mark_saved", lambda: None)
    monkeypatch.setattr(ps, "SessionLocal", lambda: _FakeDB())
    monkeypatch.setattr(ps.project_repo, "update_project_from_draft",
                        lambda db, draft, rows=None: True)
    monkeypatch.setattr(ps.timetable_repo, "save_rows", lambda db, pid, rows: True)

    def _drafts(before, after):
        state["before"], state["after"] = before, after
        seq = iter([before, after])
        monkeypatch.setattr(session_manager, "get_draft_project", lambda: next(seq))

    state["set_drafts"] = _drafts
    state["Draft"] = ProjectDraft
    return state


def _draft(Draft, title="T", date="2026-11-03", subtitle=""):
    return Draft(id=1, title=title, event_date=date, subtitle=subtitle)


def test_cache_cleared_when_subtitle_changes(save_spy):
    """★サブタイトルだけ変えた保存でもセレクタのキャッシュが無効化される。"""
    D = save_spy["Draft"]
    save_spy["set_drafts"](_draft(D, subtitle="旧サブ"), _draft(D, subtitle="新サブ"))
    assert ps.save_active_project() is True
    assert save_spy["cleared"] == 1, "サブタイトル変更で invalidate されていない"


def test_cache_cleared_when_title_changes(save_spy):
    D = save_spy["Draft"]
    save_spy["set_drafts"](_draft(D, title="旧"), _draft(D, title="新"))
    assert ps.save_active_project() is True
    assert save_spy["cleared"] == 1


def test_cache_cleared_when_date_changes(save_spy):
    D = save_spy["Draft"]
    save_spy["set_drafts"](_draft(D, date="2026-11-03"), _draft(D, date="2026-11-04"))
    assert ps.save_active_project() is True
    assert save_spy["cleared"] == 1


def test_cache_not_cleared_when_label_fields_are_unchanged(save_spy):
    """ラベルに出ない項目だけの保存では無駄な invalidate をしない(既存の意図)。"""
    D = save_spy["Draft"]
    same = _draft(D, title="T", date="2026-11-03", subtitle="S")
    save_spy["set_drafts"](same, _draft(D, title="T", date="2026-11-03", subtitle="S"))
    assert ps.save_active_project() is True
    assert save_spy["cleared"] == 0


# ---------------------------------------------------------------------------
# テスト側とのラベル形式の一致
# ---------------------------------------------------------------------------
def test_conftest_uses_the_same_label_builder():
    """conftest が自前でラベルを組んでいないこと。

    自前で組むと形式変更時にテストが「ラベルが見つからない」で静かに skip し、
    失敗として気づけなくなる。
    """
    src = open("tests/conftest.py", encoding="utf-8").read()
    assert "build_selector_label" in src
    assert "or '----'} {row.title}" not in src


def test_cache_decorator_stays_on_the_list_function():
    """@_cache_data が list_projects_for_selector に付いていること。

    ★実バグの再発防止: build_selector_label をこの関数の直前に足したとき、
      デコレータと関数の間に挟まってしまい、キャッシュが helper に付いた。
      その状態だと list_projects_for_selector に .clear が生えず、
      save_active_project のキャッシュ無効化が AttributeError で落ちる。
    """
    assert hasattr(ps.list_projects_for_selector, "clear"), (
        "@_cache_data が list_projects_for_selector から外れている"
    )
    # 純関数側にはキャッシュを付けない(引数だけで決まるので不要)
    assert not hasattr(ps.build_selector_label, "clear")
