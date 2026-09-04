"""段階B B-3: LINE Bot 会話フロー(C2〜C4)のテスト。

実 LINE 送信 / 実 Storage / 実生成はすべて monkeypatch する。
.venv 実行想定:
    .venv/bin/python3 -m pytest tests/test_bot_flow.py -v
"""
from __future__ import annotations

import datetime
import json

import pytest

from bot import main as bm
from models.event import EventOption


def _ev(pid, title, y=2026, m=9, d=21):
    return EventOption(project_id=pid, title=title, event_date=datetime.date(y, m, d))


# ---------------------------------------------------------------------------
# C2: reply_messages / quickreply / postback data
# ---------------------------------------------------------------------------
def test_reply_messages_sends_payload_as_is(monkeypatch):
    sent = {}

    class _R:
        status_code = 200
        text = ""

    def _post(url, headers=None, json=None, timeout=None):
        sent.update(url=url, headers=headers, body=json, timeout=timeout)
        return _R()

    monkeypatch.setattr(bm.requests, "post", _post)
    msgs = [{"type": "text", "text": "a"}, {"type": "image", "originalContentUrl": "u",
                                            "previewImageUrl": "p"}]
    bm.reply_messages("TOKEN", msgs, "AT")

    assert sent["url"] == bm.LINE_REPLY_ENDPOINT
    assert sent["headers"]["Authorization"] == "Bearer AT"
    assert sent["body"] == {"replyToken": "TOKEN", "messages": msgs}


def test_reply_text_is_a_thin_wrapper(monkeypatch):
    captured = {}
    monkeypatch.setattr(bm, "reply_messages",
                        lambda tok, msgs, at, timeout=15: captured.update(msgs=msgs))
    bm.reply_text("T", "hello", "AT")
    assert captured["msgs"] == [{"type": "text", "text": "hello"}]


def test_reply_messages_noop_without_token(monkeypatch):
    monkeypatch.setattr(bm.requests, "post",
                        lambda *a, **k: pytest.fail("must not send"))
    bm.reply_messages("", [{"type": "text", "text": "x"}], "AT")
    bm.reply_messages("T", [], "AT")


def test_reply_messages_truncates_over_five(monkeypatch):
    sent = {}

    class _R:
        status_code = 200
        text = ""

    monkeypatch.setattr(bm.requests, "post",
                        lambda url, headers=None, json=None, timeout=None:
                        (sent.update(body=json), _R())[1])
    bm.reply_messages("T", [{"type": "text", "text": str(i)} for i in range(8)], "AT")
    assert len(sent["body"]["messages"]) == 5


def test_quickreply_shape_and_limits():
    events = [_ev(i, "イベント名がとても長いタイトルです%d" % i, d=10 + i) for i in range(1, 16)]
    msg = bm.build_event_quickreply(events, "手羽先センセーション")

    items = msg["quickReply"]["items"]
    assert msg["type"] == "text"
    assert len(items) == bm.QUICKREPLY_MAX_ITEMS, "items は 13 件までに丸める"
    for it in items:
        assert it["type"] == "action"
        a = it["action"]
        assert a["type"] == "postback"
        assert len(a["label"]) <= bm.QUICKREPLY_LABEL_MAX, a["label"]
        assert len(a["data"].encode("utf-8")) <= bm.POSTBACK_DATA_MAX_BYTES
        assert a["data"].startswith("regen|pid=")


def test_quickreply_label_includes_date():
    msg = bm.build_event_quickreply([_ev(1, "夏フェス", m=9, d=21)], "A")
    assert msg["quickReply"]["items"][0]["action"]["label"].startswith("09/21")


def test_quickreply_handles_none_date():
    msg = bm.build_event_quickreply(
        [EventOption(project_id=1, title="日付未定イベント", event_date=None)], "A"
    )
    assert "日付未定" in msg["quickReply"]["items"][0]["action"]["label"]


def test_postback_data_roundtrip():
    data = bm.build_postback_data(42, "手羽先センセーション")
    assert bm.parse_postback_data(data) == (42, "手羽先センセーション")


def test_postback_data_truncates_long_name_without_breaking_utf8():
    long_name = "あ" * 300
    data = bm.build_postback_data(7, long_name)
    assert len(data.encode("utf-8")) <= bm.POSTBACK_DATA_MAX_BYTES
    pid, artist = bm.parse_postback_data(data)
    assert pid == 7
    assert artist and all(c == "あ" for c in artist), "UTF-8 の途中で切れていない"


@pytest.mark.parametrize("bad", ["", None, "other|pid=1", "regen|artist=x", "regen|pid=abc"])
def test_postback_data_invalid_returns_none(bad):
    assert bm.parse_postback_data(bad) is None


# ---------------------------------------------------------------------------
# C2: Storage アップロード / preview
# ---------------------------------------------------------------------------
def test_upload_generated_png_uses_fixed_key_and_cache_buster(monkeypatch):
    import database

    seen = {}
    monkeypatch.setattr(database, "upload_image_to_supabase",
                        lambda f, name: seen.setdefault("name", name) or name)
    monkeypatch.setattr(database, "get_image_url", lambda n: "https://cdn.invalid/%s" % n)

    url = bm.upload_generated_png(b"PNGDATA", 39, "grid", now=1234567890)
    assert seen["name"] == "generated/39/flyer_grid.png", "キーは (pid, variant) 固定=上書き"
    assert url == "https://cdn.invalid/generated/39/flyer_grid.png?t=1234567890"


def test_upload_generated_png_returns_none_on_failure(monkeypatch):
    import database

    monkeypatch.setattr(database, "upload_image_to_supabase", lambda f, name: None)
    monkeypatch.setattr(database, "get_image_url", lambda n: None)
    assert bm.upload_generated_png(b"X", 1, "tt") is None


def test_build_preview_png_downscales():
    import io as _io

    from PIL import Image

    buf = _io.BytesIO()
    Image.new("RGB", (1080, 1350), (1, 2, 3)).save(buf, format="PNG")
    preview = bm.build_preview_png(buf.getvalue(), max_edge=240)
    im = Image.open(_io.BytesIO(preview))
    assert max(im.size) <= 240
    assert len(preview) < len(buf.getvalue())


def test_build_preview_png_falls_back_on_error():
    assert bm.build_preview_png(b"not an image") == b"not an image"


# ---------------------------------------------------------------------------
# C3: render_flyer_set_for_project
# ---------------------------------------------------------------------------
def _stub_generation(monkeypatch, results):
    """generation_service.render_flyer_png_for_project を差し替える。

    results: {variant: (png_or_None, [failures...])}
    """
    import services.generation_service as gs

    def _fake(pid, variant="grid", failures=None):
        png, fails = results.get(variant, (None, []))
        if failures is not None:
            failures.extend(fails)
        return png

    monkeypatch.setattr(gs, "render_flyer_png_for_project", _fake)


def _stub_storage(monkeypatch):
    monkeypatch.setattr(bm, "upload_generated_png",
                        lambda png, pid, variant, now=None: "https://cdn.invalid/%d_%s.png" % (pid, variant))
    monkeypatch.setattr(bm, "build_preview_png", lambda png, max_edge=240: b"PREVIEW")


def test_flyer_set_returns_two_images_and_merged_failures(monkeypatch):
    _stub_generation(monkeypatch, {
        "grid": (b"GRIDPNG", [{"kind": "artist_photo", "name": "A", "url": "u", "reason": "fetch_failed"}]),
        "tt": (b"TTPNG", [{"kind": "flyer_bg", "name": None, "url": "b", "reason": "fetch_failed"}]),
    })
    _stub_storage(monkeypatch)

    msgs, failures = bm.render_flyer_set_for_project(39)
    assert len(msgs) == 2
    assert all(m["type"] == "image" for m in msgs)
    assert msgs[0]["originalContentUrl"] == "https://cdn.invalid/39_grid.png"
    assert msgs[1]["originalContentUrl"] == "https://cdn.invalid/39_tt.png"
    assert sorted(f["kind"] for f in failures) == ["artist_photo", "flyer_bg"], failures


def test_flyer_set_skips_unavailable_variant(monkeypatch):
    """★片方が生成不能(None)なら、その variant はスキップして残りを返す。"""
    _stub_generation(monkeypatch, {"grid": (b"GRIDPNG", []), "tt": (None, [])})
    _stub_storage(monkeypatch)

    msgs, failures = bm.render_flyer_set_for_project(39)
    assert len(msgs) == 1
    assert msgs[0]["originalContentUrl"].endswith("_grid.png")
    assert failures == []


def test_flyer_set_returns_empty_when_all_fail(monkeypatch):
    _stub_generation(monkeypatch, {"grid": (None, []), "tt": (None, [])})
    _stub_storage(monkeypatch)
    msgs, _ = bm.render_flyer_set_for_project(39)
    assert msgs == []


def test_flyer_set_survives_generation_exception(monkeypatch):
    """生成が例外でも Webhook を落とさず、もう片方を返す。"""
    import services.generation_service as gs

    def _fake(pid, variant="grid", failures=None):
        if variant == "grid":
            raise RuntimeError("boom")
        return b"TTPNG"

    monkeypatch.setattr(gs, "render_flyer_png_for_project", _fake)
    _stub_storage(monkeypatch)
    msgs, _ = bm.render_flyer_set_for_project(39)
    assert len(msgs) == 1
    assert msgs[0]["originalContentUrl"].endswith("_tt.png")


def test_flyer_set_skips_when_upload_fails(monkeypatch):
    _stub_generation(monkeypatch, {"grid": (b"G", []), "tt": (b"T", [])})
    monkeypatch.setattr(bm, "upload_generated_png", lambda *a, **k: None)
    msgs, _ = bm.render_flyer_set_for_project(39)
    assert msgs == []


# ---------------------------------------------------------------------------
# C3: 失敗の文言化
# ---------------------------------------------------------------------------
def test_failure_notice_lists_artists_and_assets():
    notice = bm.build_failure_notice([
        {"kind": "artist_photo", "name": "手羽先センセーション", "url": "u", "reason": "fetch_failed"},
        {"kind": "artist_photo", "name": "手羽先センセーション", "url": "u", "reason": "fetch_failed"},
        {"kind": "flyer_bg", "name": None, "url": "b", "reason": "fetch_failed"},
    ])
    assert "手羽先センセーション" in notice
    assert notice.count("手羽先センセーション") == 1, "重複は 1 回だけ"
    assert "背景画像" in notice


def test_failure_notice_none_when_empty():
    assert bm.build_failure_notice([]) is None
    assert bm.build_failure_notice([{"kind": "unknown"}]) is None


# ---------------------------------------------------------------------------
# C4: handle_event の配線(ガード / トリガー2 / postback / バックグラウンド)
# ---------------------------------------------------------------------------
GROUP = "Gallowed"
USER = "Usomeone"


def _config(allowed=(GROUP,), owners=()):
    return bm.BotConfig(
        channel_secret="s",
        channel_access_token="AT",
        owner_user_ids=frozenset(owners),
        allowed_group_ids=frozenset(allowed),
    )


def _text_event(text, mentioned=True, group=GROUP, user=USER):
    mentionees = [{"index": 0, "length": 4, "isSelf": True}] if mentioned else []
    return {
        "type": "message",
        "replyToken": "RT",
        "source": {"type": "group", "groupId": group, "userId": user},
        "message": {"type": "text", "text": text, "mention": {"mentionees": mentionees}},
    }


@pytest.fixture
def sent(monkeypatch):
    """reply_messages を捕捉する。"""
    box = []
    monkeypatch.setattr(bm, "reply_messages",
                        lambda tok, msgs, at, timeout=15: box.append((tok, msgs)))
    return box


def test_owner_gate_removed_any_group_member_can_use(sent, monkeypatch):
    """★OWNER ゲート撤去: 許可グループ内なら owner でなくても反応する。"""
    monkeypatch.setattr(bm, "_reply_event_choices",
                        lambda tok, artist, config, prefix=None: sent.append(("choices", artist)))
    bm.handle_event(_text_event("@Bot 手羽先の最新"), _config(owners=("someone-else",)))
    assert ("choices", "手羽先") in sent


def test_text_without_mention_is_ignored(sent):
    """★メンション無しテキストは無反応(誤爆防止)。"""
    bm.handle_event(_text_event("手羽先の最新", mentioned=False), _config())
    assert sent == []


def test_group_not_allowed_is_ignored(sent):
    """★許可グループ外は無反応。"""
    bm.handle_event(_text_event("@Bot 手羽先の最新", group="Gother"), _config())
    assert sent == []


def test_dm_is_ignored(sent):
    ev = _text_event("@Bot 手羽先の最新")
    ev["source"] = {"type": "user", "userId": USER}
    bm.handle_event(ev, _config())
    assert sent == []


def test_trigger2_latest_marker_lists_events(sent, monkeypatch):
    """★トリガー2: 「〇〇の最新」で写真を待たずイベント選択へ。"""
    import services.event_service as es

    monkeypatch.setattr(es, "list_recent_events_for_artist",
                        lambda name, **k: [_ev(39, "秋フェス")])
    bm.handle_event(_text_event("@Bot 手羽先センセーションの最新"), _config())

    assert len(sent) == 1
    _tok, msgs = sent[0]
    assert msgs[-1]["quickReply"]["items"][0]["action"]["data"] == \
        bm.build_postback_data(39, "手羽先センセーション")


def test_trigger2_regenerate_marker_also_works(sent, monkeypatch):
    import services.event_service as es

    monkeypatch.setattr(es, "list_recent_events_for_artist",
                        lambda name, **k: [_ev(1, "E")])
    bm.handle_event(_text_event("@Bot 手羽先の再生成"), _config())
    assert len(sent) == 1


def test_trigger2_zero_events_replies_message(sent, monkeypatch):
    """★0 件なら「見つかりませんでした」で終了。"""
    import services.event_service as es

    monkeypatch.setattr(es, "list_recent_events_for_artist", lambda name, **k: [])
    bm.handle_event(_text_event("@Bot 手羽先の最新"), _config())
    _tok, msgs = sent[0]
    assert msgs[0]["type"] == "text"
    assert "見つかりませんでした" in msgs[0]["text"]


def test_trigger1_still_enters_pending(sent, monkeypatch):
    """★トリガー1 は従来どおり写真待ちに入る(挙動不変)。"""
    bm.pending_store._data.clear()
    bm.handle_event(_text_event("@Bot 手羽先のアー写更新"), _config())
    assert bm.pending_store.pop_valid(USER, __import__("time").time()) == "手羽先"


def test_trigger1_after_update_lists_events(sent, monkeypatch):
    """★アー写更新成功 → そのままイベント選択ボタンを出す。"""
    import services.event_service as es

    bm.pending_store._data.clear()
    bm.pending_store.put(USER, "手羽先", __import__("time").time())
    monkeypatch.setattr(bm, "download_image", lambda mid, at, timeout=30: (b"IMG", "image/jpeg"))
    monkeypatch.setattr(bm, "update_artist_photo",
                        lambda name, b, ct: (True, "手羽先 のアー写を更新しました"))
    monkeypatch.setattr(es, "list_recent_events_for_artist",
                        lambda name, **k: [_ev(39, "秋フェス")])

    ev = {
        "type": "message", "replyToken": "RT",
        "source": {"type": "group", "groupId": GROUP, "userId": USER},
        "message": {"type": "image", "id": "m1"},
    }
    bm.handle_event(ev, _config())

    _tok, msgs = sent[0]
    assert msgs[0]["text"].startswith("手羽先 のアー写を更新しました")
    assert "quickReply" in msgs[-1]


def test_trigger1_update_failure_does_not_list_events(sent, monkeypatch):
    bm.pending_store._data.clear()
    bm.pending_store.put(USER, "居ない人", __import__("time").time())
    monkeypatch.setattr(bm, "download_image", lambda mid, at, timeout=30: (b"IMG", "image/jpeg"))
    monkeypatch.setattr(bm, "update_artist_photo", lambda name, b, ct: (False, "「居ない人」が見つかりません"))

    ev = {
        "type": "message", "replyToken": "RT",
        "source": {"type": "group", "groupId": GROUP, "userId": USER},
        "message": {"type": "image", "id": "m1"},
    }
    bm.handle_event(ev, _config())
    _tok, msgs = sent[0]
    assert msgs == [{"type": "text", "text": "「居ない人」が見つかりません"}]


# ---------------------------------------------------------------------------
# C4: postback
# ---------------------------------------------------------------------------
def _postback_event(data, group=GROUP):
    return {
        "type": "postback",
        "replyToken": "RT",
        "source": {"type": "group", "groupId": group, "userId": USER},
        "postback": {"data": data},
    }


def test_postback_spawns_background_thread(monkeypatch):
    """★重い生成は別スレッド。handle_event は即座に戻る。"""
    spawned = {}

    def _spawn(pid, artist, tok, config):
        spawned.update(pid=pid, artist=artist, token=tok)

        class _T:
            pass
        return _T()

    monkeypatch.setattr(bm, "_spawn_regeneration", _spawn)
    bm.handle_event(_postback_event(bm.build_postback_data(39, "手羽先")), _config())
    assert spawned == {"pid": 39, "artist": "手羽先", "token": "RT"}


def test_postback_thread_actually_replies(monkeypatch, sent):
    """thread が実際に 2 枚 + 警告を reply すること(join して確認)。"""
    monkeypatch.setattr(bm, "render_flyer_set_for_project", lambda pid: (
        [bm.build_image_message("https://a/1.png", "https://a/1p.png"),
         bm.build_image_message("https://a/2.png", "https://a/2p.png")],
        [{"kind": "artist_photo", "name": "手羽先", "url": "u", "reason": "fetch_failed"}],
    ))
    t = bm._spawn_regeneration(39, "手羽先", "RT", _config())
    t.join(timeout=5)
    assert not t.is_alive()

    _tok, msgs = sent[0]
    assert len(msgs) == 3, msgs
    assert [m["type"] for m in msgs] == ["image", "image", "text"]
    assert "手羽先" in msgs[2]["text"]


def test_postback_thread_replies_failure_when_nothing_generated(monkeypatch, sent):
    monkeypatch.setattr(bm, "render_flyer_set_for_project", lambda pid: ([], []))
    t = bm._spawn_regeneration(39, "A", "RT", _config())
    t.join(timeout=5)
    _tok, msgs = sent[0]
    assert msgs[0]["type"] == "text"
    assert "生成できませんでした" in msgs[0]["text"]


def test_postback_invalid_data_is_ignored(monkeypatch):
    monkeypatch.setattr(bm, "_spawn_regeneration",
                        lambda *a, **k: pytest.fail("must not spawn"))
    bm.handle_event(_postback_event("garbage"), _config())


def test_postback_group_guard_applies(monkeypatch):
    monkeypatch.setattr(bm, "_spawn_regeneration",
                        lambda *a, **k: pytest.fail("must not spawn"))
    bm.handle_event(_postback_event(bm.build_postback_data(1, "A"), group="Gother"), _config())


# ---------------------------------------------------------------------------
# C4: webhook レベル(callback は 200 を即返す)
# ---------------------------------------------------------------------------
import base64 as _b64  # noqa: E402
import hashlib as _hashlib  # noqa: E402
import hmac as _hmac  # noqa: E402
import time as _time  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

SECRET = "test-channel-secret"


def _signed_post(client, payload: dict):
    body = json.dumps(payload).encode("utf-8")
    sig = _b64.b64encode(
        _hmac.new(SECRET.encode("utf-8"), body, _hashlib.sha256).digest()
    ).decode("ascii")
    return client.post("/callback", content=body,
                       headers={"X-Line-Signature": sig, "Content-Type": "application/json"})


@pytest.fixture
def line_env(monkeypatch):
    monkeypatch.setenv("LINE_CHANNEL_SECRET", SECRET)
    monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "AT")
    monkeypatch.setenv("LINE_ALLOWED_GROUP_IDS", GROUP)
    monkeypatch.setenv("LINE_OWNER_USER_IDS", "")
    return TestClient(bm.app)


def test_callback_returns_200_immediately_for_postback(line_env, monkeypatch):
    """★postback の重い生成はバックグラウンド。callback は待たずに 200 を返す。"""
    started = {}
    release = []

    def _slow(pid, artist, tok, config):
        started["pid"] = pid

        def _work():
            _time.sleep(2.0)  # 生成が重い状況を模す
            release.append(True)

        import threading
        t = threading.Thread(target=_work, daemon=True)
        t.start()
        return t

    monkeypatch.setattr(bm, "_spawn_regeneration", _slow)

    t0 = _time.time()
    r = _signed_post(line_env, {"events": [_postback_event(bm.build_postback_data(39, "A"))]})
    elapsed = _time.time() - t0

    assert r.status_code == 200
    assert started["pid"] == 39
    assert elapsed < 1.0, "生成完了を待っていない(elapsed=%.2fs)" % elapsed
    assert release == [], "callback 応答時点ではまだ生成中"


def test_callback_rejects_bad_signature(line_env):
    r = line_env.post("/callback", content=b'{"events":[]}',
                      headers={"X-Line-Signature": "bogus"})
    assert r.status_code == 400
