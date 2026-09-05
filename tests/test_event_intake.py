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
    "event_type": "girls",
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


class _FakeToolUseBlock:
    """tool_use ブロックの最小モック(.type / .name / .input だけ見ている)。"""

    def __init__(self, name, payload):
        self.type = "tool_use"
        self.name = name
        self.input = payload


class _FakeTextBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _FakeResponse:
    def __init__(self, blocks, stop_reason="tool_use"):
        self.content = blocks
        self.stop_reason = stop_reason


def _install_fake_anthropic(monkeypatch, payload=None, raise_exc=None, capture=None,
                            blocks=None):
    """anthropic モジュールを偽物に差し替える(実 API を叩かない)。

    既定では INTAKE_TOOL_NAME の tool_use ブロックを 1 つ返す。
    blocks を渡すと応答ブロックをそのまま差し替えられる(異常系用)。
    """
    module = types.ModuleType("anthropic")

    if blocks is None:
        blocks = [_FakeToolUseBlock(ei.INTAKE_TOOL_NAME, payload)]

    class _Messages:
        def create(self, **kwargs):
            if capture is not None:
                capture.update(kwargs)
            if raise_exc is not None:
                raise raise_exc
            return _FakeResponse(blocks)

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


def test_no_tool_use_block_returns_reason(monkeypatch):
    """tool_choice で強制していても text しか返らなかった場合に落ちない。"""
    _install_fake_anthropic(
        monkeypatch, blocks=[_FakeTextBlock("すみません、読み取れませんでした")])
    result = ei.parse_event_template("x")
    assert result["ok"] is False
    assert result["reason"] == ei.REASON_BAD_OUTPUT


def test_tool_use_with_other_name_is_ignored(monkeypatch):
    """別 tool の tool_use を誤って採用しない。"""
    _install_fake_anthropic(
        monkeypatch, blocks=[_FakeToolUseBlock("some_other_tool", FULL_PAYLOAD)])
    result = ei.parse_event_template("x")
    assert result["ok"] is False
    assert result["reason"] == ei.REASON_BAD_OUTPUT


# ---------------------------------------------------------------------------
# 解析と正規化
# ---------------------------------------------------------------------------
def test_parse_uses_forced_tool_use_and_configured_model(monkeypatch):
    """構造化は tool use + tool_choice 強制で行う。

    ★output_config.format は使えない(厳格スキーマ検証の「union 型 ≤16」に
      このスキーマの 21 union が引っかかり 400 invalid_request になる)。
      同じ理由で strict も付けてはいけない。実 API で確認済みの制約なので、
      うっかり戻さないようテストで固定する。
    """
    capture = {}
    _install_fake_anthropic(monkeypatch, payload=FULL_PAYLOAD, capture=capture)
    result = ei.parse_event_template("■ 公演概要の設定\n■ タイムテーブル設定")

    assert result["ok"] is True
    assert capture["model"] == ei.INTAKE_MODEL

    assert "output_config" not in capture, "output_config は 400 になるので使ってはいけない"

    tools = capture["tools"]
    assert len(tools) == 1
    tool = tools[0]
    assert tool["name"] == ei.INTAKE_TOOL_NAME
    assert tool["input_schema"]["additionalProperties"] is False
    assert "strict" not in tool, "strict を付けると 16 union 制限で 400 になる"

    assert capture["tool_choice"] == {"type": "tool", "name": ei.INTAKE_TOOL_NAME}


def test_schema_exceeds_structured_output_union_limit(monkeypatch):
    """スキーマの union 数が 16 を超えることを記録しておく(切替の根拠)。

    16 以下に収まるようになったら output_config へ戻せるが、その判断は
    実 API で確認してから行うこと。
    """
    def count_unions(node):
        n = 0
        if isinstance(node, dict):
            t = node.get("type")
            if isinstance(t, list) and len(t) > 1:
                n += 1
            for v in node.values():
                n += count_unions(v)
        elif isinstance(node, list):
            for v in node:
                n += count_unions(v)
        return n

    assert count_unions(ei._INTAKE_SCHEMA) > 16


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
@pytest.mark.parametrize("event_type", ["girls", "mens"])
def test_template_itself_is_detected_as_filled_shape(event_type):
    """配ったテンプレの見出しがそのまま受信判定に使える(両種別とも)。"""
    assert ei.looks_like_filled_template(ei.get_intake_template(event_type)) is True


@pytest.mark.parametrize(
    "text,expected",
    [
        ("", False),
        ("新規作成", False),
        ("ガールズイベント", False),        # 種別ボタンの文言では成立しない
        ("メンズイベント", False),
        ("【公演概要】\n2026年11月3日", False),   # 見出し1つでは不足
        ("【公演概要】\n■料金", True),             # 2つで成立
        ("■会場:上野\n■出演者(20組予定)", True),
        ("フライヤーください", False),
    ],
)
def test_looks_like_filled_template(text, expected):
    assert ei.looks_like_filled_template(text) is expected


@pytest.mark.parametrize(
    "event_type,artist_count,label",
    [("girls", 27, "ガールズ"), ("mens", 20, "メンズ")],
)
def test_templates_have_expected_shape(event_type, artist_count, label):
    """告知文フォーマットのテンプレ2種の構造を固定する。"""
    t = ei.get_intake_template(event_type)

    # 先頭が種別行(ステートレスに種別を復元する要)
    assert t.splitlines()[0] == ei.EVENT_TYPE_MARKER + label
    assert ei.detect_event_type(t) == event_type

    # メンション案内(これが無いと埋めた本文が解析フローに入らない)
    assert "メンションを付けて" in t

    # 告知文の骨格
    for heading in ("【公演概要】", "■会場:", "■時間:", "OPEN▶", "START▶",
                    "■料金", "■チケットリンク:", "■出演者",
                    "■チケット・入場に関して"):
        assert heading in t, f"{event_type}: {heading} が無い"

    # 出演者の番号欄が 1..N ちょうど
    lines = t.splitlines()
    assert "1." in lines and "%d." % artist_count in lines
    assert "%d." % (artist_count + 1) not in lines
    assert "(%d組予定)" % artist_count in t

    # 受信判定の見出しが全部含まれる
    for h in ei.SECTION_HEADINGS:
        assert h in t, f"{event_type}: 見出し {h} が無い"


def test_girls_and_mens_differ_only_in_price_and_free_text():
    """種別差は料金と自由記述だけ(項目の骨格は共通)。"""
    g, m = ei.TEMPLATE_GIRLS, ei.TEMPLATE_MENS
    assert g != m
    # ガールズにしかない自由記述ブロック
    assert "■注意事項とご協力のお願い" in g and "■注意事項とご協力のお願い" not in m
    # メンズにしかない自由記述ブロック
    assert "■物販・特典会ご参加時の注意点" in m
    assert "■物販・特典会ご参加時の注意点" not in g
    # 料金の差
    assert "Aチケット ¥2,000(撮影不可)" in g
    assert "Aチケット ¥3,000" in m


# ---------------------------------------------------------------------------
# イベント種別
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "text,expected",
    [
        ("【イベント種別】ガールズ\n以下を…", "girls"),
        ("【イベント種別】メンズ\n以下を…", "mens"),
        ("【イベント種別】ふつう\n…", None),      # 未知のラベル
        ("【公演概要】\n2026年11月3日", None),      # マーカー無し
        ("", None),
    ],
)
def test_detect_event_type(text, expected):
    assert ei.detect_event_type(text) == expected


def test_marker_line_overrides_llm_event_type(monkeypatch):
    """本文の種別行が LLM の抽出値より優先される。"""
    payload = dict(FULL_PAYLOAD, event_type="mens")   # LLM は mens と答えた
    _install_fake_anthropic(monkeypatch, payload=payload)
    data = ei.parse_event_template("【イベント種別】ガールズ\n■料金\n【公演概要】")["data"]
    assert data["event_type"] == "girls", "本文の種別行が優先されていない"


def test_llm_event_type_used_when_marker_missing(monkeypatch):
    """種別行が無いときは LLM の抽出値を使う。"""
    _install_fake_anthropic(monkeypatch, payload=dict(FULL_PAYLOAD, event_type="mens"))
    data = ei.parse_event_template("【公演概要】\n■料金")["data"]
    assert data["event_type"] == "mens"


@pytest.mark.parametrize("bad", ["unknown", "", None, "other"])
def test_unknown_event_type_becomes_none(monkeypatch, bad):
    """enum 外の種別は未設定(None)にそろえる。"""
    _install_fake_anthropic(monkeypatch, payload=dict(FULL_PAYLOAD, event_type=bad))
    data = ei.parse_event_template("【公演概要】\n■料金")["data"]
    assert data["event_type"] is None


def test_event_type_is_not_a_union_in_schema():
    """event_type は enum 文字列で持つ(罠43 の union 数を増やさない)。"""
    prop = ei._INTAKE_SCHEMA["properties"]["event_type"]
    assert prop["type"] == "string", "union にすると 16 制限に近づく"
    assert set(prop["enum"]) == {"girls", "mens", "unknown"}
    assert "event_type" in ei._INTAKE_SCHEMA["required"]


def test_echo_shows_event_type(monkeypatch):
    _install_fake_anthropic(monkeypatch, payload=FULL_PAYLOAD)
    echo = ei.format_intake_echo(ei.parse_event_template("【イベント種別】ガールズ\n■料金\n■会場"))
    assert "イベント種別: ガールズ" in echo


def test_echo_shows_unset_event_type():
    echo = ei.format_intake_echo({"ok": True, "reason": None, "data": {}})
    assert "イベント種別: 未設定" in echo


# ---------------------------------------------------------------------------
# 自由記述の件数
# ---------------------------------------------------------------------------
def test_free_texts_allow_three_blocks(monkeypatch):
    """メンズの 3 ブロック(チケット入場 / 注意事項 / 物販特典会)を結合せず保持する。

    アプリ側は自由記述の件数に制限が無い(UI は無制限に追加でき、
    free_text_json は生 list、概要テキスト生成も全件ループ)ので、
    3 件をそのまま持てることを固定する。
    """
    payload = dict(FULL_PAYLOAD, free_texts=[
        {"title": "■チケット・入場に関して", "body": "入場は…"},
        {"title": "■注意事項", "body": "ジャンプの禁止…"},
        {"title": "■物販・特典会ご参加時の注意点", "body": "出演者毎の決まりに…"},
    ])
    _install_fake_anthropic(monkeypatch, payload=payload)
    data = ei.parse_event_template("x")["data"]
    assert len(data["free_texts"]) == 3
    assert data["free_texts"][2]["title"] == "■物販・特典会ご参加時の注意点"
    assert ei.MAX_FREE_TEXTS >= 3
