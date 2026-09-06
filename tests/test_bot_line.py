"""BOTTZ AI LINE Bot の純関数ユニットテスト(DB / LINE 実通信なし)。

対象: 署名検証 / メンション処理 / 名前抽出 / pending TTL / ガード。
本テストは bot.main の純関数のみを叩き、database / services は import しない
(bot.main は DB を遅延 import する設計のため import 時に本番 DB へ触れない)。
"""
from __future__ import annotations

import base64
import hashlib
import hmac

import pytest

from bot import main


# --------------------------------------------------------------------------
# 署名検証
# --------------------------------------------------------------------------
def _sign(body: bytes, secret: str) -> str:
    mac = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    return base64.b64encode(mac).decode("utf-8")


def test_verify_signature_valid():
    body = b'{"events":[]}'
    secret = "topsecret"
    assert main.verify_signature(body, _sign(body, secret), secret) is True


def test_verify_signature_wrong_signature():
    body = b'{"events":[]}'
    assert main.verify_signature(body, _sign(body, "other"), "topsecret") is False


def test_verify_signature_tampered_body():
    secret = "topsecret"
    sig = _sign(b'{"events":[]}', secret)
    assert main.verify_signature(b'{"events":[{"x":1}]}', sig, secret) is False


def test_verify_signature_missing_inputs():
    assert main.verify_signature(b"x", None, "s") is False
    assert main.verify_signature(b"x", "sig", "") is False


# --------------------------------------------------------------------------
# メンション処理
# --------------------------------------------------------------------------
def test_is_self_mentioned():
    assert main.is_self_mentioned([{"isSelf": True, "index": 0, "length": 9}]) is True
    assert main.is_self_mentioned([{"isSelf": False}]) is False
    assert main.is_self_mentioned([]) is False
    assert main.is_self_mentioned(None) is False


def test_strip_self_mentions_leading():
    text = "@BOTTZ AI バンドAのアー写更新"
    mentionees = [{"isSelf": True, "index": 0, "length": len("@BOTTZ AI")}]
    assert main.strip_self_mentions(text, mentionees).strip() == "バンドAのアー写更新"


def test_strip_self_mentions_ignores_non_self():
    text = "@誰か バンドAのアー写更新"
    mentionees = [{"isSelf": False, "index": 0, "length": 3}]
    # isSelf でないメンションは除去しない
    assert main.strip_self_mentions(text, mentionees) == text


# --------------------------------------------------------------------------
# pending TTL
# --------------------------------------------------------------------------
def test_pending_put_and_pop_within_ttl():
    store = main.PendingStore(ttl_seconds=300)
    store.put("U1", 39, "バンドA", now=1000.0)
    assert store.pop_valid("U1", now=1200.0) == (39, "バンドA", "replace")  # 200 秒後 = TTL 内
    # 消費済みなので 2 回目は None
    assert store.pop_valid("U1", now=1201.0) is None


def test_pending_expires_after_ttl():
    store = main.PendingStore(ttl_seconds=300)
    store.put("U1", 39, "バンドA", now=1000.0)
    assert store.pop_valid("U1", now=1000.0 + 301) is None  # TTL 超過


def test_pending_isolated_per_user():
    store = main.PendingStore(ttl_seconds=300)
    store.put("U1", 39, "バンドA", now=1000.0)
    assert store.pop_valid("U2", now=1000.0) is None
    assert store.pop_valid("U1", now=1000.0) == (39, "バンドA", "replace")


def test_pending_purge_expired():
    store = main.PendingStore(ttl_seconds=300)
    store.put("U1", 1, "A", now=1000.0)
    store.put("U2", 2, "B", now=1000.0)
    store.purge_expired(now=1000.0 + 301)
    assert store.pop_valid("U1", now=1000.0 + 302) is None
    assert store.pop_valid("U2", now=1000.0 + 302) is None


# --------------------------------------------------------------------------
# ガード(グループ許可リスト)
# --------------------------------------------------------------------------
def _cfg(owners=("Uowner",), groups=()):
    return main.BotConfig(
        channel_secret="s",
        channel_access_token="t",
        owner_user_ids=frozenset(owners),
        allowed_group_ids=frozenset(groups),
    )


def test_group_guard_dm_rejected():
    assert main._passes_group_guard(None, _cfg()) is False


def test_group_guard_empty_allowlist_allows_any_group():
    assert main._passes_group_guard("Gany", _cfg(groups=())) is True


def test_group_guard_ignores_static_allowlist():
    """★B-4: 静的許可リスト(ALLOWED_GROUP_IDS)によるゲートは撤去した。

    どのグループが使えるかは activation_service(オーナーが「起動」と送ったか)が決める。
    _passes_group_guard は「グループ発かどうか」だけを見る。
    """
    cfg = _cfg(groups=("Gok",))
    assert main._passes_group_guard("Gok", cfg) is True
    assert main._passes_group_guard("Gng", cfg) is True, "許可リスト外でもガードは通す"


def test_parse_id_set():
    assert main._parse_id_set("a, b ,,c") == frozenset({"a", "b", "c"})
    assert main._parse_id_set("") == frozenset()
    assert main._parse_id_set(None) == frozenset()


def test_ext_from_content_type():
    assert main._ext_from_content_type("image/png") == ".png"
    assert main._ext_from_content_type("image/webp") == ".webp"
    assert main._ext_from_content_type("image/jpeg") == ".jpg"
    assert main._ext_from_content_type("") == ".jpg"


def test_pending_default_mode_is_replace():
    """mode 省略時は従来どおり差し替え(既存の呼び出しを壊さない)。"""
    store = main.PendingStore(ttl_seconds=300)
    store.put("U1", 39, "A", now=1000.0)
    assert store.pop_valid("U1", now=1000.0) == (39, "A", main.PENDING_MODE_REPLACE)


def test_pending_can_hold_register_mode():
    store = main.PendingStore(ttl_seconds=300)
    store.put("U1", 41, "テスト太郎", now=1000.0, mode=main.PENDING_MODE_REGISTER)
    assert store.pop_valid("U1", now=1000.0) == (41, "テスト太郎",
                                                 main.PENDING_MODE_REGISTER)


def test_pending_rejects_unknown_mode():
    """想定外の mode は受け付けない(画像受信時の分岐が壊れないように)。"""
    store = main.PendingStore(ttl_seconds=300)
    with pytest.raises(ValueError):
        store.put("U1", 1, "A", now=1000.0, mode="something")


def test_pending_mode_does_not_change_ttl_behaviour():
    """mode を足しても TTL の扱いは不変。"""
    store = main.PendingStore(ttl_seconds=300)
    store.put("U1", 1, "A", now=1000.0, mode=main.PENDING_MODE_REGISTER)
    assert store.pop_valid("U1", now=1301.0) is None
