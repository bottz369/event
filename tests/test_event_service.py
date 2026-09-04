"""段階B B-3 C1: イベント検索 service のテスト。

並び順(これから優先 → 過去補完)・limit・出演判定・0件を、today 注入で決定的に検証する。
DB は repositories を monkeypatch して触らない。

.venv 実行想定:
    .venv/bin/python3 -m pytest tests/test_event_service.py -v
"""
from __future__ import annotations

import datetime

import pytest

import services.event_service as es
from models.event import EventOption

TODAY = datetime.date(2026, 9, 3)


class _FakeDB:
    def close(self):
        pass


def _stub_rows(monkeypatch, rows):
    """timetable_repo.find_projects_by_artist_name の戻り値を差し替える。"""
    monkeypatch.setattr(es, "SessionLocal", lambda: _FakeDB())
    monkeypatch.setattr(
        es.timetable_repo, "find_projects_by_artist_name", lambda db, name: rows
    )


def test_upcoming_first_then_past_desc(monkeypatch):
    """★これから順(近い順)→ 足りなければ過去を新しい順で補完。"""
    _stub_rows(monkeypatch, [
        (1, "過去A", "2026-08-01"),
        (2, "未来B", "2026-09-21"),
        (3, "過去C", "2026-08-30"),
        (4, "未来D", "2026-09-05"),
    ])
    got = es.list_recent_events_for_artist("X", limit=4, today=TODAY)
    assert [o.project_id for o in got] == [4, 2, 3, 1], [
        (o.project_id, o.event_date) for o in got
    ]


def test_today_counts_as_upcoming(monkeypatch):
    """当日は「これから」に含む(>= today)。"""
    _stub_rows(monkeypatch, [(1, "過去", "2026-09-02"), (2, "当日", "2026-09-03")])
    got = es.list_recent_events_for_artist("X", limit=2, today=TODAY)
    assert [o.project_id for o in got] == [2, 1]


def test_limit_is_respected(monkeypatch):
    _stub_rows(monkeypatch, [
        (i, "E%d" % i, "2026-09-%02d" % (10 + i)) for i in range(1, 8)
    ])
    got = es.list_recent_events_for_artist("X", limit=4, today=TODAY)
    assert len(got) == 4
    assert [o.project_id for o in got] == [1, 2, 3, 4], "近い順で 4 件"


def test_only_past_falls_back(monkeypatch):
    """これからが 0 件なら過去だけで埋める(新しい順)。"""
    _stub_rows(monkeypatch, [
        (1, "古い", "2026-01-01"),
        (2, "新しい", "2026-08-30"),
        (3, "中間", "2026-05-05"),
    ])
    got = es.list_recent_events_for_artist("X", limit=4, today=TODAY)
    assert [o.project_id for o in got] == [2, 3, 1]


def test_none_date_goes_last(monkeypatch):
    """日付未設定は最後(過去枠の末尾)。"""
    _stub_rows(monkeypatch, [
        (1, "日付なし", None),
        (2, "未来", "2026-09-21"),
        (3, "過去", "2026-08-01"),
    ])
    got = es.list_recent_events_for_artist("X", limit=4, today=TODAY)
    assert [o.project_id for o in got] == [2, 3, 1]


def test_broken_date_is_treated_as_none(monkeypatch):
    _stub_rows(monkeypatch, [(1, "壊れ", "not-a-date"), (2, "未来", "2026-09-21")])
    got = es.list_recent_events_for_artist("X", limit=4, today=TODAY)
    assert [o.project_id for o in got] == [2, 1]
    assert got[1].event_date is None


def test_no_events_returns_empty(monkeypatch):
    _stub_rows(monkeypatch, [])
    assert es.list_recent_events_for_artist("X", today=TODAY) == []


@pytest.mark.parametrize("bad", ["", None])
def test_empty_name_returns_empty(bad, monkeypatch):
    _stub_rows(monkeypatch, [(1, "E", "2026-09-21")])
    assert es.list_recent_events_for_artist(bad, today=TODAY) == []


def test_zero_limit_returns_empty(monkeypatch):
    _stub_rows(monkeypatch, [(1, "E", "2026-09-21")])
    assert es.list_recent_events_for_artist("X", limit=0, today=TODAY) == []


def test_returns_dto_with_title_fallback(monkeypatch):
    _stub_rows(monkeypatch, [(9, None, "2026-09-21")])
    got = es.list_recent_events_for_artist("X", today=TODAY)
    assert isinstance(got[0], EventOption)
    assert got[0].project_id == 9
    assert got[0].title == "(無題)"
    assert got[0].event_date == datetime.date(2026, 9, 21)
