"""BOTTZ AI — read 専用 Web API(§11.7 段階A0 骨格)。

同一 FastAPI アプリ(bot/main.py)に APIRouter として mount する read-only API。
Webhook(/callback)の LINE 署名検証とは別系統で、EVENT_API_KEY による API キー
認証で守る(認証系を混ぜない)。

設計方針:
- read のみ(GET・非書き込み)。生成 / write は含めない(A1 / A2 で追加)。
- services / repositories は各エンドポイント内で遅延 import する。これにより
  `import bot.main`(=このルーターを include)は SUPABASE_* env 未設定でも失敗しない
  (database は import 時にロードしない。bot/main.py と同じ流儀)。
- ORM は返さず、既存の読み取り DTO(ProjectView / TimetableRowDraft / ArtistView)を
  dict 化して JSON で返す。
- テストは下記データアクセス薄ラッパ(_load_*)を monkeypatch し、実 DB に触れず検証する。
"""
from __future__ import annotations

import hmac
import json
import os
from dataclasses import asdict
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Response


# ---------------------------------------------------------------------------
# API キー認証(Webhook の LINE 署名検証とは別系統)
# ---------------------------------------------------------------------------
def require_api_key(
    authorization: Optional[str] = Header(default=None),
    x_api_key: Optional[str] = Header(default=None),
) -> None:
    """EVENT_API_KEY と一致するキーが提示されているか検証する。

    受理ヘッダ: `Authorization: Bearer <key>` または `X-API-Key: <key>`。
    EVENT_API_KEY 未設定 / キー未提示 / 不一致 はいずれも 401。
    比較は hmac.compare_digest(タイミング攻撃対策・定数時間比較)。
    """
    expected = os.environ.get("EVENT_API_KEY", "")
    if not expected:
        raise HTTPException(status_code=401, detail="API key not configured")

    presented: Optional[str] = None
    if authorization and authorization.startswith("Bearer "):
        presented = authorization[len("Bearer "):]
    elif x_api_key:
        presented = x_api_key

    if not presented or not hmac.compare_digest(presented, expected):
        raise HTTPException(status_code=401, detail="invalid api key")


router = APIRouter(prefix="/api", dependencies=[Depends(require_api_key)])


# ---------------------------------------------------------------------------
# データアクセス薄ラッパ(services を遅延 import。テストはここを monkeypatch する)
# ---------------------------------------------------------------------------
def _load_project_summaries():
    from services import project_service

    return project_service.list_project_summaries()


def _load_project_view(project_id: int):
    from services import project_service

    return project_service.get_project_flyer_view(project_id)


def _load_rows(project_id: int):
    from services import timetable_service

    return timetable_service.get_rows_for_project(project_id)


def _load_artists():
    from services import artist_service

    return artist_service.list_artists()


def _build_summary_text(project_id: int):
    from services import generation_service

    return generation_service.build_summary_text_for_project(project_id)


def _render_grid_png(project_id: int):
    from services import generation_service

    return generation_service.render_grid_png_for_project(project_id)


def _parse_grid(raw: Optional[str]):
    """grid_order_json(生文字列)を JSON パースして返す。None / 空 / 壊れは None。"""
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# read エンドポイント(全て GET・非書き込み・DTO を JSON で返す)
# ---------------------------------------------------------------------------
@router.get("/projects")
def list_projects() -> list:
    """プロジェクト一覧(軽量: id / title / event_date)。"""
    return [
        {"id": v.id, "title": v.title, "event_date": v.event_date}
        for v in _load_project_summaries()
    ]


@router.get("/projects/{project_id}")
def get_project(project_id: int) -> dict:
    """プロジェクト詳細(ProjectView 相当・生値ミラー)。未検出は 404。"""
    view = _load_project_view(project_id)
    if view is None:
        raise HTTPException(status_code=404, detail="project not found")
    return asdict(view)


@router.get("/projects/{project_id}/rows")
def get_project_rows(project_id: int) -> list:
    """その project の TT rows(TimetableRowDraft 相当)。未検出プロジェクトは 404。"""
    if _load_project_view(project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")
    return [asdict(r) for r in _load_rows(project_id)]


@router.get("/projects/{project_id}/grid")
def get_project_grid(project_id: int) -> dict:
    """その project の grid_order(ProjectView.grid_order_json をパースして返す)。未検出は 404。"""
    view = _load_project_view(project_id)
    if view is None:
        raise HTTPException(status_code=404, detail="project not found")
    return {"grid_order": _parse_grid(view.grid_order_json)}


@router.get("/artists")
def list_artists() -> list:
    """アーティスト一覧(ArtistView 相当・既定 is_deleted==False)。"""
    return [asdict(a) for a in _load_artists()]


# ---------------------------------------------------------------------------
# 生成トリガー(read + generate・書き込みなし。§11.7 段階A1)
# ---------------------------------------------------------------------------
@router.get("/projects/{project_id}/summary-text")
def get_project_summary_text(project_id: int) -> dict:
    """その project の告知テキストを DB から生成して返す。未検出は 404。"""
    text = _build_summary_text(project_id)
    if text is None:
        raise HTTPException(status_code=404, detail="project not found")
    return {"text": text}


@router.get("/projects/{project_id}/grid-image")
def get_project_grid_image(project_id: int) -> Response:
    """その project の grid 画像(PNG・透過)を DB 設定から生成して返す。

    未検出プロジェクトは 404。出演者ゼロで生成不能なら 404(grid has no artists)。
    """
    if _load_project_view(project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")
    png = _render_grid_png(project_id)
    if png is None:
        raise HTTPException(status_code=404, detail="grid has no artists")
    return Response(content=png, media_type="image/png")
