"""render_grid_png_for_project が生成前にフォントを materialize することの確認(§A2 豆腐化修正)。

font_service.ensure_font_available を monkeypatch し、grid_font 本体と "keifont.ttf" の
両方について呼ばれることを検証する。DB / 実生成には触れない(全て stub)。
.venv 実行想定(generation_service の import が database を引くため)。
"""
from __future__ import annotations

import services.generation_service as gs


class _FakeProject:
    grid_order_json = '{"order":["A"],"row_counts_str":"1","layout_mode":"レンガ (サイズ統一)","alignment":"中央揃え"}'
    settings_json = '{"grid_font":"myfont.ttf"}'


class _FakeDB:
    def close(self):
        pass


def test_render_materializes_grid_font_and_default(monkeypatch):
    calls = []
    monkeypatch.setattr(gs.font_service, "ensure_font_available", lambda name: calls.append(name))
    monkeypatch.setattr(gs, "SessionLocal", lambda: _FakeDB())
    monkeypatch.setattr(gs.project_repo, "get_project", lambda db, pid: _FakeProject())
    monkeypatch.setattr(gs.artist_service, "get_artists_by_names", lambda names: ["artistA"])
    # 実生成はスキップ(None を返させる。materialize はその前に済む)
    monkeypatch.setattr(gs, "generate_grid_image", lambda *a, **k: None)

    result = gs.render_grid_png_for_project(1)

    assert result is None  # generate stub が None
    # settings の grid_font と、フォールバックの keifont.ttf の両方を materialize
    assert "myfont.ttf" in calls
    assert "keifont.ttf" in calls


def test_render_materialize_failure_does_not_break(monkeypatch):
    """ensure_font_available が例外でも生成は続行(握ってログのみ)。"""
    def _boom(name):
        raise RuntimeError("font DB down")

    monkeypatch.setattr(gs.font_service, "ensure_font_available", _boom)
    monkeypatch.setattr(gs, "SessionLocal", lambda: _FakeDB())
    monkeypatch.setattr(gs.project_repo, "get_project", lambda db, pid: _FakeProject())
    monkeypatch.setattr(gs.artist_service, "get_artists_by_names", lambda names: ["artistA"])

    sentinel = object()
    captured = {}

    def _fake_generate(*a, **k):
        captured["reached"] = True
        return None  # 生成失敗扱い(None)

    monkeypatch.setattr(gs, "generate_grid_image", _fake_generate)

    # 例外を投げず、generate まで到達すること
    result = gs.render_grid_png_for_project(1)
    assert result is None
    assert captured.get("reached") is True
