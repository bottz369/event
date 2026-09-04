"""段階B B-4 C1: グループ起動制御ストアのテスト。

Storage は全てモックする(実 Supabase Storage には触らない)。
.venv 実行想定:
    .venv/bin/python3 -m pytest tests/test_activation_service.py -v
"""
from __future__ import annotations

import json

import pytest

import services.activation_service as act


class _FakeBucket:
    """download / upload だけを持つ Storage バケットの模擬。"""

    def __init__(self, initial: bytes = None, fail_download=False, fail_upload=False):
        self.blob = initial
        self.fail_download = fail_download
        self.fail_upload = fail_upload
        self.uploads = []

    def download(self, path):
        if self.fail_download or self.blob is None:
            raise RuntimeError("not found")
        return self.blob

    def upload(self, path=None, file=None, file_options=None):
        if self.fail_upload:
            raise RuntimeError("upload failed")
        self.uploads.append((path, file, file_options))
        self.blob = file
        return path


@pytest.fixture(autouse=True)
def _fresh_cache():
    """テストごとにキャッシュを捨てる(モジュール状態の持ち越しを防ぐ)。"""
    act.reload_from_storage()
    yield
    act.reload_from_storage()


def _use(monkeypatch, bucket):
    monkeypatch.setattr(act, "_bucket", lambda: bucket)
    return bucket


def _blob(groups: dict) -> bytes:
    return json.dumps({"groups": groups}, ensure_ascii=False).encode("utf-8")


# ---------------------------------------------------------------------------
# 基本の有効化 / 無効化
# ---------------------------------------------------------------------------
def test_activate_then_is_active(monkeypatch):
    b = _use(monkeypatch, _FakeBucket(initial=_blob({})))
    assert act.is_group_active("G1") is False
    act.activate_group("G1", "Uowner")
    assert act.is_group_active("G1") is True


def test_activate_writes_through_to_storage(monkeypatch):
    """★ライトスルー: activate で Storage への書き込みが起きること。"""
    b = _use(monkeypatch, _FakeBucket(initial=_blob({})))
    act.activate_group("G1", "Uowner")

    assert len(b.uploads) == 1
    path, payload, opts = b.uploads[0]
    assert path == act.STORAGE_KEY
    assert opts["content-type"] == "application/json"
    assert opts["upsert"] == "true"

    saved = json.loads(payload.decode("utf-8"))["groups"]
    assert "G1" in saved
    assert saved["G1"]["activated_by"] == "Uowner"
    assert isinstance(saved["G1"]["activated_at"], int)


def test_deactivate_removes_and_writes(monkeypatch):
    b = _use(monkeypatch, _FakeBucket(initial=_blob({"G1": {"activated_by": "U"}})))
    assert act.is_group_active("G1") is True
    act.deactivate_group("G1")
    assert act.is_group_active("G1") is False

    saved = json.loads(b.uploads[-1][1].decode("utf-8"))["groups"]
    assert "G1" not in saved


def test_deactivate_unknown_group_does_not_write(monkeypatch):
    """存在しないグループの無効化は no-op(無駄な書き込みをしない)。"""
    b = _use(monkeypatch, _FakeBucket(initial=_blob({})))
    act.deactivate_group("G-unknown")
    assert b.uploads == []


def test_groups_are_isolated(monkeypatch):
    _use(monkeypatch, _FakeBucket(initial=_blob({})))
    act.activate_group("G1", "U")
    assert act.is_group_active("G1") is True
    assert act.is_group_active("G2") is False


@pytest.mark.parametrize("bad", [None, ""])
def test_empty_group_id_is_never_active(bad, monkeypatch):
    _use(monkeypatch, _FakeBucket(initial=_blob({"G1": {}})))
    assert act.is_group_active(bad) is False
    act.activate_group(bad, "U")  # 例外にならない
    act.deactivate_group(bad)


# ---------------------------------------------------------------------------
# Storage 読み込み
# ---------------------------------------------------------------------------
def test_loads_existing_state_from_storage(monkeypatch):
    """★再起動後も Storage の内容から復元されること。"""
    _use(monkeypatch, _FakeBucket(initial=_blob({"Gsaved": {"activated_by": "U"}})))
    assert act.is_group_active("Gsaved") is True


def test_missing_file_starts_empty(monkeypatch):
    """★ファイル未作成(初回)は空集合で安全に起動する。"""
    _use(monkeypatch, _FakeBucket(initial=None))
    assert act.is_group_active("G1") is False
    # その状態から有効化はできる
    act.activate_group("G1", "U")
    assert act.is_group_active("G1") is True


def test_download_failure_starts_empty(monkeypatch):
    """★Storage 読み失敗でも落ちず、空集合として起動する。"""
    _use(monkeypatch, _FakeBucket(initial=_blob({"G1": {}}), fail_download=True))
    assert act.is_group_active("G1") is False


@pytest.mark.parametrize("broken", [
    b"not json",
    b"[]",
    json.dumps({"groups": "notadict"}).encode("utf-8"),
    json.dumps({"other": {}}).encode("utf-8"),
])
def test_broken_json_starts_empty(broken, monkeypatch):
    _use(monkeypatch, _FakeBucket(initial=broken))
    assert act.is_group_active("G1") is False


def test_storage_is_read_once_and_cached(monkeypatch):
    """★webhook ごとに Storage を読まない(初回だけ)。"""
    calls = {"n": 0}

    class _Counting(_FakeBucket):
        def download(self, path):
            calls["n"] += 1
            return super().download(path)

    _use(monkeypatch, _Counting(initial=_blob({"G1": {}})))
    for _ in range(5):
        act.is_group_active("G1")
    assert calls["n"] == 1


# ---------------------------------------------------------------------------
# 書き込み失敗
# ---------------------------------------------------------------------------
def test_upload_failure_keeps_memory_state(monkeypatch):
    """★書き込み失敗でも例外は投げず、メモリ上は有効(再起動まで持つ)。"""
    _use(monkeypatch, _FakeBucket(initial=_blob({}), fail_upload=True))
    act.activate_group("G1", "U")  # 例外にならない
    assert act.is_group_active("G1") is True


def test_reload_discards_cache(monkeypatch):
    b = _use(monkeypatch, _FakeBucket(initial=_blob({})))
    act.activate_group("G1", "U")
    assert act.is_group_active("G1") is True
    # Storage 側が別プロセスで書き換わった状況を模す
    b.blob = _blob({"G2": {}})
    act.reload_from_storage()
    assert act.is_group_active("G1") is False
    assert act.is_group_active("G2") is True
