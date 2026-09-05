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
    # #4 以降 generation_service は resolve_artists_in_order を通る(未登録名も枠を残す)。
    # ここはフォント materialize の検証なので、解決結果はダミーのままでよい。
    monkeypatch.setattr(gs.artist_service, "resolve_artists_in_order",
                        lambda names, failures=None: ["artistA"])
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
    # #4 以降 generation_service は resolve_artists_in_order を通る(未登録名も枠を残す)。
    # ここはフォント materialize の検証なので、解決結果はダミーのままでよい。
    monkeypatch.setattr(gs.artist_service, "resolve_artists_in_order",
                        lambda names, failures=None: ["artistA"])

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


# ---------------------------------------------------------------------------
# 段階A2 のハードニング(53dd1ec・§45/罠40): materialize が「実際に使えるフォントを
# 置いた」ことまで検証する回帰網
# ---------------------------------------------------------------------------
# 旧テスト(上の2本)は ensure_font_available を丸ごと monkeypatch していたため、
# 「呼ばれたこと」しか見ておらず、FONT_DIR にフォントが落ちたか / 日本語が描けるかは
# 一切保証していなかった。本番で 6 週間豆腐が出続けたのを検知できなかった穴がここ。
import logging

import pytest
from PIL import ImageFont

import services.font_service as fs
from models.timetable import TimetableRowDraft


def _real_font_bytes() -> bytes:
    """本物の TTF バイト列(Pillow 同梱の Aileron Regular)。

    ネットワーク・リポジトリ同梱フォントに依存せず、どの環境でも同じ「本物のフォント」を
    得るために Pillow の既定フォントの生バイトを借りる(load_default は file-like から
    読むため FreeTypeFont.font_bytes に原本が残る)。
    """
    try:
        data = ImageFont.load_default(20).font_bytes
    except Exception as e:  # 取り出せない Pillow 版
        pytest.skip(f"Pillow 同梱フォントのバイト列を取得できない: {e}")
    if not data:
        pytest.skip("Pillow 同梱フォントのバイト列が空")
    return data


class _Asset:
    image_filename = "testfont.ttf"


def _stub_font_sources(monkeypatch, tmp_path, *, http_body, http_status=200, binary=None):
    """font_service の外部依存(FONT_DIR / DB / Storage URL / HTTP)を差し替える。"""
    monkeypatch.setattr(fs, "FONT_DIR", str(tmp_path))
    monkeypatch.setattr(fs, "SessionLocal", lambda: _FakeDB())
    monkeypatch.setattr(
        fs.font_repo, "get_font_asset",
        lambda db, name: _Asset() if http_body is not None else None,
    )
    monkeypatch.setattr(fs, "get_image_url", lambda name: "https://example.invalid/f.ttf")

    class _Resp:
        status_code = http_status
        content = http_body or b""

    monkeypatch.setattr(fs.requests, "get", lambda url, **kw: _Resp())

    class _AF:
        file_data = binary

    monkeypatch.setattr(
        fs.font_repo, "get_font_asset_file",
        lambda db, name: _AF() if binary else None,
    )


def test_ensure_font_available_writes_a_usable_font(monkeypatch, tmp_path):
    """URL 経路で取得したファイルが「PIL で開けるフォント」として置かれること。"""
    _stub_font_sources(monkeypatch, tmp_path, http_body=_real_font_bytes())

    status = fs.ensure_font_available("testfont.ttf")

    assert status == "downloaded_url"
    written = tmp_path / "testfont.ttf"
    assert written.exists() and written.stat().st_size > 0
    # ★ 生成成功ではなく「フォントとして開ける」ことを assert する
    assert ImageFont.truetype(str(written), 12) is not None


def test_ensure_font_available_rejects_non_font_payload(monkeypatch, tmp_path):
    """200 でも中身がフォントでなければ成功扱いにせず、壊れファイルを残さない。

    旧実装は size>0 だけを見ていたため、この状況で "downloaded_url" を返し、
    以後は "cached" が固着してコンテナが生きている限り豆腐が直らなかった。
    """
    _stub_font_sources(monkeypatch, tmp_path, http_body=b"<html>404 Not Found</html>")

    status = fs.ensure_font_available("testfont.ttf")

    assert status == "not_found"
    assert not (tmp_path / "testfont.ttf").exists(), "壊れたファイルを残してはいけない"


def test_ensure_font_available_repairs_poisoned_cache(monkeypatch, tmp_path):
    """FONT_DIR に既に壊れたファイルがあっても "cached" で固着せず取り直すこと。"""
    poisoned = tmp_path / "testfont.ttf"
    poisoned.write_bytes(b"not a font at all")
    _stub_font_sources(monkeypatch, tmp_path, http_body=_real_font_bytes())

    status = fs.ensure_font_available("testfont.ttf")

    assert status == "downloaded_url", "壊れキャッシュを 'cached' として返してはいけない"
    assert ImageFont.truetype(str(poisoned), 12) is not None


def test_ensure_font_available_falls_back_to_binary_when_url_payload_is_broken(
    monkeypatch, tmp_path
):
    """URL の中身が壊れていたら binary(AssetFile)経路へ落ちて復旧できること。"""
    _stub_font_sources(
        monkeypatch, tmp_path,
        http_body=b"<html>oops</html>",
        binary=_real_font_bytes(),
    )

    status = fs.ensure_font_available("testfont.ttf")

    assert status == "downloaded_db"
    assert ImageFont.truetype(str(tmp_path / "testfont.ttf"), 12) is not None


class _RecordingHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


def test_render_warns_loudly_when_font_is_not_resolved(monkeypatch):
    """フォントが解決できないまま生成に進むとき、必ず警告を出すこと。

    generate_grid_image は font 未解決でも黙って PIL 既定フォントで描画して画像を
    返してしまう。ログが無いと本番で豆腐が出ていることに誰も気づけない
    (段階A2 のフォント materialize 修正 6a95fe2 が 6 週間見逃された実因。§45/罠40)。
    この警告はその検知装置なので回帰網で守る。
    """
    monkeypatch.setattr(gs.font_service, "ensure_font_available", lambda name: "not_found")
    monkeypatch.setattr(gs, "SessionLocal", lambda: _FakeDB())
    monkeypatch.setattr(gs.project_repo, "get_project", lambda db, pid: _FakeProject())
    # #4 以降 generation_service は resolve_artists_in_order を通る(未登録名も枠を残す)。
    # ここはフォント materialize の検証なので、解決結果はダミーのままでよい。
    monkeypatch.setattr(gs.artist_service, "resolve_artists_in_order",
                        lambda names, failures=None: ["artistA"])
    monkeypatch.setattr(gs, "resolve_font_path", lambda p: None)
    monkeypatch.setattr(gs, "generate_grid_image", lambda *a, **k: None)

    # utils.logger は propagate=False なので caplog では拾えない。直接ハンドラを付ける。
    handler = _RecordingHandler()
    gs.logger.addHandler(handler)
    try:
        gs.render_grid_png_for_project(1)
    finally:
        gs.logger.removeHandler(handler)

    warnings = [r.getMessage() for r in handler.records if r.levelno >= logging.WARNING]
    assert any("tofu" in m for m in warnings), (
        "フォント未解決時に豆腐化の警告が出ていない: %r" % warnings
    )


# ---------------------------------------------------------------------------
# 段階B B-1: render_timetable_png_for_project のフォント materialize
# ---------------------------------------------------------------------------
class _FakeTTProject:
    id = 1
    grid_order_json = None
    settings_json = '{"tt_font":"myfont.ttf","tt_columns":2}'
    open_time = "10:00"
    start_time = "10:30"
    title = "X"
    subtitle = ""
    event_date = None
    venue_name = ""
    venue_url = ""
    goods_start_offset = 5
    tickets_json = None
    ticket_notes_json = None
    free_text_json = None
    flyer_json = None


def test_render_timetable_materializes_font_and_default(monkeypatch):
    """TT 画像生成でも tt_font と keifont.ttf の両方を materialize すること。"""
    calls = []
    monkeypatch.setattr(gs.font_service, "ensure_font_available", lambda name: calls.append(name) or "cached")
    monkeypatch.setattr(gs, "SessionLocal", lambda: _FakeDB())
    monkeypatch.setattr(gs.project_repo, "get_project", lambda db, pid: _FakeTTProject())
    monkeypatch.setattr(
        gs.timetable_service, "get_rows_for_project",
        lambda pid: [TimetableRowDraft(artist_name="A", duration=30)],
    )
    monkeypatch.setattr(
        gs.timetable_service, "build_tt_gen_list_from_rows",
        lambda rows, o, s: [["10:30 - 11:00", "A", "", "A"]],
    )
    monkeypatch.setattr(gs, "generate_timetable_image", lambda *a, **k: None)

    assert gs.render_timetable_png_for_project(1) is None  # generate stub が None
    assert "myfont.ttf" in calls
    assert "keifont.ttf" in calls


def test_render_timetable_warns_when_font_is_not_resolved(monkeypatch, tmp_path):
    """フォントが FONT_DIR に無いまま生成に進むとき、必ず豆腐警告を出すこと。

    ★logic_timetable.get_font の候補には FONT_DIR が入っていないため、
    keifont.ttf を materialize してあっても渡す path が実在しなければ
    PIL 既定フォントに落ちて日本語ラベルが豆腐になる。その検知装置を守る。
    """
    monkeypatch.setattr(gs, "FONT_DIR", str(tmp_path))  # 空ディレクトリ
    monkeypatch.setattr(gs.font_service, "ensure_font_available", lambda name: "not_found")
    monkeypatch.setattr(gs, "SessionLocal", lambda: _FakeDB())
    monkeypatch.setattr(gs.project_repo, "get_project", lambda db, pid: _FakeTTProject())
    monkeypatch.setattr(
        gs.timetable_service, "get_rows_for_project",
        lambda pid: [TimetableRowDraft(artist_name="A", duration=30)],
    )
    monkeypatch.setattr(
        gs.timetable_service, "build_tt_gen_list_from_rows",
        lambda rows, o, s: [["10:30 - 11:00", "A", "", "A"]],
    )
    monkeypatch.setattr(gs, "generate_timetable_image", lambda *a, **k: None)

    handler = _RecordingHandler()
    gs.logger.addHandler(handler)
    try:
        gs.render_timetable_png_for_project(1)
    finally:
        gs.logger.removeHandler(handler)

    warnings = [r.getMessage() for r in handler.records if r.levelno >= logging.WARNING]
    assert any("tofu" in m for m in warnings), (
        "フォント未解決時に豆腐化の警告が出ていない: %r" % warnings
    )
