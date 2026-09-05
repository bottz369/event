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


@pytest.fixture
def sent(monkeypatch):
    box = []
    monkeypatch.setattr(bm, "reply_messages",
                        lambda tok, msgs, at, timeout=15: box.append((tok, msgs)))
    return box


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
    "■ 公演概要の設定\n開催日: 2026-11-03\nイベント名: 秋フェス\n"
    "■ 料金設定\nチケット1 名前: 前売\n"
    "■ アー写グリッド設定\n出演者1: NecroA\n"
    "■ タイムテーブル設定\n出演尺(分): 15"
)

PARSED_OK = {
    "ok": True,
    "reason": None,
    "data": {
        "event_date": "2026-11-03",
        "event_name": "秋フェス",
        "subtitle": None, "venue": "上野音横丁", "venue_url": None,
        "open_time": "11:30", "start_time": "12:00",
        "open_start_note": None, "ticket_common_note": None,
        "tickets": [{"name": "前売", "price": 3000, "note": None}],
        "artists": ["NecroA", "PRIBEAST"],
        "tt_settings": {"goods_spaces": "A/B", "set_minutes": 15,
                        "has_post_goods": True,
                        "goods_start_offset_minutes": 5,
                        "goods_duration_minutes": 60,
                        "changeover_every_n": None, "changeover_minutes": None},
        "free_texts": [],
    },
}


def _only_text(sent):
    assert len(sent) == 1, f"返信が 1 通ではない: {sent}"
    msgs = sent[0][1]
    assert len(msgs) == 1 and msgs[0]["type"] == "text"
    return msgs[0]["text"]


# ---------------------------------------------------------------------------
# (A) テンプレ送出
# ---------------------------------------------------------------------------
def test_shinki_sakusei_replies_template(sent):
    bm.handle_event(_text_event("@Bot 新規作成"), _config())
    assert _only_text(sent) == ei.MSG_INTAKE_TEMPLATE


def test_template_is_not_sent_for_other_text(sent):
    """関係ないテキストではテンプレを返さない(使い方案内になる)。"""
    bm.handle_event(_text_event("@Bot こんにちは"), _config())
    text = _only_text(sent)
    assert text != ei.MSG_INTAKE_TEMPLATE
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
    assert _only_text(sent) != ei.MSG_INTAKE_TEMPLATE


def test_filled_template_wins_over_shinki_sakusei(monkeypatch, sent, run_inline):
    """テンプレ本文に「新規作成」が混ざっていても配り直さず解析へ進む。"""
    monkeypatch.setattr(ei, "parse_event_template", lambda text: PARSED_OK)
    bm.handle_event(_text_event("@Bot 新規作成\n" + FILLED), _config())
    assert len(run_inline) == 1
    assert _only_text(sent) != ei.MSG_INTAKE_TEMPLATE


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
    text = _only_text(sent)
    assert "秋フェス" in text and "2026-11-03" in text
    assert "1. NecroA" in text
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

    bm.handle_event(_text_event("@Bot 新規作成"), _config())
    bm.handle_event(_text_event("@Bot " + FILLED), _config())
    assert len(sent) == 2
