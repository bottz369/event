"""BOTTZ AI read 専用 /api の TestClient テスト(§11.7 段階A0)。

DB / services は import せず、bot.api のデータアクセス薄ラッパ(_load_*)を
monkeypatch して読み取り DTO を差し込む。認証(EVENT_API_KEY)と各 GET の
JSON 形・404・401 を検証する。実 DB には一切触れない(read-only テストの範疇)。

fastapi / starlette / httpx を要するため、bot 依存を入れた venv(例 .venv)で実行する:
    .venv/bin/python3 -m pytest tests/test_bot_api.py -v
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from bot import api as bot_api
from bot import main as bot_main
from models.artist import ArtistView
from models.project import ProjectView
from models.timetable import TimetableRowDraft

API_KEY = "test-secret-key"

client = TestClient(bot_main.app)


@pytest.fixture(autouse=True)
def _set_api_key(monkeypatch):
    """既定で有効な API キーを env に注入(未設定テストは各自 delenv する)。"""
    monkeypatch.setenv("EVENT_API_KEY", API_KEY)


def _auth(key: str = API_KEY) -> dict:
    return {"Authorization": f"Bearer {key}"}


# ---------------------------------------------------------------------------
# 認証(Webhook とは別系統・未認証 401)
# ---------------------------------------------------------------------------
def test_no_key_returns_401():
    assert client.get("/api/projects").status_code == 401


def test_wrong_key_returns_401():
    assert client.get("/api/projects", headers=_auth("wrong")).status_code == 401


def test_unset_env_key_returns_401(monkeypatch):
    monkeypatch.delenv("EVENT_API_KEY", raising=False)
    assert client.get("/api/projects", headers=_auth()).status_code == 401


def test_401_does_not_touch_data_layer(monkeypatch):
    """認証失敗時はエンドポイント本体(_load_*)を呼ばない(=DB に触れない)。"""
    called = {"n": 0}

    def _boom():
        called["n"] += 1
        raise AssertionError("data layer must not be reached on auth failure")

    monkeypatch.setattr(bot_api, "_load_project_summaries", _boom)
    assert client.get("/api/projects", headers=_auth("wrong")).status_code == 401
    assert called["n"] == 0


def test_x_api_key_header_accepted(monkeypatch):
    monkeypatch.setattr(bot_api, "_load_project_summaries", lambda: [])
    r = client.get("/api/projects", headers={"X-API-Key": API_KEY})
    assert r.status_code == 200
    assert r.json() == []


# ---------------------------------------------------------------------------
# GET /api/projects
# ---------------------------------------------------------------------------
def test_list_projects_ok(monkeypatch):
    fake = [
        ProjectView(id=1, title="A", event_date="2026-07-01"),
        ProjectView(id=2, title="B", event_date=None),
    ]
    monkeypatch.setattr(bot_api, "_load_project_summaries", lambda: fake)
    r = client.get("/api/projects", headers=_auth())
    assert r.status_code == 200
    assert r.json() == [
        {"id": 1, "title": "A", "event_date": "2026-07-01"},
        {"id": 2, "title": "B", "event_date": None},
    ]


# ---------------------------------------------------------------------------
# GET /api/projects/{id}
# ---------------------------------------------------------------------------
def test_get_project_ok(monkeypatch):
    view = ProjectView(
        id=7, title="X", event_date="2026-08-01", grid_order_json='{"order":["a"]}'
    )
    monkeypatch.setattr(bot_api, "_load_project_view", lambda pid: view if pid == 7 else None)
    r = client.get("/api/projects/7", headers=_auth())
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == 7
    assert body["title"] == "X"
    # ProjectView は生値ミラー: JSON カラムは raw 文字列のまま返す
    assert body["grid_order_json"] == '{"order":["a"]}'


def test_get_project_404(monkeypatch):
    monkeypatch.setattr(bot_api, "_load_project_view", lambda pid: None)
    assert client.get("/api/projects/999", headers=_auth()).status_code == 404


# ---------------------------------------------------------------------------
# GET /api/projects/{id}/rows
# ---------------------------------------------------------------------------
def test_get_rows_ok(monkeypatch):
    monkeypatch.setattr(
        bot_api, "_load_project_view", lambda pid: ProjectView(id=pid, title="X")
    )
    rows = [
        TimetableRowDraft(artist_name="A", duration=20),
        TimetableRowDraft(artist_name="B", duration=30),
    ]
    monkeypatch.setattr(bot_api, "_load_rows", lambda pid: rows)
    r = client.get("/api/projects/1/rows", headers=_auth())
    assert r.status_code == 200
    body = r.json()
    assert [x["artist_name"] for x in body] == ["A", "B"]
    assert body[0]["duration"] == 20
    # dataclass field のみ(@property は含まれない)
    assert "is_pre_goods_row" not in body[0]


def test_get_rows_404_when_project_missing(monkeypatch):
    monkeypatch.setattr(bot_api, "_load_project_view", lambda pid: None)
    assert client.get("/api/projects/999/rows", headers=_auth()).status_code == 404


# ---------------------------------------------------------------------------
# GET /api/projects/{id}/grid
# ---------------------------------------------------------------------------
def test_get_grid_ok(monkeypatch):
    view = ProjectView(
        id=1, title="X", grid_order_json='{"order":["a","b"],"row_counts_str":"5,6"}'
    )
    monkeypatch.setattr(bot_api, "_load_project_view", lambda pid: view)
    r = client.get("/api/projects/1/grid", headers=_auth())
    assert r.status_code == 200
    assert r.json() == {"grid_order": {"order": ["a", "b"], "row_counts_str": "5,6"}}


def test_get_grid_null_when_absent(monkeypatch):
    view = ProjectView(id=1, title="X", grid_order_json=None)
    monkeypatch.setattr(bot_api, "_load_project_view", lambda pid: view)
    r = client.get("/api/projects/1/grid", headers=_auth())
    assert r.status_code == 200
    assert r.json() == {"grid_order": None}


def test_get_grid_404(monkeypatch):
    monkeypatch.setattr(bot_api, "_load_project_view", lambda pid: None)
    assert client.get("/api/projects/1/grid", headers=_auth()).status_code == 404


# ---------------------------------------------------------------------------
# GET /api/artists
# ---------------------------------------------------------------------------
def test_list_artists_ok(monkeypatch):
    artists = [
        ArtistView(
            id=1,
            name="A",
            image_filename="a.jpg",
            is_deleted=False,
            crop_scale=1.0,
            crop_x=0,
            crop_y=0,
        )
    ]
    monkeypatch.setattr(bot_api, "_load_artists", lambda: artists)
    r = client.get("/api/artists", headers=_auth())
    assert r.status_code == 200
    body = r.json()
    assert body[0]["name"] == "A"
    assert body[0]["is_deleted"] is False
