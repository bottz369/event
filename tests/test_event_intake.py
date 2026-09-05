"""services/event_intake.py(段階C C-1)のユニットテスト。

★実 API は一切叩かない。anthropic クライアントを monkeypatch で差し替え、
  固定 JSON を返させて整形・検証・正規化を固定する。

検証:
  - streamlit を引かない(罠39)
  - ANTHROPIC_API_KEY 未設定 → 例外ではなく reason 付きの失敗
  - anthropic 未 install → 同上
  - API 例外 → 同上(webhook を落とさない)
  - 空欄出演者の除去 / 空チケット・空自由記述の除去
  - 必須検証(開催日・イベント名・出演者1組以上)と日付形式
  - エコー整形(番号付き出演者・長い自由記述のプレビュー・末尾の一文)
  - 埋めたテンプレのステートレス判定(見出し2つ以上)
"""
from __future__ import annotations

import builtins
import importlib
import json
import sys
import types

import pytest

from services import event_intake as ei


# --- LLM が返す想定の JSON(schema どおり)------------------------------------
FULL_PAYLOAD = {
    "event_date": "2026-11-03",
    "event_name": "rock field ULTRA LIVE",
    "subtitle": "AUTUMN 2026",
    "venue": "上野音横丁",
    "venue_url": "https://example.com/venue",
    "open_time": "11:30",
    "start_time": "12:00",
    "open_start_note": "雨天決行",
    "ticket_common_note": "ドリンク代別途",
    "tickets": [
        {"name": "前売", "price": 3000, "note": None},
        {"name": "当日", "price": 3500, "note": "整理番号なし"},
        {"name": None, "price": None, "note": None},          # ← 空行は落ちる
    ],
    "artists": ["NecroA", "  ", "PRIBEAST", "", "ZEKECODE"],   # ← 空欄は落ちる
    "tt_settings": {
        "goods_spaces": "A/B/C",
        "set_minutes": 15,
        "has_post_goods": True,
        "goods_start_offset_minutes": 5,
        "goods_duration_minutes": 60,
        "changeover_every_n": 4,
        "changeover_minutes": 10,
    },
    "free_texts": [
        {"title": "注意事項", "body": "あ" * 120},              # ← プレビューされる
        {"title": None, "body": None},                          # ← 空行は落ちる
    ],
}


class _FakeBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _FakeResponse:
    def __init__(self, payload):
        self.content = [_FakeBlock(json.dumps(payload, ensure_ascii=False))]


def _install_fake_anthropic(monkeypatch, payload=None, raise_exc=None, capture=None):
    """anthropic モジュールを偽物に差し替える(実 API を叩かない)。"""
    module = types.ModuleType("anthropic")

    class _Messages:
        def create(self, **kwargs):
            if capture is not None:
                capture.update(kwargs)
            if raise_exc is not None:
                raise raise_exc
            return _FakeResponse(payload)

    class _Client:
        def __init__(self, api_key=None):
            self.api_key = api_key
            self.messages = _Messages()

    module.Anthropic = _Client
    monkeypatch.setitem(sys.modules, "anthropic", module)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-not-a-real-key")


# ---------------------------------------------------------------------------
# streamlit-free
# ---------------------------------------------------------------------------
def test_event_intake_is_streamlit_free(monkeypatch):
    """streamlit が import 不能な Bot 環境でも import でき、streamlit を引かない。

    ★後片付けが要る: fresh import すると services.event_intake が別オブジェクトに
      差し替わる。他のテスト(や bot 側)は先に束縛済みのモジュールを monkeypatch
      するため、差し替えたままだとパッチが効かなくなる。
      戻す先は 2 か所:
        (1) sys.modules["services.event_intake"]
        (2) 親パッケージの属性 services.event_intake
      bot/main.py は `from services import event_intake` で (2) を引くので、
      (1) だけ戻しても取り違えたままになる(実際にテストが落ちて判明した)。
    """
    import services as _services_pkg

    real_import = builtins.__import__
    original = sys.modules.get("services.event_intake")
    original_attr = getattr(_services_pkg, "event_intake", None)

    def _blocked(name, *a, **kw):
        if name == "streamlit" or name.startswith("streamlit."):
            raise ImportError("streamlit is unavailable (simulated Bot env)")
        return real_import(name, *a, **kw)

    try:
        for m in list(sys.modules):
            if m == "services.event_intake" or m == "streamlit" or m.startswith("streamlit."):
                sys.modules.pop(m, None)

        monkeypatch.setattr(builtins, "__import__", _blocked)
        mod = importlib.import_module("services.event_intake")

        assert callable(mod.parse_event_template)
        assert callable(mod.validate_intake)
        assert callable(mod.format_intake_echo)
        assert "streamlit" not in sys.modules
    finally:
        if original is not None:
            sys.modules["services.event_intake"] = original
        if original_attr is not None:
            setattr(_services_pkg, "event_intake", original_attr)


# ---------------------------------------------------------------------------
# 失敗経路(すべて例外を投げない)
# ---------------------------------------------------------------------------
def test_missing_api_key_returns_reason_not_exception(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = ei.parse_event_template("■ 公演概要の設定\n開催日: 2026-11-03")
    assert result == {"ok": False, "reason": ei.REASON_NO_API_KEY, "data": None}


def test_sdk_missing_returns_reason_not_exception(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-not-a-real-key")
    real_import = builtins.__import__

    def _blocked(name, *a, **kw):
        if name == "anthropic":
            raise ImportError("no anthropic")
        return real_import(name, *a, **kw)

    monkeypatch.setitem(sys.modules, "anthropic", None)
    sys.modules.pop("anthropic", None)
    monkeypatch.setattr(builtins, "__import__", _blocked)
    result = ei.parse_event_template("x")
    assert result["ok"] is False
    assert result["reason"] == ei.REASON_SDK_MISSING


def test_api_error_returns_reason_not_exception(monkeypatch):
    _install_fake_anthropic(monkeypatch, raise_exc=RuntimeError("boom"))
    result = ei.parse_event_template("x")
    assert result["ok"] is False
    assert result["reason"] == ei.REASON_API_ERROR


def test_non_json_output_returns_reason(monkeypatch):
    _install_fake_anthropic(monkeypatch)

    class _BadResponse:
        content = [_FakeBlock("これは JSON ではありません")]

    import anthropic

    anthropic.Anthropic.__init__ = lambda self, api_key=None: setattr(
        self, "messages", type("M", (), {"create": lambda _s, **_k: _BadResponse()})()
    )
    result = ei.parse_event_template("x")
    assert result["ok"] is False
    assert result["reason"] == ei.REASON_BAD_OUTPUT


# ---------------------------------------------------------------------------
# 解析と正規化
# ---------------------------------------------------------------------------
def test_parse_uses_structured_output_and_configured_model(monkeypatch):
    capture = {}
    _install_fake_anthropic(monkeypatch, payload=FULL_PAYLOAD, capture=capture)
    result = ei.parse_event_template("■ 公演概要の設定\n■ タイムテーブル設定")

    assert result["ok"] is True
    assert capture["model"] == ei.INTAKE_MODEL
    fmt = capture["output_config"]["format"]
    assert fmt["type"] == "json_schema", "構造化出力を使っていない"
    assert fmt["schema"]["additionalProperties"] is False


def test_blank_artists_are_dropped(monkeypatch):
    _install_fake_anthropic(monkeypatch, payload=FULL_PAYLOAD)
    data = ei.parse_event_template("x")["data"]
    assert data["artists"] == ["NecroA", "PRIBEAST", "ZEKECODE"], "空欄の出演者が残っている"


def test_empty_tickets_and_free_texts_are_dropped(monkeypatch):
    _install_fake_anthropic(monkeypatch, payload=FULL_PAYLOAD)
    data = ei.parse_event_template("x")["data"]
    assert len(data["tickets"]) == 2
    assert len(data["free_texts"]) == 1


# ---------------------------------------------------------------------------
# 必須検証
# ---------------------------------------------------------------------------
def test_validate_ok_for_full_payload(monkeypatch):
    _install_fake_anthropic(monkeypatch, payload=FULL_PAYLOAD)
    ok, missing = ei.validate_intake(ei.parse_event_template("x"))
    assert ok is True and missing == []


@pytest.mark.parametrize(
    "overrides,expected",
    [
        ({"event_date": None}, ["開催日"]),
        ({"event_date": "らいねんの11月3日"}, ["開催日"]),  # 日付として読めない
        ({"event_name": None}, ["イベント名"]),
        ({"artists": []}, ["出演者(1組以上)"]),
        ({"event_date": None, "artists": []}, ["開催日", "出演者(1組以上)"]),
    ],
)
def test_validate_reports_missing_fields(monkeypatch, overrides, expected):
    payload = dict(FULL_PAYLOAD)
    payload.update(overrides)
    _install_fake_anthropic(monkeypatch, payload=payload)
    ok, missing = ei.validate_intake(ei.parse_event_template("x"))
    assert ok is False
    assert missing == expected


# ---------------------------------------------------------------------------
# エコー整形
# ---------------------------------------------------------------------------
def test_echo_contains_key_fields_and_numbered_artists(monkeypatch):
    _install_fake_anthropic(monkeypatch, payload=FULL_PAYLOAD)
    echo = ei.format_intake_echo(ei.parse_event_template("x"))

    assert "rock field ULTRA LIVE" in echo
    assert "2026-11-03" in echo
    assert "上野音横丁" in echo
    assert "11:30 / 12:00" in echo
    assert "前売 3000円" in echo
    assert "当日 3500円" in echo
    assert "【出演者 3組】" in echo
    assert "1. NecroA" in echo and "3. ZEKECODE" in echo
    assert "終演5分後から60分" in echo
    assert "4組ごとに10分" in echo
    assert echo.rstrip().endswith(ei.ECHO_FOOTER), "作成は次のステップ、の一文が末尾に無い"


def test_echo_previews_long_free_text(monkeypatch):
    _install_fake_anthropic(monkeypatch, payload=FULL_PAYLOAD)
    echo = ei.format_intake_echo(ei.parse_event_template("x"))
    assert "あ" * 120 not in echo, "長い自由記述がそのまま出ている"
    assert "…" in echo


def test_echo_handles_empty_payload():
    """必須が空でも例外にならず「未記入」で出る(bot が必ず何か返せるように)。"""
    echo = ei.format_intake_echo({"ok": True, "reason": None, "data": {}})
    assert "(未記入)" in echo
    assert ei.ECHO_FOOTER in echo


# ---------------------------------------------------------------------------
# ステートレス判定
# ---------------------------------------------------------------------------
def test_template_itself_is_detected_as_filled_shape():
    """配ったテンプレの見出しがそのまま判定に使える。"""
    assert ei.looks_like_filled_template(ei.MSG_INTAKE_TEMPLATE) is True


@pytest.mark.parametrize(
    "text,expected",
    [
        ("", False),
        ("新規作成", False),
        ("■ 公演概要の設定\n開催日: 2026-11-03", False),          # 見出し1つでは不足
        ("公演概要の設定\n料金設定", True),                        # 2つで成立
        ("公演概要の設定\nアー写グリッド設定\nタイムテーブル設定", True),
        ("フライヤーください", False),
    ],
)
def test_looks_like_filled_template(text, expected):
    assert ei.looks_like_filled_template(text) is expected


def test_template_contains_all_sections_and_slots():
    """確定版テンプレ(「→」区切り・■ / 《《 》》 見出し)の構造を固定する。"""
    t = ei.MSG_INTAKE_TEMPLATE
    for heading in ei.SECTION_HEADINGS:
        assert heading in t, f"テンプレに見出し {heading} が無い"
    # 出演者は 1〜30 の枠が全部ある
    for i in (1, 15, 30):
        assert "出演者%d→" % i in t, f"出演者{i} の枠が無い"
    assert "出演者31→" not in t
    # チケット 3 種 × 名前/金額/備考
    for i in (1, 2, 3):
        for field in ("名前", "金額", "備考"):
            assert "チケット%d %s→" % (i, field) in t, f"チケット{i} {field} の枠が無い"
    # 自由記述 2 件 × 件名/内容(↓…↓ 形式)
    for i in (1, 2):
        assert "↓自由記述%d 件名↓" % i in t
        assert "↓自由記述%d 内容↓" % i in t
    # TT 設定
    for slot in ("物販スペース→", "出演尺(分)→", "終演後物販→",
                 "物販開始までの分→", "転換_N組ごと→", "転換_分→"):
        assert slot in t, f"TT設定の枠 {slot} が無い"
    # 返信時のメンション案内(これが無いと解析フローに入らない)
    assert "メンションを付けて" in t
    # 自由記述セクションは 《《 》》 見出し
    assert "《《" in t and "》》" in t
