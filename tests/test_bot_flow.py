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


def test_event_quickreply_shape_and_limits():
    events = [_ev(i, "イベント名がとても長いタイトルです%d" % i, d=10 + i) for i in range(1, 16)]
    msg = bm.build_event_quickreply(events, bm.FLOW_REPLACE, page=0, has_more=True)

    items = msg["quickReply"]["items"]
    assert msg["type"] == "text"
    assert "差し替え" in msg["text"]
    assert len(items) == bm.QUICKREPLY_MAX_ITEMS, "12 件 + ページングボタン = 13"
    for it in items:
        a = it["action"]
        assert a["type"] == "postback"
        assert len(a["label"]) <= bm.QUICKREPLY_LABEL_MAX, a["label"]
        assert len(a["data"].encode("utf-8")) <= bm.POSTBACK_DATA_MAX_BYTES
    assert items[-1]["action"]["label"] == "さらに前のイベントを表示"
    assert items[-1]["action"]["data"] == "more_evt|flow=replace|page=1"


def test_event_quickreply_without_more_has_no_paging_button():
    msg = bm.build_event_quickreply([_ev(1, "A")], bm.FLOW_GET, page=0, has_more=False)
    items = msg["quickReply"]["items"]
    assert len(items) == 1
    assert items[0]["action"]["data"] == "evt|flow=get|pid=1"
    assert "フライヤー" in msg["text"]


def test_event_quickreply_label_includes_date():
    msg = bm.build_event_quickreply([_ev(1, "夏フェス", m=9, d=21)], bm.FLOW_GET)
    assert msg["quickReply"]["items"][0]["action"]["label"].startswith("09/21")


def test_event_quickreply_handles_none_date():
    msg = bm.build_event_quickreply(
        [EventOption(project_id=1, title="日付未定イベント", event_date=None)], bm.FLOW_GET
    )
    assert "日付未定" in msg["quickReply"]["items"][0]["action"]["label"]


def test_artist_quickreply_shape_and_paging():
    artists = ["アーティスト名がとても長い場合のラベル丸め確認%02d" % i for i in range(15)]
    msg = bm.build_artist_quickreply(39, artists, page=0, has_more=True)
    items = msg["quickReply"]["items"]
    assert len(items) == bm.QUICKREPLY_MAX_ITEMS
    for it in items:
        assert len(it["action"]["label"]) <= bm.QUICKREPLY_LABEL_MAX
    assert items[-1]["action"]["data"] == "more_art|pid=39|page=1"
    assert items[-1]["action"]["label"] == "さらに表示"


def test_artist_quickreply_without_more():
    msg = bm.build_artist_quickreply(39, ["手羽先センセーション"], has_more=False)
    items = msg["quickReply"]["items"]
    assert len(items) == 1
    assert items[0]["action"]["data"] == "art|pid=39|artist=手羽先センセーション"


# --- postback data の 4 種別 ---
def test_postback_data_roundtrip_event():
    d = bm.build_postback_data(bm.ACTION_EVENT, flow=bm.FLOW_REPLACE, pid=42)
    assert bm.parse_postback_data(d) == {"action": "evt", "flow": "replace", "pid": 42}


def test_postback_data_roundtrip_artist():
    d = bm.build_postback_data(bm.ACTION_ARTIST, pid=42, artist="手羽先センセーション")
    assert bm.parse_postback_data(d) == {
        "action": "art", "pid": 42, "artist": "手羽先センセーション"
    }


def test_postback_data_roundtrip_paging():
    d = bm.build_postback_data(bm.ACTION_MORE_EVENT, flow=bm.FLOW_GET, page=2)
    assert bm.parse_postback_data(d) == {"action": "more_evt", "flow": "get", "page": 2}
    d2 = bm.build_postback_data(bm.ACTION_MORE_ARTIST, pid=7, page=1)
    assert bm.parse_postback_data(d2) == {"action": "more_art", "pid": 7, "page": 1}


def test_postback_data_truncates_long_name_without_breaking_utf8():
    long_name = "あ" * 300
    d = bm.build_postback_data(bm.ACTION_ARTIST, pid=7, artist=long_name)
    assert len(d.encode("utf-8")) <= bm.POSTBACK_DATA_MAX_BYTES
    parsed = bm.parse_postback_data(d)
    assert parsed["pid"] == 7
    assert parsed["artist"] and all(c == "あ" for c in parsed["artist"]), "UTF-8 が壊れていない"


@pytest.mark.parametrize("bad", [
    "", None, "garbage", "regen|pid=1",
    "evt|flow=replace",            # pid 欠落
    "evt|pid=1",                   # flow 欠落
    "evt|flow=bogus|pid=1",        # 未知 flow
    "evt|flow=get|pid=abc",        # pid が数値でない
    "art|pid=1",                   # artist 欠落
    "more_art|pid=1",              # page 欠落
])
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
# B-3.1 C3: handle_event の配線(完全ボタン対話)
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


def _postback_event(data, group=GROUP, user=USER):
    return {
        "type": "postback",
        "replyToken": "RT",
        "source": {"type": "group", "groupId": group, "userId": user},
        "postback": {"data": data},
    }


def _image_event(group=GROUP, user=USER):
    return {
        "type": "message", "replyToken": "RT",
        "source": {"type": "group", "groupId": group, "userId": user},
        "message": {"type": "image", "id": "m1"},
    }


@pytest.fixture
def sent(monkeypatch):
    box = []
    monkeypatch.setattr(bm, "reply_messages",
                        lambda tok, msgs, at, timeout=15: box.append((tok, msgs)))
    return box


@pytest.fixture
def stub_events(monkeypatch):
    """event_service を差し替える。既定は 1 ページ分・has_more=False。"""
    import services.event_service as es

    state = {"events": [_ev(39, "秋フェス")], "ev_more": False,
             "artists": ["手羽先センセーション"], "art_more": False}
    monkeypatch.setattr(es, "list_recent_events",
                        lambda limit=12, page=0, today=None: (state["events"], state["ev_more"]))
    monkeypatch.setattr(es, "list_event_artists",
                        lambda pid, limit=12, page=0: (state["artists"], state["art_more"]))
    return state


# --- 入口(テキスト) ---
def test_replace_marker_lists_events(sent, stub_events):
    """★「アー写変更」だけで(名前なしで)イベントボタンが出る。"""
    bm.handle_event(_text_event("@Bot アー写変更"), _config())
    _tok, msgs = sent[0]
    assert "差し替え" in msgs[0]["text"]
    assert msgs[0]["quickReply"]["items"][0]["action"]["data"] == "evt|flow=replace|pid=39"


def test_get_marker_lists_events(sent, stub_events):
    """★「フライヤー」だけでイベントボタンが出る。"""
    bm.handle_event(_text_event("@Bot フライヤー"), _config())
    _tok, msgs = sent[0]
    assert msgs[0]["quickReply"]["items"][0]["action"]["data"] == "evt|flow=get|pid=39"


@pytest.mark.parametrize("marker", ["アー写変更", "アー写差し替え", "写真変更", "写真差し替え", "アー写更新"])
def test_replace_markers(marker, sent, stub_events):
    bm.handle_event(_text_event("@Bot " + marker), _config())
    assert sent[0][1][0]["quickReply"]["items"][0]["action"]["data"].startswith("evt|flow=replace")


@pytest.mark.parametrize("marker", ["最新", "フライヤー", "再生成"])
def test_get_markers(marker, sent, stub_events):
    bm.handle_event(_text_event("@Bot " + marker), _config())
    assert sent[0][1][0]["quickReply"]["items"][0]["action"]["data"].startswith("evt|flow=get")


def test_event_list_has_more_adds_paging_button(sent, stub_events):
    """★次ページがあるときだけ【さらに前のイベントを表示】が付く。"""
    stub_events["ev_more"] = True
    bm.handle_event(_text_event("@Bot アー写変更"), _config())
    items = sent[0][1][0]["quickReply"]["items"]
    assert items[-1]["action"]["data"] == "more_evt|flow=replace|page=1"


def test_unknown_text_replies_usage(sent, stub_events):
    bm.handle_event(_text_event("@Bot こんにちは"), _config())
    assert "使い方" in sent[0][1][0]["text"]


def test_text_without_mention_is_ignored(sent, stub_events):
    """★メンション無しテキストは無反応(誤爆防止)。"""
    bm.handle_event(_text_event("アー写変更", mentioned=False), _config())
    assert sent == []


def test_unknown_group_gets_not_activated_hint(sent, stub_events, activation):
    """★B-4: 静的許可リストは撤去された。未起動グループは「無反応」ではなく
    「まだ起動していません」のヒントを返す(招待された人が次にどうすればいいか分かる)。
    """
    bm.handle_event(_text_event("@Bot アー写変更", group="Gother"), _config())
    assert sent[0][1][0]["text"] == bm.MSG_NOT_ACTIVATED


def test_dm_is_ignored(sent, stub_events):
    ev = _text_event("@Bot アー写変更")
    ev["source"] = {"type": "user", "userId": USER}
    bm.handle_event(ev, _config())
    assert sent == []


def test_owner_gate_removed_any_group_member_can_use(sent, stub_events):
    """★OWNER ゲート撤去: 許可グループ内なら owner でなくても反応する。"""
    bm.handle_event(_text_event("@Bot アー写変更"), _config(owners=("someone-else",)))
    assert len(sent) == 1


def test_zero_events_replies_message(sent, stub_events):
    stub_events["events"] = []
    bm.handle_event(_text_event("@Bot アー写変更"), _config())
    assert "見つかりませんでした" in sent[0][1][0]["text"]


# --- postback: イベント選択 ---
def test_evt_get_spawns_regeneration(monkeypatch, stub_events):
    """★flow=get のイベント押下 → バックグラウンド生成。"""
    spawned = {}
    monkeypatch.setattr(bm, "_spawn_regeneration",
                        lambda pid, tok, cfg: spawned.update(pid=pid, token=tok))
    bm.handle_event(_postback_event("evt|flow=get|pid=39"), _config())
    assert spawned == {"pid": 39, "token": "RT"}


def test_evt_replace_lists_artists(sent, stub_events):
    """★flow=replace のイベント押下 → アーティストボタン。"""
    stub_events["artists"] = ["手羽先センセーション", "まねきケチャ"]
    bm.handle_event(_postback_event("evt|flow=replace|pid=39"), _config())
    _tok, msgs = sent[0]
    assert "どのアーティスト" in msgs[0]["text"]
    datas = [i["action"]["data"] for i in msgs[0]["quickReply"]["items"]]
    assert datas == ["art|pid=39|artist=手羽先センセーション", "art|pid=39|artist=まねきケチャ"]


def test_evt_replace_with_many_artists_has_paging(sent, stub_events):
    """★13 を超えるイベント(29 組など)では【さらに表示】が出る。"""
    stub_events["artists"] = ["A%02d" % i for i in range(12)]
    stub_events["art_more"] = True
    bm.handle_event(_postback_event("evt|flow=replace|pid=13"), _config())
    items = sent[0][1][0]["quickReply"]["items"]
    assert len(items) == 13
    assert items[-1]["action"]["data"] == "more_art|pid=13|page=1"


def test_evt_replace_with_no_artists(sent, stub_events):
    stub_events["artists"] = []
    bm.handle_event(_postback_event("evt|flow=replace|pid=39"), _config())
    assert "出演アーティストが登録されていません" in sent[0][1][0]["text"]


# --- postback: ページング ---
def test_more_evt_returns_next_page(sent, stub_events, monkeypatch):
    import services.event_service as es

    seen = {}
    monkeypatch.setattr(es, "list_recent_events",
                        lambda limit=12, page=0, today=None: (seen.update(page=page) or
                                                              ([_ev(1, "E")], False)))
    bm.handle_event(_postback_event("more_evt|flow=replace|page=2"), _config())
    assert seen["page"] == 2
    assert sent[0][1][0]["quickReply"]["items"][0]["action"]["data"] == "evt|flow=replace|pid=1"


def test_more_art_returns_next_page(sent, stub_events, monkeypatch):
    import services.event_service as es

    seen = {}
    monkeypatch.setattr(es, "list_event_artists",
                        lambda pid, limit=12, page=0: (seen.update(pid=pid, page=page) or
                                                       (["Z"], False)))
    bm.handle_event(_postback_event("more_art|pid=13|page=1"), _config())
    assert seen == {"pid": 13, "page": 1}
    assert sent[0][1][0]["quickReply"]["items"][0]["action"]["data"] == "art|pid=13|artist=Z"


# --- postback: アーティスト選択 → pending ---
def test_art_puts_pending_and_asks_for_image(sent, stub_events):
    """★art 押下 → pending に (pid, artist) を積み、画像を要求する。"""
    bm.pending_store._data.clear()
    bm.handle_event(_postback_event("art|pid=39|artist=手羽先センセーション"), _config())

    assert bm.pending_store.pop_valid(USER, _time.time()) == (39, "手羽先センセーション")
    assert "新しい画像を送ってください" in sent[0][1][0]["text"]


def test_postback_invalid_data_is_ignored(monkeypatch, stub_events):
    monkeypatch.setattr(bm, "_spawn_regeneration",
                        lambda *a, **k: pytest.fail("must not spawn"))
    bm.handle_event(_postback_event("garbage"), _config())


def test_postback_group_guard_applies(monkeypatch, stub_events):
    monkeypatch.setattr(bm, "_spawn_regeneration",
                        lambda *a, **k: pytest.fail("must not spawn"))
    bm.handle_event(_postback_event("evt|flow=get|pid=1", group="Gother"), _config())


# --- 画像受信 → 更新 → 2 枚 ---
def test_image_spawns_photo_update(monkeypatch, stub_events):
    """★画像受信は pending から (pid, artist) を取り、バックグラウンドへ。"""
    bm.pending_store._data.clear()
    bm.pending_store.put(USER, 39, "手羽先", _time.time())
    spawned = {}
    monkeypatch.setattr(bm, "_spawn_photo_update",
                        lambda pid, artist, mid, tok, cfg:
                        spawned.update(pid=pid, artist=artist, mid=mid, token=tok))

    bm.handle_event(_image_event(), _config())
    assert spawned == {"pid": 39, "artist": "手羽先", "mid": "m1", "token": "RT"}


def test_image_without_pending_is_ignored(monkeypatch, stub_events):
    bm.pending_store._data.clear()
    monkeypatch.setattr(bm, "_spawn_photo_update",
                        lambda *a, **k: pytest.fail("must not spawn"))
    bm.handle_event(_image_event(), _config())


def test_photo_update_worker_replies_text_and_two_images(monkeypatch, sent):
    """★1 回の reply に [更新テキスト + grid + tt] をまとめて送る。"""
    monkeypatch.setattr(bm, "download_image", lambda mid, at, timeout=30: (b"IMG", "image/jpeg"))
    monkeypatch.setattr(bm, "update_artist_photo",
                        lambda name, b, ct: (True, "手羽先 のアー写を更新しました"))
    monkeypatch.setattr(bm, "render_flyer_set_for_project", lambda pid: (
        [bm.build_image_message("https://a/1.png", "https://a/1p.png"),
         bm.build_image_message("https://a/2.png", "https://a/2p.png")],
        [],
    ))
    t = bm._spawn_photo_update(39, "手羽先", "m1", "RT", _config())
    t.join(timeout=5)
    assert not t.is_alive()

    _tok, msgs = sent[0]
    assert [m["type"] for m in msgs] == ["text", "image", "image"]
    assert msgs[0]["text"] == "手羽先 のアー写を更新しました"


def test_photo_update_worker_appends_failure_notice(monkeypatch, sent):
    monkeypatch.setattr(bm, "download_image", lambda mid, at, timeout=30: (b"IMG", "image/jpeg"))
    monkeypatch.setattr(bm, "update_artist_photo", lambda name, b, ct: (True, "更新しました"))
    monkeypatch.setattr(bm, "render_flyer_set_for_project", lambda pid: (
        [bm.build_image_message("https://a/1.png", "https://a/1p.png")],
        [{"kind": "artist_photo", "name": "まねきケチャ", "url": "u", "reason": "fetch_failed"}],
    ))
    t = bm._spawn_photo_update(39, "手羽先", "m1", "RT", _config())
    t.join(timeout=5)
    _tok, msgs = sent[0]
    assert [m["type"] for m in msgs] == ["text", "image", "text"]
    assert "まねきケチャ" in msgs[-1]["text"]


def test_photo_update_worker_replies_error_on_update_failure(monkeypatch, sent):
    """★更新失敗時はエラーテキストのみ(生成しない)。"""
    monkeypatch.setattr(bm, "download_image", lambda mid, at, timeout=30: (b"IMG", "image/jpeg"))
    monkeypatch.setattr(bm, "update_artist_photo", lambda name, b, ct: (False, "「X」が見つかりません"))
    monkeypatch.setattr(bm, "render_flyer_set_for_project",
                        lambda pid: pytest.fail("must not generate"))
    t = bm._spawn_photo_update(39, "X", "m1", "RT", _config())
    t.join(timeout=5)
    assert sent[0][1] == [{"type": "text", "text": "「X」が見つかりません"}]


def test_photo_update_worker_replies_on_download_failure(monkeypatch, sent):
    def _boom(mid, at, timeout=30):
        raise RuntimeError("download failed")

    monkeypatch.setattr(bm, "download_image", _boom)
    t = bm._spawn_photo_update(39, "X", "m1", "RT", _config())
    t.join(timeout=5)
    assert "画像の取得に失敗" in sent[0][1][0]["text"]


def test_regeneration_worker_replies_two_images(monkeypatch, sent):
    """flow=get のバックグラウンド生成(artist 引数は撤去済み)。"""
    monkeypatch.setattr(bm, "render_flyer_set_for_project", lambda pid: (
        [bm.build_image_message("https://a/1.png", "https://a/1p.png"),
         bm.build_image_message("https://a/2.png", "https://a/2p.png")],
        [],
    ))
    t = bm._spawn_regeneration(39, "RT", _config())
    t.join(timeout=5)
    _tok, msgs = sent[0]
    assert [m["type"] for m in msgs] == ["image", "image"]


def test_regeneration_worker_replies_failure_when_nothing_generated(monkeypatch, sent):
    monkeypatch.setattr(bm, "render_flyer_set_for_project", lambda pid: ([], []))
    t = bm._spawn_regeneration(39, "RT", _config())
    t.join(timeout=5)
    assert "生成できませんでした" in sent[0][1][0]["text"]


# ---------------------------------------------------------------------------
# webhook レベル(callback は 200 を即返す)
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


def _slow_spawn(release):
    def _spawn(*args, **kwargs):
        import threading

        def _work():
            _time.sleep(2.0)  # 生成が重い状況を模す
            release.append(True)

        t = threading.Thread(target=_work, daemon=True)
        t.start()
        return t
    return _spawn


def test_callback_returns_200_immediately_for_postback(line_env, monkeypatch):
    """★flow=get の postback で生成は待たない。"""
    release = []
    monkeypatch.setattr(bm, "_spawn_regeneration", _slow_spawn(release))

    t0 = _time.time()
    r = _signed_post(line_env, {"events": [_postback_event("evt|flow=get|pid=39")]})
    elapsed = _time.time() - t0

    assert r.status_code == 200
    assert elapsed < 1.0, "生成完了を待っていない(elapsed=%.2fs)" % elapsed
    assert release == [], "callback 応答時点ではまだ生成中"


def test_callback_returns_200_immediately_for_image(line_env, monkeypatch):
    """★画像受信(DL→更新→2枚生成)も待たない。"""
    bm.pending_store._data.clear()
    bm.pending_store.put(USER, 39, "手羽先", _time.time())
    release = []
    monkeypatch.setattr(bm, "_spawn_photo_update", _slow_spawn(release))

    t0 = _time.time()
    r = _signed_post(line_env, {"events": [_image_event()]})
    elapsed = _time.time() - t0

    assert r.status_code == 200
    assert elapsed < 1.0, "更新完了を待っていない(elapsed=%.2fs)" % elapsed
    assert release == []


def test_callback_rejects_bad_signature(line_env):
    r = line_env.post("/callback", content=b'{"events":[]}',
                      headers={"X-Line-Signature": "bogus"})
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# B-4: グループ起動制御
# ---------------------------------------------------------------------------
OWNER = "Uowner"


def _cfg_b4(owners=(OWNER,)):
    """B-4: ALLOWED_GROUP_IDS はゲートに使われないので空で渡す。"""
    return bm.BotConfig(
        channel_secret="s",
        channel_access_token="AT",
        owner_user_ids=frozenset(owners),
        allowed_group_ids=frozenset(),
    )


@pytest.fixture(autouse=True)
def activation(monkeypatch):
    """activation_service をメモリ集合で差し替える(Storage に触らない)。

    ★autouse: B-4 でグループ起動制御が入ったため、既存の会話フローのテストは
      「起動済みのグループ」を前提にする。未起動を試すテストは
      activation["active"].clear() してから実行すること。
    """
    state = {"active": {GROUP}}
    import services.activation_service as act

    monkeypatch.setattr(act, "is_group_active", lambda gid: gid in state["active"])
    monkeypatch.setattr(act, "activate_group",
                        lambda gid, uid: state["active"].add(gid))
    monkeypatch.setattr(act, "deactivate_group",
                        lambda gid: state["active"].discard(gid))
    return state


def _member_left_event(user_ids, group=GROUP):
    return {
        "type": "memberLeft",
        "replyToken": "RT",
        "source": {"type": "group", "groupId": group},
        "left": {"members": [{"type": "user", "userId": u} for u in user_ids]},
    }


# --- 起動 ---
def test_owner_activates_group(sent, activation):
    """★オーナーの「起動」で有効化 + 起動文言。"""
    activation["active"].clear()
    bm.handle_event(_text_event("@Bot 起動", user=OWNER), _cfg_b4())
    assert GROUP in activation["active"]
    assert sent[0][1][0]["text"] == bm.MSG_ACTIVATED


def test_non_owner_cannot_activate(sent, activation):
    """★非オーナーの「起動」は拒否文言(有効化しない)。"""
    activation["active"].clear()
    bm.handle_event(_text_event("@Bot 起動", user="Ustranger"), _cfg_b4())
    assert GROUP not in activation["active"]
    assert sent[0][1][0]["text"] == bm.MSG_ACTIVATE_DENIED


def test_activate_when_already_active(sent, activation):
    """★既に有効なら「すでに起動しています」。"""
    bm.handle_event(_text_event("@Bot 起動", user=OWNER), _cfg_b4())
    assert sent[0][1][0]["text"] == bm.MSG_ALREADY_ACTIVE


def test_already_active_message_even_for_non_owner(sent, activation):
    """有効なグループでは非オーナーの「起動」も「すでに起動」を返す(拒否ではない)。"""
    bm.handle_event(_text_event("@Bot 起動", user="Ustranger"), _cfg_b4())
    assert sent[0][1][0]["text"] == bm.MSG_ALREADY_ACTIVE


# --- 通常依頼のゲート ---
def test_request_in_inactive_group_gets_hint(sent, activation, stub_events):
    """★未起動グループの依頼は無反応ではなくヒント文言を返す。"""
    activation["active"].clear()
    bm.handle_event(_text_event("@Bot アー写変更"), _cfg_b4())
    assert sent[0][1][0]["text"] == bm.MSG_NOT_ACTIVATED


def test_request_in_active_group_proceeds(sent, activation, stub_events):
    bm.handle_event(_text_event("@Bot アー写変更"), _cfg_b4())
    assert "quickReply" in sent[0][1][0]


def test_postback_in_inactive_group_gets_hint(sent, activation):
    """★無効化後に古いボタンを押されても処理しない。"""
    activation["active"].clear()
    bm.handle_event(_postback_event("evt|flow=replace|pid=39"), _cfg_b4())
    assert sent[0][1][0]["text"] == bm.MSG_NOT_ACTIVATED


def test_image_in_inactive_group_is_ignored(monkeypatch, activation):
    activation["active"].clear()
    bm.pending_store._data.clear()
    bm.pending_store.put(USER, 39, "A", _time.time())
    monkeypatch.setattr(bm, "_spawn_photo_update",
                        lambda *a, **k: pytest.fail("must not spawn"))
    bm.handle_event(_image_event(), _cfg_b4())


def test_any_group_can_be_activated_no_static_allowlist(sent, activation):
    """★ALLOWED_GROUP_IDS ゲートは撤去済み。どのグループでも起動できる。"""
    bm.handle_event(_text_event("@Bot 起動", group="Gbrandnew", user=OWNER), _cfg_b4())
    assert "Gbrandnew" in activation["active"]


# --- @All(isSelf 無し)は無反応のまま ---
def test_at_all_does_not_activate(sent, activation):
    """★@All(自ボット宛メンションでない)では起動も依頼も無反応(回帰固定)。"""
    activation["active"].clear()
    bm.handle_event(_text_event("起動", mentioned=False, user=OWNER), _cfg_b4())
    assert sent == []
    assert activation["active"] == set()


def test_at_all_does_not_trigger_request(sent, activation, stub_events):
    bm.handle_event(_text_event("アー写変更", mentioned=False), _cfg_b4())
    assert sent == []


# --- memberLeft / leave / join ---
def test_owner_leaving_deactivates_and_notifies(sent, activation):
    """★オーナー退会 → 無効化 + 停止文言。"""
    bm.handle_event(_member_left_event([OWNER]), _cfg_b4())
    assert GROUP not in activation["active"]
    assert sent[0][1][0]["text"] == bm.MSG_OWNER_LEFT


def test_non_owner_leaving_does_nothing(sent, activation):
    bm.handle_event(_member_left_event(["Ustranger"]), _cfg_b4())
    assert GROUP in activation["active"]
    assert sent == []


def test_owner_leaving_inactive_group_is_silent(sent, activation):
    """もともと無効なら通知しない(ノイズ防止)。"""
    activation["active"].clear()
    bm.handle_event(_member_left_event([OWNER]), _cfg_b4())
    assert sent == []


def test_bot_leave_removes_group_silently(sent, activation):
    """★bot 自身の退出は静かに掃除するだけ(発言しない)。"""
    bm.handle_event(
        {"type": "leave", "source": {"type": "group", "groupId": GROUP}}, _cfg_b4()
    )
    assert GROUP not in activation["active"]
    assert sent == []


def test_bot_join_does_nothing(sent, activation):
    """★join ではデフォルト無効のまま(勝手に有効化しない)。"""
    activation["active"].clear()
    bm.handle_event(
        {"type": "join", "source": {"type": "group", "groupId": GROUP}}, _cfg_b4()
    )
    assert activation["active"] == set()
    assert sent == []


def test_dm_events_are_ignored(sent, activation):
    ev = _member_left_event([OWNER])
    ev["source"] = {"type": "user", "userId": OWNER}
    bm.handle_event(ev, _cfg_b4())
    assert sent == []


# --- webhook レベル ---
@pytest.mark.parametrize("payload_event", [
    {"type": "memberLeft", "replyToken": "RT",
     "source": {"type": "group", "groupId": GROUP},
     "left": {"members": [{"type": "user", "userId": OWNER}]}},
    {"type": "leave", "source": {"type": "group", "groupId": GROUP}},
    {"type": "join", "source": {"type": "group", "groupId": GROUP}},
])
def test_callback_returns_200_for_membership_events(line_env, monkeypatch, payload_event):
    monkeypatch.setenv("OWNER_USER_IDS", OWNER)
    monkeypatch.setattr(bm, "_is_group_active", lambda gid: True)
    monkeypatch.setattr(bm, "_deactivate_group", lambda gid: None)
    monkeypatch.setattr(bm, "reply_text", lambda *a, **k: None)
    r = _signed_post(line_env, {"events": [payload_event]})
    assert r.status_code == 200


def test_activation_lookup_failure_falls_back_to_inactive(monkeypatch, sent, stub_events, activation):
    """★Storage 障害で判定不能なら「無効」に倒す(勝手に使えてしまうより安全)。"""
    activation["active"].clear()
    import services.activation_service as act

    def _boom(gid):
        raise RuntimeError("storage down")

    monkeypatch.setattr(act, "is_group_active", _boom)
    bm.handle_event(_text_event("@Bot アー写変更"), _cfg_b4())
    assert sent[0][1][0]["text"] == bm.MSG_NOT_ACTIVATED


# ---------------------------------------------------------------------------
# #4 案2: 未登録アーティストの通知
# ---------------------------------------------------------------------------
def test_failure_notice_reports_unregistered_artists():
    notice = bm.build_failure_notice(
        [{"kind": "artist_not_registered", "name": "Luna moon"}])
    assert "Luna moon はアー写未登録です" in notice
    assert "黒い枠" in notice, "グリッド上どう見えているかが伝わらない"
    assert "アー写変更" in notice, "次にやることの導線が無い"
    # 取得失敗とは原因も対処も違うので、そちらの文言は混ぜない
    assert "取得できませんでした" not in notice
    assert "反映待ち" not in notice


def test_failure_notice_dedupes_unregistered_names():
    notice = bm.build_failure_notice([
        {"kind": "artist_not_registered", "name": "X"},
        {"kind": "artist_not_registered", "name": "X"},
        {"kind": "artist_not_registered", "name": "Y"},
    ])
    assert notice.count("X") == 1
    assert "X / Y" in notice


def test_failure_notice_keeps_fetch_failure_wording_unchanged():
    """既存の取得失敗の文言は変えない(未登録が無いときは従来どおり)。"""
    notice = bm.build_failure_notice([{"kind": "artist_photo", "name": "A"}])
    assert notice == (
        "※ 一部の素材を取得できませんでした(アー写: A)。\n"
        "アップロード直後で反映待ちの可能性があります。少し待ってからもう一度お試しください。"
    )


def test_failure_notice_shows_both_blocks_separately():
    notice = bm.build_failure_notice([
        {"kind": "artist_photo", "name": "A"},
        {"kind": "artist_not_registered", "name": "Luna moon"},
    ])
    blocks = notice.split("\n\n")
    assert len(blocks) == 2, "2 つの事情が 1 段落に混ざっている"
    assert "取得できませんでした" in blocks[0]
    assert "アー写未登録" in blocks[1]


def test_failure_notice_ignores_unknown_kind_only():
    assert bm.build_failure_notice([{"kind": "something_else"}]) is None
