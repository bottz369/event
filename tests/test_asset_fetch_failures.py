"""§5: 素材(アー写 / 背景 / ロゴ)取得失敗の可観測化テスト。

従来は取得失敗を静かに None にして「素材なし」で描画継続していたため、
どの素材が落ちたか追跡できなかった。本テストは:
  - 非空 URL の失敗で【必ず WARNING ログ】が出ること
  - failures list を渡すと構造化エントリが入ること
  - 空 URL / 画像未設定では失敗扱いしない(ログも failure も出ない)こと
  - failures=None(= 既存 views 経路)では従来と同じ戻り値であること
を機械確認する。

.venv 実行想定(database / PIL を引くため):
    .venv/bin/python3 -m pytest tests/test_asset_fetch_failures.py -v
"""
from __future__ import annotations

import logging

import pytest
import requests

import logic_timetable as lt


# ---------------------------------------------------------------------------
# 共通スタブ
# ---------------------------------------------------------------------------
class _Resp:
    def __init__(self, status_code=200, content=b""):
        self.status_code = status_code
        self.content = content


def _boom(*a, **k):
    raise requests.ConnectionError("simulated network failure")


class _FakeArtist:
    def __init__(self, name, image_filename):
        self.name = name
        self.image_filename = image_filename


class _FakeQuery:
    def __init__(self, artist):
        self._a = artist

    def filter(self, *a, **k):
        return self

    def first(self):
        return self._a


class _FakeDB:
    def __init__(self, artist=None):
        self._a = artist

    def query(self, model):
        return _FakeQuery(self._a)


# ---------------------------------------------------------------------------
# load_image: 非空 URL の失敗はログを出す / 戻り値は None のまま
# ---------------------------------------------------------------------------
def test_load_image_http_error_logs_warning(monkeypatch, caplog):
    monkeypatch.setattr(lt.requests, "get", lambda url, **k: _Resp(404))
    with caplog.at_level(logging.WARNING, logger="logic_timetable"):
        assert lt.load_image("https://example.invalid/a.jpg") is None
    msgs = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("http_404" in m for m in msgs), msgs
    assert any("example.invalid/a.jpg" in m for m in msgs), msgs


def test_load_image_exception_logs_warning(monkeypatch, caplog):
    monkeypatch.setattr(lt.requests, "get", _boom)
    with caplog.at_level(logging.WARNING, logger="logic_timetable"):
        assert lt.load_image("https://example.invalid/a.jpg") is None
    msgs = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("ConnectionError" in m for m in msgs), msgs


def test_load_image_decode_failure_logs_warning(monkeypatch, caplog):
    """200 でも中身が画像でなければ失敗として記録する。"""
    monkeypatch.setattr(lt.requests, "get", lambda url, **k: _Resp(200, b"<html>not an image</html>"))
    with caplog.at_level(logging.WARNING, logger="logic_timetable"):
        assert lt.load_image("https://example.invalid/a.jpg") is None
    assert [r for r in caplog.records if r.levelno >= logging.WARNING]


@pytest.mark.parametrize("empty", [None, "", 0])
def test_load_image_empty_is_not_a_failure(empty, caplog):
    """★空 URL / 空パスは失敗ではない。ログを出さない。"""
    with caplog.at_level(logging.WARNING, logger="logic_timetable"):
        assert lt.load_image(empty) is None
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


# ---------------------------------------------------------------------------
# _load_and_fit_tt(B-1.5 の fit 版 loader)も同様
# ---------------------------------------------------------------------------
def test_load_and_fit_tt_http_error_logs_warning(monkeypatch, caplog):
    monkeypatch.setattr(lt.requests, "get", lambda url, **k: _Resp(500))
    with caplog.at_level(logging.WARNING, logger="logic_timetable"):
        assert lt._load_and_fit_tt("https://example.invalid/a.jpg", 100, 50) is None
    msgs = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("http_500" in m for m in msgs), msgs


def test_load_and_fit_tt_exception_logs_warning(monkeypatch, caplog):
    monkeypatch.setattr(lt.requests, "get", _boom)
    with caplog.at_level(logging.WARNING, logger="logic_timetable"):
        assert lt._load_and_fit_tt("https://example.invalid/a.jpg", 100, 50) is None
    msgs = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("ConnectionError" in m for m in msgs), msgs


# ---------------------------------------------------------------------------
# _prefetch_tt_images: メインスレッドで突合して failures を組む
# ---------------------------------------------------------------------------
def _prefetch(monkeypatch, artist, failures, url="https://example.invalid/a.jpg"):
    import database

    monkeypatch.setattr(database, "get_image_url", lambda fn: url)
    monkeypatch.setattr(lt.requests, "get", lambda u, **k: _Resp(404))
    rows = [["10:00 - 10:30", "手羽先センセーション", "", "A"]]
    return lt._prefetch_tt_images(rows, _FakeDB(artist), target_size=(100, 50), failures=failures)


def test_prefetch_collects_failure_entry(monkeypatch):
    """取得を試みて落ちたアー写が構造化エントリで返ること。"""
    failures = []
    cache = _prefetch(monkeypatch, _FakeArtist("手羽先センセーション", "a.jpg"), failures)

    assert cache.get("手羽先センセーション") is None
    assert len(failures) == 1
    e = failures[0]
    assert e["kind"] == "artist_photo"
    assert e["name"] == "手羽先センセーション"
    assert e["url"] == "https://example.invalid/a.jpg"
    assert e["reason"] == "fetch_failed"


def test_prefetch_without_failures_arg_behaves_as_before(monkeypatch):
    """★failures=None(既存 views 経路)でも例外にならず、戻り値は従来どおり。"""
    cache = _prefetch(monkeypatch, _FakeArtist("手羽先センセーション", "a.jpg"), None)
    assert cache.get("手羽先センセーション") is None


def test_prefetch_no_image_filename_is_not_a_failure(monkeypatch, caplog):
    """★画像未設定のアーティストは「失敗」ではない(取得を試みていない)。"""
    failures = []
    with caplog.at_level(logging.WARNING, logger="logic_timetable"):
        cache = _prefetch(monkeypatch, _FakeArtist("手羽先センセーション", None), failures)
    assert cache == {}
    assert failures == []
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_prefetch_unknown_artist_is_not_a_failure(monkeypatch):
    """DB に居ないアーティストも失敗ではない。"""
    failures = []
    cache = _prefetch(monkeypatch, None, failures)
    assert cache == {}
    assert failures == []


def test_prefetch_success_records_no_failure(monkeypatch):
    """取得に成功したら failures は空のまま。"""
    import io as _io

    import database
    from PIL import Image

    buf = _io.BytesIO()
    Image.new("RGB", (200, 200), (10, 20, 30)).save(buf, format="PNG")
    monkeypatch.setattr(database, "get_image_url", lambda fn: "https://example.invalid/a.png")
    monkeypatch.setattr(lt.requests, "get", lambda u, **k: _Resp(200, buf.getvalue()))

    failures = []
    rows = [["10:00 - 10:30", "手羽先センセーション", "", "A"]]
    cache = lt._prefetch_tt_images(
        rows, _FakeDB(_FakeArtist("手羽先センセーション", "a.png")),
        target_size=(100, 50), failures=failures,
    )
    assert cache.get("手羽先センセーション") is not None
    assert failures == []


# ---------------------------------------------------------------------------
# logic_grid: grid 側も同型(kind="artist_photo"・name はアーティスト名)
# ---------------------------------------------------------------------------
import logic_grid as lg  # noqa: E402


class _FakeArtistView:
    """ArtistView 相当(prefetch が触るのは id / name / image_filename のみ)。"""

    def __init__(self, aid, name, image_filename):
        self.id = aid
        self.name = name
        self.image_filename = image_filename


def test_grid_load_image_from_url_logs_warning(monkeypatch, caplog):
    monkeypatch.setattr(lg.requests, "get", _boom)
    with caplog.at_level(logging.WARNING, logger="logic_grid"):
        assert lg.load_image_from_url("https://example.invalid/a.jpg") is None
    msgs = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("ConnectionError" in m for m in msgs), msgs


def test_grid_load_image_from_url_empty_is_not_a_failure(caplog):
    with caplog.at_level(logging.WARNING, logger="logic_grid"):
        assert lg.load_image_from_url("") is None
        assert lg.load_image_from_url(None) is None
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_grid_load_and_downscale_logs_warning(monkeypatch, caplog):
    monkeypatch.setattr(lg.requests, "get", _boom)
    with caplog.at_level(logging.WARNING, logger="logic_grid"):
        assert lg._load_and_downscale("https://example.invalid/a.jpg") is None
    msgs = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("ConnectionError" in m for m in msgs), msgs


def test_grid_prefetch_collects_failure_entry(monkeypatch):
    import database

    monkeypatch.setattr(database, "get_image_url", lambda fn: "https://example.invalid/g.jpg")
    monkeypatch.setattr(lg, "get_image_url", lambda fn: "https://example.invalid/g.jpg")
    monkeypatch.setattr(lg.requests, "get", _boom)

    failures = []
    cache = lg._fetch_grid_images_parallel(
        [_FakeArtistView(7, "まねきケチャ", "g.jpg")], failures=failures
    )
    assert cache.get(7) is None
    assert len(failures) == 1
    e = failures[0]
    assert e["kind"] == "artist_photo"
    assert e["name"] == "まねきケチャ"
    assert e["url"] == "https://example.invalid/g.jpg"
    assert e["reason"] == "fetch_failed"


def test_grid_prefetch_without_failures_arg(monkeypatch):
    """★failures=None(既存 views 経路)でも例外にならない。"""
    monkeypatch.setattr(lg, "get_image_url", lambda fn: "https://example.invalid/g.jpg")
    monkeypatch.setattr(lg.requests, "get", _boom)
    cache = lg._fetch_grid_images_parallel([_FakeArtistView(7, "まねきケチャ", "g.jpg")])
    assert cache.get(7) is None


def test_grid_prefetch_no_image_filename_is_not_a_failure(monkeypatch, caplog):
    failures = []
    with caplog.at_level(logging.WARNING, logger="logic_grid"):
        cache = lg._fetch_grid_images_parallel(
            [_FakeArtistView(7, "まねきケチャ", None)], failures=failures
        )
    assert cache == {}
    assert failures == []
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


# ---------------------------------------------------------------------------
# utils/flyer_generator: bg / logo
# ---------------------------------------------------------------------------
import utils.flyer_generator as fg  # noqa: E402


def _default_styles():
    """本番と同じく FLYER_KEY_REGISTRY の既定で全キーを埋めた styles。

    styles={} だとフォント名が None になり get_font_path が
    os.path.basename(None) で落ちる(実運用では gather が必ず全キーを埋める)。
    """
    from models.flyer_keys import FLYER_KEY_REGISTRY

    return {e.short_key: e.default for e in FLYER_KEY_REGISTRY if e.persist}


def _flyer_kwargs(**over):
    """create_flyer_image_shadow の引数一式(描画は通るが軽い)。"""
    base = dict(
        bg_source=None, logo_source=None,
        main_source=None, styles=_default_styles(),
        date_text="2026.09.21", venue_text="会場", subtitle_text="",
        open_time="10:00", start_time="10:30",
        ticket_info_list=[], common_notes_list=[],
    )
    base.update(over)
    return base


def test_flyer_bg_failure_is_recorded(monkeypatch):
    monkeypatch.setattr(fg.requests, "get", _boom)
    failures = []
    img, _meta = fg.create_flyer_image_shadow(
        failures=failures, **_flyer_kwargs(bg_source="https://example.invalid/bg.jpg")
    )
    assert img is not None  # 背景が無くても生成は続行(挙動不変)
    kinds = [f["kind"] for f in failures]
    assert "flyer_bg" in kinds, failures
    e = next(f for f in failures if f["kind"] == "flyer_bg")
    assert e["name"] is None
    assert e["url"] == "https://example.invalid/bg.jpg"
    assert e["reason"] == "fetch_failed"


def test_flyer_logo_failure_is_recorded(monkeypatch):
    monkeypatch.setattr(fg.requests, "get", _boom)
    failures = []
    fg.create_flyer_image_shadow(
        failures=failures, **_flyer_kwargs(logo_source="https://example.invalid/logo.png")
    )
    kinds = [f["kind"] for f in failures]
    assert "flyer_logo" in kinds, failures


def test_flyer_no_bg_no_logo_is_not_a_failure(caplog):
    """★背景/ロゴ未設定は失敗ではない(ログも failure も出ない)。"""
    failures = []
    with caplog.at_level(logging.WARNING, logger="utils.flyer_generator"):
        fg.create_flyer_image_shadow(failures=failures, **_flyer_kwargs())
    assert failures == []
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_flyer_without_failures_arg_behaves_as_before(monkeypatch):
    """★failures=None(既存 views 経路)でも例外にならず画像を返す。"""
    monkeypatch.setattr(fg.requests, "get", _boom)
    img, _meta = fg.create_flyer_image_shadow(
        **_flyer_kwargs(bg_source="https://example.invalid/bg.jpg")
    )
    assert img is not None


def test_flyer_load_image_logs_warning(monkeypatch, caplog):
    monkeypatch.setattr(fg.requests, "get", _boom)
    with caplog.at_level(logging.WARNING, logger="utils.flyer_generator"):
        assert fg.load_image("https://example.invalid/x.png") is None
    msgs = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("ConnectionError" in m for m in msgs), msgs
