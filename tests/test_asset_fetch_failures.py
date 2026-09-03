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
