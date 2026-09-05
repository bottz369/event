"""段階C C-1: bot の記入テンプレ配線(テンプレ送出 / 受信判定 / 背景解析)のテスト。

実 LINE 送信・実 Anthropic API はすべて monkeypatch する。DB にも触らない。
★.venv 実行専用(fastapi / bot の依存が要るため verify.sh のゲートには入れない。
  既存の tests/test_bot_flow.py・test_bot_api.py と同じ扱い):
    .venv/bin/python3 -m pytest tests/test_bot_intake.py -v
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from bot import main as bm
from services import event_intake as ei

GROUP = "Gallowed"
USER = "Usomeone"
SECRET = "s"


def _config(owners=()):
    return bm.BotConfig(
        channel_secret=SECRET,
        channel_access_token="AT",
        owner_user_ids=frozenset(owners),
        allowed_group_ids=frozenset(),
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


@pytest.fixture
def sent(monkeypatch):
    box = []
    monkeypatch.setattr(bm, "reply_messages",
                        lambda tok, msgs, at, timeout=15: box.append((tok, msgs)))
    return box


@pytest.fixture(autouse=True)
def draft_store(monkeypatch):
    """intake_draft_store をメモリの偽物に差し替える(実 Storage に触らせない)。

    ★autouse: C-2 でエコー生成時に下書きを保存するようになったため、
      すべての intake テストがこれを通る。
    """
    from services import intake_draft_store as ds

    state = {"saved": {}, "deleted": [], "next_id": "d" * 32, "fail_save": False}

    def _save(data):
        if state["fail_save"]:
            return None
        did = state["next_id"]
        state["saved"][did] = data
        return did

    monkeypatch.setattr(ds, "save_draft", _save)
    monkeypatch.setattr(ds, "load_draft", lambda did: state["saved"].get(did))
    monkeypatch.setattr(ds, "delete_draft",
                        lambda did: bool(state["deleted"].append(did)) or True)
    return state


@pytest.fixture(autouse=True)
def activation(monkeypatch):
    """activation_service をメモリ集合で差し替える(Storage に触らない)。"""
    state = {"active": {GROUP}}
    import services.activation_service as act

    monkeypatch.setattr(act, "is_group_active", lambda gid: gid in state["active"])
    monkeypatch.setattr(act, "activate_group", lambda gid, uid: state["active"].add(gid))
    monkeypatch.setattr(act, "deactivate_group", lambda gid: state["active"].discard(gid))
    return state


@pytest.fixture
def run_inline(monkeypatch):
    """バックグラウンド thread をやめて同期実行にする(テストを決定的にする)。

    ★本番は daemon thread。ここで置き換えているのは「解析が呼ばれたか」と
      「何を返信したか」を確定的に見るためで、_spawn_intake_parse が
      _parse_intake_and_reply を呼ぶこと自体は別テストで確認している。
    """
    calls = []

    def _inline(text, reply_token, config):
        calls.append(text)
        bm._parse_intake_and_reply(text, reply_token, config)
        return None

    monkeypatch.setattr(bm, "_spawn_intake_parse", _inline)
    return calls


FILLED = (
    "【イベント種別】ガールズ\n"
    "\n"
    "【公演概要】\n"
    "2026年11月3日(月)\n"
    "「rock field ULTRA LIVE - AUTUMN」\n"
    "\n"
    "■会場:上野恩賜公園野外ステージ\n"
    "https://maps.app.goo.gl/example\n"
    "\n"
    "■時間:\n"
    "OPEN▶11:30\n"
    "START▶12:00\n"
    "\n"
    "■料金\n"
    "Sチケット ¥6,000(前方エリア)\n"
    "\n"
    "■出演者(3組予定)\n"
    "1.NecroA\n"
    "2.PRIBEAST\n"
    "3.\n"
    "\n"
    "■チケット・入場に関して\n"
    "入場はSチケット→Aチケット→当日券の順です。"
)

PARSED_OK = {
    "ok": True,
    "reason": None,
    "data": {
        "event_type": "girls",
        "event_date": "2026-11-03",
        "event_name": "rock field ULTRA LIVE",
        "subtitle": "AUTUMN", "venue": "上野恩賜公園野外ステージ", "venue_url": None,
        "open_time": "11:30", "start_time": "12:00",
        "open_start_note": None, "ticket_common_note": None,
        "tickets": [{"name": "Sチケット", "price": "¥6,000", "note": "前方エリア"}],
        "artists": ["NecroA", "PRIBEAST"],
        "tt_settings": {"goods_spaces": None, "set_minutes": None,
                        "has_post_goods": None,
                        "goods_start_offset_minutes": None,
                        "goods_duration_minutes": None,
                        "changeover_every_n": None, "changeover_minutes": None},
        "free_texts": [],
    },
}


def _only_text_or_msg(sent):
    """返信が 1 通であることを確かめ、そのメッセージ dict を返す。"""
    assert len(sent) == 1, f"返信が 1 通ではない: {sent}"
    msgs = sent[0][1]
    assert len(msgs) == 1 and msgs[0]["type"] == "text"
    return msgs[0]


def _only_text(sent):
    return _only_text_or_msg(sent)["text"]


def _labels(msg):
    return [i["action"]["label"] for i in msg.get("quickReply", {}).get("items", [])]


def _datas(msg):
    return [i["action"]["data"] for i in msg.get("quickReply", {}).get("items", [])]


# ---------------------------------------------------------------------------
# (A) テンプレ送出
# ---------------------------------------------------------------------------
def test_shinki_sakusei_asks_event_type(sent):
    """C-1.1: いきなりテンプレではなく、まず種別ボタンを出す。"""
    bm.handle_event(_text_event("@Bot 新規作成"), _config())
    assert len(sent) == 1
    msg = sent[0][1][0]
    assert msg["text"] == bm.MSG_ASK_EVENT_TYPE
    items = msg["quickReply"]["items"]
    assert [i["action"]["label"] for i in items] == ["ガールズイベント", "メンズイベント"]
    assert [i["action"]["data"] for i in items] == ["newproj|type=girls",
                                                    "newproj|type=mens"]


def test_shinki_sakusei_does_not_send_template_directly(sent):
    """種別を選ぶ前にテンプレ本文を送ってしまわない。"""
    bm.handle_event(_text_event("@Bot 新規作成"), _config())
    text = _only_text(sent)
    for event_type in ei.EVENT_TYPES:
        assert text != ei.get_intake_template(event_type)


@pytest.mark.parametrize(
    "event_type,label", [("girls", "ガールズ"), ("mens", "メンズ")])
def test_event_type_postback_sends_matching_template(sent, event_type, label):
    """種別 postback → その種別のテンプレを送る(先頭に種別行が入る)。"""
    bm.handle_event(_postback_event("newproj|type=%s" % event_type), _config())
    text = _only_text(sent)
    assert text == ei.get_intake_template(event_type)
    assert text.splitlines()[0] == ei.EVENT_TYPE_MARKER + label


def test_unknown_event_type_postback_is_ignored(sent):
    """未知の種別ボタンは静かに無視する(テンプレを引けないため)。"""
    bm.handle_event(_postback_event("newproj|type=other"), _config())
    assert sent == []


def test_event_type_postback_needs_active_group(sent, activation):
    activation["active"].clear()
    bm.handle_event(_postback_event("newproj|type=girls"), _config())
    assert _only_text(sent) == bm.MSG_NOT_ACTIVATED


def test_template_is_not_sent_for_other_text(sent):
    """関係ないテキストではテンプレを返さない(使い方案内になる)。"""
    bm.handle_event(_text_event("@Bot こんにちは"), _config())
    text = _only_text(sent)
    for event_type in ei.EVENT_TYPES:
        assert text != ei.get_intake_template(event_type)
    assert "新規作成" in text, "使い方案内に「新規作成」の導線が無い"


# ---------------------------------------------------------------------------
# (B) 埋めたテンプレの受信判定(ステートレス)
# ---------------------------------------------------------------------------
def test_filled_template_goes_to_parse_not_template(monkeypatch, sent, run_inline):
    monkeypatch.setattr(ei, "parse_event_template", lambda text: PARSED_OK)
    bm.handle_event(_text_event("@Bot " + FILLED), _config())

    # メンションを除去した本文がそのまま解析へ渡ること
    # (strip_self_mentions はメンション直後の空白を残すので strip して比較する)
    assert len(run_inline) == 1, "解析が呼ばれていない: %r" % (run_inline,)
    assert run_inline[0].strip() == FILLED, "解析に渡る本文が欠けている"
    for event_type in ei.EVENT_TYPES:
        assert _only_text(sent) != ei.get_intake_template(event_type)


def test_filled_template_wins_over_shinki_sakusei(monkeypatch, sent, run_inline):
    """テンプレ本文に「新規作成」が混ざっていても配り直さず解析へ進む。"""
    monkeypatch.setattr(ei, "parse_event_template", lambda text: PARSED_OK)
    bm.handle_event(_text_event("@Bot 新規作成\n" + FILLED), _config())
    assert len(run_inline) == 1
    assert _only_text(sent) != bm.MSG_ASK_EVENT_TYPE


def test_bare_shinki_sakusei_is_not_treated_as_filled(sent, run_inline):
    """素の「新規作成」は見出しが無いので解析に流れない。"""
    bm.handle_event(_text_event("@Bot 新規作成"), _config())
    assert run_inline == []


# ---------------------------------------------------------------------------
# ガード(既存どおり)
# ---------------------------------------------------------------------------
def test_no_mention_is_ignored(sent, run_inline):
    bm.handle_event(_text_event("新規作成", mentioned=False), _config())
    bm.handle_event(_text_event(FILLED, mentioned=False), _config())
    assert sent == [] and run_inline == []


def test_inactive_group_does_not_parse(sent, run_inline, activation):
    activation["active"].clear()
    bm.handle_event(_text_event("@Bot " + FILLED), _config())
    assert run_inline == [], "未起動グループで解析が走った"
    assert _only_text(sent) == bm.MSG_NOT_ACTIVATED


def test_dm_is_ignored(sent, run_inline):
    ev = _text_event("@Bot 新規作成")
    ev["source"] = {"type": "user", "userId": USER}
    bm.handle_event(ev, _config())
    assert sent == [] and run_inline == []


# ---------------------------------------------------------------------------
# (D) エコー確認 / 失敗時の案内
# ---------------------------------------------------------------------------
def test_successful_parse_replies_echo(monkeypatch, sent, run_inline):
    monkeypatch.setattr(ei, "parse_event_template", lambda text: PARSED_OK)
    bm.handle_event(_text_event("@Bot " + FILLED), _config())
    text = _only_text_or_msg(sent)["text"]
    assert "rock field ULTRA LIVE" in text and "2026-11-03" in text
    assert "1. NecroA" in text
    assert "イベント種別: ガールズ" in text, "エコーに種別が出ていない"
    assert text.rstrip().endswith(ei.ECHO_FOOTER)


def test_missing_required_replies_guidance(monkeypatch, sent, run_inline):
    bad = {"ok": True, "reason": None,
           "data": dict(PARSED_OK["data"], event_date=None, artists=[])}
    monkeypatch.setattr(ei, "parse_event_template", lambda text: bad)
    bm.handle_event(_text_event("@Bot " + FILLED), _config())
    text = _only_text(sent)
    assert "開催日" in text and "出演者" in text
    assert "再送" in text


def test_missing_api_key_replies_guidance_not_crash(monkeypatch, sent, run_inline):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    bm.handle_event(_text_event("@Bot " + FILLED), _config())
    assert _only_text(sent) == bm.MSG_INTAKE_NO_API_KEY


def test_api_failure_replies_guidance(monkeypatch, sent, run_inline):
    monkeypatch.setattr(
        ei, "parse_event_template",
        lambda text: {"ok": False, "reason": ei.REASON_API_ERROR, "data": None})
    bm.handle_event(_text_event("@Bot " + FILLED), _config())
    assert _only_text(sent) == bm.MSG_INTAKE_FAILED


def test_unexpected_exception_still_replies(monkeypatch, sent, run_inline):
    """解析側が想定外の例外を投げても必ず何か返す(無反応にしない)。"""
    def _boom(text):
        raise RuntimeError("boom")

    monkeypatch.setattr(ei, "parse_event_template", _boom)
    bm.handle_event(_text_event("@Bot " + FILLED), _config())
    assert _only_text(sent) == bm.MSG_INTAKE_FAILED


# ---------------------------------------------------------------------------
# (E) バックグラウンド化 / webhook は 200 を即返す
# ---------------------------------------------------------------------------
def test_spawn_runs_parse_in_daemon_thread(monkeypatch):
    done = []
    monkeypatch.setattr(bm, "_parse_intake_and_reply",
                        lambda text, tok, cfg: done.append(text))
    t = bm._spawn_intake_parse("body", "RT", _config())
    assert t.daemon is True
    t.join(timeout=5)
    assert done == ["body"]


def test_callback_returns_200_immediately_for_filled_template(monkeypatch):
    """テンプレ受信でも webhook は 200 を即返し、解析は別スレッドに逃げる。"""
    monkeypatch.setattr(bm, "load_config", lambda: _config())
    monkeypatch.setattr(bm, "reply_messages", lambda *a, **k: None)

    spawned = []
    monkeypatch.setattr(bm, "_spawn_intake_parse",
                        lambda text, tok, cfg: spawned.append(text))

    body = json.dumps({"events": [_text_event("@Bot " + FILLED)]}).encode("utf-8")
    sig = base64.b64encode(
        hmac.new(SECRET.encode("utf-8"), body, hashlib.sha256).digest()
    ).decode("utf-8")

    client = TestClient(bm.app)
    res = client.post("/callback", content=body,
                      headers={"X-Line-Signature": sig,
                               "Content-Type": "application/json"})
    assert res.status_code == 200
    assert len(spawned) == 1, "解析がバックグラウンドに投げられていない"


# ---------------------------------------------------------------------------
# C-1 は DB に書かない
# ---------------------------------------------------------------------------
def test_intake_path_does_not_touch_db(monkeypatch, sent, run_inline):
    """C-1 の経路が DB セッションを開かないこと(作成は C-2)。"""
    import database

    monkeypatch.setattr(database, "SessionLocal",
                        lambda *a, **k: pytest.fail("C-1 は DB に触ってはいけない"))
    monkeypatch.setattr(ei, "parse_event_template", lambda text: PARSED_OK)

    bm.handle_event(_text_event("@Bot 新規作成"), _config())          # 種別ボタン
    bm.handle_event(_postback_event("newproj|type=girls"), _config())  # テンプレ送信
    bm.handle_event(_postback_event("newproj|type=mens"), _config())
    bm.handle_event(_text_event("@Bot " + FILLED), _config())          # 解析→エコー
    assert len(sent) == 4


# ---------------------------------------------------------------------------
# C-1.2 (3): ワンショット投入(テンプレを配らずに概要を直接投げる)
# ---------------------------------------------------------------------------
def test_oneshot_concept_only_parses_without_asking_type(
    monkeypatch, sent, run_inline
):
    """メンション + 概要だけ(「新規作成」なし)→ 種別ボタンを出さず直接解析。

    テンプレを配ってもらわず、手元の告知文をそのまま投げる使い方を正式仕様にした。
    """
    monkeypatch.setattr(ei, "parse_event_template", lambda text: PARSED_OK)
    bm.handle_event(_text_event("@Bot " + FILLED), _config())

    assert len(run_inline) == 1, "解析に流れていない"
    text = _only_text(sent)
    assert text != bm.MSG_ASK_EVENT_TYPE, "種別ボタンを出してしまっている"
    assert "イベント種別: ガールズ" in text


def test_oneshot_with_shinki_sakusei_in_same_message_parses(
    monkeypatch, sent, run_inline
):
    """「新規作成」と概要が同じメッセージ → 概要があるので直接解析。"""
    monkeypatch.setattr(ei, "parse_event_template", lambda text: PARSED_OK)
    bm.handle_event(_text_event("@Bot 新規作成\n" + FILLED), _config())

    assert len(run_inline) == 1
    assert _only_text(sent) != bm.MSG_ASK_EVENT_TYPE


def test_shinki_sakusei_alone_still_asks_type(sent, run_inline):
    """「新規作成」だけ(概要なし)→ 従来どおり種別ボタン。"""
    bm.handle_event(_text_event("@Bot 新規作成"), _config())

    assert run_inline == [], "概要が無いのに解析へ流れている"
    assert _only_text(sent) == bm.MSG_ASK_EVENT_TYPE


def test_oneshot_without_type_marker_echoes_undetermined(
    monkeypatch, sent, run_inline
):
    """種別行の無い告知文で LLM も判定できなければ、その旨をエコーに出す。"""
    undetermined = {"ok": True, "reason": None,
                    "data": dict(PARSED_OK["data"], event_type=None)}
    monkeypatch.setattr(ei, "parse_event_template", lambda text: undetermined)

    body = FILLED.split("\n", 2)[2]        # 先頭の【イベント種別】行を落とす
    assert ei.EVENT_TYPE_MARKER not in body
    bm.handle_event(_text_event("@Bot " + body), _config())

    assert len(run_inline) == 1
    assert ei.ECHO_EVENT_TYPE_UNKNOWN in _only_text(sent)


def test_oneshot_still_requires_mention_and_active_group(sent, run_inline, activation):
    """ワンショットでもガードは従来どおり(メンション必須 / 起動済みグループ)。"""
    bm.handle_event(_text_event(FILLED, mentioned=False), _config())
    assert sent == [] and run_inline == []

    activation["active"].clear()
    bm.handle_event(_text_event("@Bot " + FILLED), _config())
    assert run_inline == []
    assert _only_text(sent) == bm.MSG_NOT_ACTIVATED


# ---------------------------------------------------------------------------
# C-2: エコーの作成ボタン
# ---------------------------------------------------------------------------
DID = "d" * 32


@pytest.fixture
def creation_spy(monkeypatch):
    """作成サービスを記録用スタブに差し替える(実 DB に書かない)。"""
    from services import intake_creation as ic

    calls = {"created": [], "found": []}
    state = {"duplicates": [], "pid": 55, "fail": False}

    def _create(data, event_type=None, overwrite_project_id=None):
        calls["created"].append({"data": data, "event_type": event_type,
                                 "overwrite": overwrite_project_id})
        return None if state["fail"] else state["pid"]

    def _find(date):
        calls["found"].append(date)
        return list(state["duplicates"])

    monkeypatch.setattr(ic, "create_project_from_intake", _create)
    monkeypatch.setattr(ic, "find_projects_by_event_date", _find)
    monkeypatch.setattr(bm, "render_draft_set_for_project",
                        lambda pid: ([{"type": "image", "originalContentUrl": "o",
                                       "previewImageUrl": "p"}], []))
    calls["state"] = state
    return calls


def test_echo_offers_create_button_when_type_is_known(monkeypatch, sent, run_inline):
    monkeypatch.setattr(ei, "parse_event_template", lambda text: PARSED_OK)
    bm.handle_event(_text_event("@Bot " + FILLED), _config())

    msg = _only_text_or_msg(sent)
    assert _labels(msg) == ["この内容で作成", "やり直し"]
    assert _datas(msg) == ["%s|draft=%s" % (bm.ACTION_CREATE, DID),
                           "%s|draft=%s" % (bm.ACTION_CANCEL, DID)]


def test_echo_offers_both_types_when_undetermined(monkeypatch, sent, run_inline):
    """種別が判定できないときは、種別を確定しながら作れる 3 択にする。"""
    undetermined = {"ok": True, "reason": None,
                    "data": dict(PARSED_OK["data"], event_type=None)}
    monkeypatch.setattr(ei, "parse_event_template", lambda text: undetermined)
    bm.handle_event(_text_event("@Bot " + FILLED), _config())

    msg = _only_text_or_msg(sent)
    assert _labels(msg) == ["ガールズで作成", "メンズで作成", "やり直し"]
    assert _datas(msg) == [
        "%s|type=girls|draft=%s" % (bm.ACTION_CREATE, DID),
        "%s|type=mens|draft=%s" % (bm.ACTION_CREATE, DID),
        "%s|draft=%s" % (bm.ACTION_CANCEL, DID),
    ]


def test_echo_has_no_buttons_when_draft_cannot_be_saved(
    monkeypatch, sent, run_inline, draft_store
):
    """取り置きに失敗したら、押しても作れないボタンは出さない。"""
    draft_store["fail_save"] = True
    monkeypatch.setattr(ei, "parse_event_template", lambda text: PARSED_OK)
    bm.handle_event(_text_event("@Bot " + FILLED), _config())

    msg = _only_text_or_msg(sent)
    assert "quickReply" not in msg
    assert ei.ECHO_FOOTER in msg["text"]


# ---------------------------------------------------------------------------
# C-2: postback の検証
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "data,expected",
    [
        ("newproj_create|draft=" + DID, {"action": "newproj_create", "draft": DID}),
        ("newproj_create|type=girls|draft=" + DID,
         {"action": "newproj_create", "type": "girls", "draft": DID}),
        ("newproj_overwrite|pid=7|draft=" + DID,
         {"action": "newproj_overwrite", "pid": 7, "draft": DID}),
        ("newproj_forcenew|draft=" + DID, {"action": "newproj_forcenew", "draft": DID}),
        ("newproj_cancel|draft=" + DID, {"action": "newproj_cancel", "draft": DID}),
    ],
)
def test_create_postback_data_parses(data, expected):
    assert bm.parse_postback_data(data) == expected


@pytest.mark.parametrize(
    "data",
    [
        "newproj_create",                      # draft が無い
        "newproj_create|type=other|draft=" + DID,   # 未知の種別
        "newproj_overwrite|draft=" + DID,      # pid が無い
        "newproj_overwrite|pid=abc|draft=" + DID,   # pid が数値でない
    ],
)
def test_malformed_create_postback_is_rejected(data):
    assert bm.parse_postback_data(data) is None


# ---------------------------------------------------------------------------
# C-2: 作成フロー
# ---------------------------------------------------------------------------
def _run_create(monkeypatch, data, draft_store, payload=None):
    """作成系 postback を同期実行して結果を見る(スレッドを外して決定的にする)。"""
    draft_store["saved"][DID] = payload if payload is not None else PARSED_OK["data"]

    def _inline(draft_id, reply_token, config, **kw):
        bm._create_and_reply(draft_id, reply_token, config, **kw)
        return None

    monkeypatch.setattr(bm, "_spawn_creation", _inline)
    bm.handle_event(_postback_event(data), _config())


def test_create_without_duplicates_creates_and_returns_images(
    monkeypatch, sent, creation_spy, draft_store
):
    _run_create(monkeypatch, "newproj_create|draft=" + DID, draft_store)

    assert creation_spy["found"] == ["2026-11-03"], "日付重複を調べていない"
    assert len(creation_spy["created"]) == 1
    call = creation_spy["created"][0]
    assert call["overwrite"] is None

    msgs = sent[0][1]
    assert msgs[0]["type"] == "image", "たたき台の画像を返していない"
    assert "たたき台を作成しました" in msgs[-1]["text"]
    assert draft_store["deleted"] == [DID], "作成後に下書きを片付けていない"


def test_create_passes_event_type_from_button(monkeypatch, sent, creation_spy,
                                              draft_store):
    _run_create(monkeypatch, "newproj_create|type=mens|draft=" + DID, draft_store,
                payload=dict(PARSED_OK["data"], event_type=None))
    assert creation_spy["created"][0]["event_type"] == "mens"


def test_duplicate_date_offers_three_choices_without_creating(
    monkeypatch, sent, creation_spy, draft_store
):
    creation_spy["state"]["duplicates"] = [
        {"id": 7, "title": "既存イベント", "event_date": "2026-11-03"}]
    _run_create(monkeypatch, "newproj_create|draft=" + DID, draft_store)

    assert creation_spy["created"] == [], "重複を確認する前に作成している"
    msg = _only_text_or_msg(sent)
    assert _labels(msg) == ["上書き保存", "別で新規作成", "中止"]
    assert _datas(msg) == [
        "%s|pid=7|draft=%s" % (bm.ACTION_OVERWRITE, DID),
        "%s|draft=%s" % (bm.ACTION_FORCE_NEW, DID),
        "%s|draft=%s" % (bm.ACTION_CANCEL, DID),
    ]
    assert "既存イベント" in msg["text"]
    assert draft_store["deleted"] == [], "まだ下書きを消してはいけない"


def test_overwrite_replaces_the_existing_project(monkeypatch, sent, creation_spy,
                                                 draft_store):
    _run_create(monkeypatch, "newproj_overwrite|pid=7|draft=" + DID, draft_store)

    assert creation_spy["found"] == [], "上書き指定なのに重複を再確認している"
    assert creation_spy["created"][0]["overwrite"] == 7
    assert "上書きしました" in sent[0][1][-1]["text"]


def test_force_new_skips_duplicate_check(monkeypatch, sent, creation_spy, draft_store):
    creation_spy["state"]["duplicates"] = [
        {"id": 7, "title": "既存", "event_date": "2026-11-03"}]
    _run_create(monkeypatch, "newproj_forcenew|draft=" + DID, draft_store)

    assert creation_spy["found"] == [], "別で新規なのに重複を聞き直している"
    assert creation_spy["created"][0]["overwrite"] is None
    assert sent[0][1][0]["type"] == "image"


def test_cancel_deletes_draft_and_writes_nothing(monkeypatch, sent, creation_spy,
                                                 draft_store):
    draft_store["saved"][DID] = PARSED_OK["data"]
    bm.handle_event(_postback_event("newproj_cancel|draft=" + DID), _config())

    assert creation_spy["created"] == [], "中止なのに作成している"
    assert draft_store["deleted"] == [DID]
    assert _only_text(sent) == bm.MSG_CANCELLED


def test_expired_draft_is_reported(monkeypatch, sent, creation_spy, draft_store):
    monkeypatch.setattr(bm, "_spawn_creation",
                        lambda did, tok, cfg, **kw: bm._create_and_reply(did, tok, cfg, **kw))
    bm.handle_event(_postback_event("newproj_create|draft=" + "e" * 32), _config())

    assert creation_spy["created"] == []
    assert _only_text(sent) == bm.MSG_DRAFT_EXPIRED


def test_creation_failure_is_reported(monkeypatch, sent, creation_spy, draft_store):
    creation_spy["state"]["fail"] = True
    _run_create(monkeypatch, "newproj_create|draft=" + DID, draft_store)
    assert _only_text(sent) == bm.MSG_CREATE_FAILED


def test_creation_runs_in_daemon_thread(monkeypatch):
    done = []
    monkeypatch.setattr(bm, "_create_and_reply",
                        lambda did, tok, cfg, **kw: done.append((did, kw)))
    t = bm._spawn_creation(DID, "RT", _config(), overwrite_project_id=7)
    assert t.daemon is True
    t.join(timeout=5)
    assert done == [(DID, {"overwrite_project_id": 7})]


def test_create_postback_needs_active_group(sent, activation, creation_spy):
    activation["active"].clear()
    bm.handle_event(_postback_event("newproj_create|draft=" + DID), _config())
    assert creation_spy["created"] == []
    assert _only_text(sent) == bm.MSG_NOT_ACTIVATED


def test_callback_returns_200_immediately_for_create_postback(monkeypatch, draft_store):
    """作成ボタンでも webhook は 200 を即返し、作成は別スレッドに逃げる。"""
    monkeypatch.setattr(bm, "load_config", lambda: _config())
    monkeypatch.setattr(bm, "reply_messages", lambda *a, **k: None)

    spawned = []
    monkeypatch.setattr(bm, "_spawn_creation",
                        lambda did, tok, cfg, **kw: spawned.append((did, kw)))

    body = json.dumps({"events": [
        _postback_event("newproj_create|draft=" + DID)]}).encode("utf-8")
    sig = base64.b64encode(
        hmac.new(SECRET.encode("utf-8"), body, hashlib.sha256).digest()
    ).decode("utf-8")

    client = TestClient(bm.app)
    res = client.post("/callback", content=body,
                      headers={"X-Line-Signature": sig,
                               "Content-Type": "application/json"})
    assert res.status_code == 200
    assert len(spawned) == 1, "作成がバックグラウンドに投げられていない"


def test_intake_path_never_calls_project_service_create():
    """streamlit を引く project_service / session_manager を Bot 経路で使わない。

    説明文では両者に触れているので、文字列検索ではなく AST の import を見る。
    """
    import ast

    tree = ast.parse(open("services/intake_creation.py", encoding="utf-8").read())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                imported.add(a.name.split(".")[-1])
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[-1])
            for a in node.names:
                imported.add(a.name.split(".")[-1])

    for forbidden in ("streamlit", "project_service", "session_manager"):
        assert forbidden not in imported, f"{forbidden} を import している"
    # 書き込みに使うのは repo だけ
    assert {"project_repo", "timetable_repo"} <= imported
