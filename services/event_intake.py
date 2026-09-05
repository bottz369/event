"""記入テンプレの送出 / LLM 解析 / エコー確認(段階C C-1・§52)。

役割:
  LINE から「新規作成」と言われたら記入テンプレを配り、埋めて返ってきたテキストを
  Anthropic の構造化出力で寛容にパースして、解釈結果を人が確認できる形に整える。

設計上の約束:
  - **streamlit を import しない**(罠39)。Bot / API 経路から呼ばれるため。
  - **DB に触らない**。C-1 は解析とエコー確認だけで、プロジェクト作成は C-2。
  - **ステートレス**。埋めたテンプレは自己完結しており、会話メモリ(pending)を持たない。
    「埋めて返ってきたテンプレか」は本文の見出しだけで判定する(looks_like_filled_template)。
  - `anthropic` は関数内で遅延 import する。未 install / API キー未設定でも
    `import services.event_intake` は失敗しない(bot の import チェーンを壊さない)。

戻り値の約束:
  parse_event_template は例外を投げず、必ず {"ok": bool, "reason": str|None, "data": dict|None}
  を返す。呼び出し側(bot)は reason を見て案内文を出し分ける。webhook を落とさないため。
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

# 構造化抽出用途なのでこのクラスで十分(谷内さん指定: Haiku/Sonnet クラスで可)。
# 差し替えはこの 1 行だけで済むようにしておく。
INTAKE_MODEL = "claude-sonnet-5"

# 出演者・チケット・自由記述の上限(テンプレと schema の両方で使う)
MAX_ARTISTS = 30
MAX_TICKETS = 3
MAX_FREE_TEXTS = 2

# 抽出に使う tool の名前。構造化出力(output_config.format)ではなく
# tool use(function calling)で構造化する。理由は _INTAKE_SCHEMA のコメント参照。
INTAKE_TOOL_NAME = "record_event_intake"

# 解析結果の失敗理由(bot 側の文言出し分けに使う)
REASON_NO_API_KEY = "no_api_key"
REASON_SDK_MISSING = "sdk_missing"
REASON_API_ERROR = "api_error"
REASON_BAD_OUTPUT = "bad_output"

# ---------------------------------------------------------------------------
# 記入テンプレ
# ---------------------------------------------------------------------------
# セクション見出し。★ステートレス判定の要:埋めて返ってきたテンプレかどうかを
# この見出しが本文に複数あるかで判定する(pending を持たないため)。
SECTION_HEADINGS = (
    "公演概要の設定",
    "料金設定",
    "アー写グリッド設定",
    "タイムテーブル設定",
    "自由記述",
)

# 「埋めたテンプレ」とみなす見出しの最低ヒット数
FILLED_TEMPLATE_MIN_HEADINGS = 2


def _artist_lines() -> str:
    """出演者の記入枠(1〜MAX_ARTISTS)。区切りは確定版に合わせて「→」。"""
    return "\n".join("出演者%d→" % i for i in range(1, MAX_ARTISTS + 1))


# 谷内さん確定版の記入テンプレ本文。
# ★差し替えるときはこの文字列だけを直す。SECTION_HEADINGS を変えなければ
#   受信判定(looks_like_filled_template)はそのまま動く。
MSG_INTAKE_TEMPLATE = (
    """以下をコピーして、分かる範囲で埋めて送り返してください。
空欄のままでも大丈夫です(あとから直せます)。

送り返す際は必ず【僕(@BOTTZ AI)にメンションを付けて】送信お願いします。



■ 公演概要の設定
開催日→yyyy/mm/dd
イベント名→rock field ULTRA LIVE
サブタイトル→
会場→上野恩賜公園野外ステージ
会場URL→https://maps.app.goo.gl/XcXRo38igMB97WGT7?g_st=ipc
OPEN→00:00
START→00:00
開場開演備考→※開場開演時間は変更になる場合がございます



■ 料金設定
チケット共通備考→※各ドリンク代別

チケット1 名前→Sチケット
チケット1 金額→¥6,000
チケット1 備考→前方エリア・指定グループ静止画撮影可能

チケット2 名前→Aチケット
チケット2 金額→¥2,000
チケット2 備考→撮影不可

チケット3 名前→当日
チケット3 金額→各+¥1,000
チケット3 備考→なし



■ アー写グリッド設定
出演順に上から書いてください(空欄はとばします)。
"""
    + _artist_lines()
    + """



■ タイムテーブル設定
物販スペース→A〜E
出演尺(分)→15分
終演後物販→なし
物販開始までの分→5分
物販尺(分):→60分
転換_N組ごと→５組ごと
転換_分→5分





《《　自由記述　》》



↓自由記述1 件名↓
■チケット・入場に関して



↓自由記述1 内容↓
入場はSチケット→Aチケット→当日券
の順に、整理番号順に行います。
また、お手荷物を置いての場所取り等は一切禁止とさせて頂きます。
※未就学児入場不可
※営利目的の転売禁止
※当イベントではBOT(ボット)などのツールを使用しての不正チケット購入を禁止しています。なお、不正購入が１枚でも発覚した場合は、お持ちのチケットは全て無効となり、今後の関連イベントの入場をお断りします。その際の払い戻しは一切致しません。
※公演中止を除き、いかなる理由でもチケットの払い戻しは致しません
※出演者及び公演スケジュールは予告なく変更となる場合がございます。尚、この場合においてもチケット払い戻しは致しません。



↓自由記述2 件名↓
【注意事項とご協力のお願い】



↓自由記述2 内容↓
※スタッフの注意や警告をお聞き頂けない場合、ご退場をお願いすることがございます。その際のチケット代の返金等は出来兼ねますので、ご理解ご了承の程、宜しくお願い致します。
※出演者・出演＆特典会時間はメンバーの体調不良やスケジュールの都合等の理由により、変更になる可能性がありますので予めご了承下さい。その際の返金などは一切応じられませんので予めご了承ください。
※イベントなど開始時間、終了時間が変更になる可能性もございますので、予めご了承ください。
※シートや荷物、私物等での席取り等は全面的に禁止いたします。移動時は、お荷物をご持参頂きますよう、宜しくお願い致します。
また、撤去した物、及び放置されている物に関して盗難・破損など主催者・会場・出演者は一切の責任を負いません。
※当日はご購入頂きましたチケットの番号順にお呼び致します。
※お荷物、貴重品の管理はお客様ご自身で管理お願い致します。盗難の際は弊社は一切の責任を負いませんのでご了承下さい。
※会場内でのトラブルや、お客様同士での怪我、破損時は弊社は一切の責任を負いませんのでご了承下さい。
※会場内は、入場規制をかける場合がございます。予めご了承の程、宜しくお願い申し上げます。
"""
)


def looks_like_filled_template(text: str) -> bool:
    """埋めて返ってきたテンプレとみなせるか(ステートレス判定)。

    セクション見出しが FILLED_TEMPLATE_MIN_HEADINGS 個以上含まれていれば真。
    テンプレを配ってから何日空いても、本文だけで判定できる。
    """
    if not text:
        return False
    hits = sum(1 for h in SECTION_HEADINGS if h in text)
    return hits >= FILLED_TEMPLATE_MIN_HEADINGS


# ---------------------------------------------------------------------------
# LLM 解析
# ---------------------------------------------------------------------------
_SYSTEM_PROMPT = (
    "あなたはライブイベントの記入テンプレを読み取る抽出器です。"
    "記入ゆれを寛容に解釈し、スキーマどおりの構造化データだけを返してください。\n"
    "\n"
    "テンプレの形:\n"
    "- 「■ 見出し」でセクションが区切られ、自由記述だけ「《《 自由記述 》》」で始まる。\n"
    "- 各項目は「項目名→値」の形。矢印の右が値。値が空なら未記入。\n"
    "- 項目名に「:」が混ざることがある(例「物販尺(分):→60分」)。無視してよい。\n"
    "- 自由記述は「↓自由記述1 件名↓」「↓自由記述1 内容↓」の次の行以降が値。"
    "内容は複数行になる。次の「↓…↓」または末尾までが 1 件の内容。\n"
    "\n"
    "読み取りの規則:\n"
    "- 全角/半角、空白、改行のゆれは吸収する(「５組ごと」→ 5、「15分」→ 15)。\n"
    "- 開催日は YYYY-MM-DD に正規化する(「2026/11/03」「11月3日」など)。"
    "年が書かれていなければ最も近い将来の年を補う。\n"
    "- 時刻は HH:MM(24時間)に正規化する。\n"
    "- 金額は数値だけを取り出す(「¥6,000」→ 6000、「各+¥1,000」→ 1000)。"
    "読み取れなければ null。\n"
    "- 「なし」「未定」「yyyy/mm/dd」「00:00」のようなプレースホルダのままの値、"
    "および空欄は未記入として null(配列なら要素を作らない)。\n"
    "- 出演者は書かれた順のまま。空欄の番号は詰めて、実在する名前だけを配列にする。\n"
    "- 終演後物販は「あり/なし」を真偽に直す。\n"
    "- 書かれていない情報を推測して埋めない。分からないものは null にする。"
)

# 抽出スキーマ。tool の input_schema として渡す。
#
# ★output_config.format(構造化出力)では使えない。厳格スキーマ検証が
#   「union 型のパラメータは 16 個まで」を要求し、このスキーマは 21 個の union
#   (["string", "null"] 等)を持つため 400 invalid_request になる(実 API で確認)。
#   tool use の input_schema には同じ制限が無く、そのまま通る。
#   同じ理由で tool に strict=True を付けてはいけない(厳格検証が働き 400 になる)。
_INTAKE_SCHEMA = {
    "type": "object",
    "properties": {
        "event_date": {"type": ["string", "null"], "description": "開催日 YYYY-MM-DD"},
        "event_name": {"type": ["string", "null"]},
        "subtitle": {"type": ["string", "null"]},
        "venue": {"type": ["string", "null"]},
        "venue_url": {"type": ["string", "null"]},
        "open_time": {"type": ["string", "null"], "description": "HH:MM"},
        "start_time": {"type": ["string", "null"], "description": "HH:MM"},
        "open_start_note": {"type": ["string", "null"], "description": "開場開演備考"},
        "ticket_common_note": {"type": ["string", "null"]},
        "tickets": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": ["string", "null"]},
                    "price": {"type": ["integer", "null"]},
                    "note": {"type": ["string", "null"]},
                },
                "required": ["name", "price", "note"],
                "additionalProperties": False,
            },
        },
        "artists": {"type": "array", "items": {"type": "string"}},
        "tt_settings": {
            "type": "object",
            "properties": {
                "goods_spaces": {"type": ["string", "null"], "description": "物販スペース"},
                "set_minutes": {"type": ["integer", "null"], "description": "出演尺(分)"},
                "has_post_goods": {"type": ["boolean", "null"], "description": "終演後物販の有無"},
                "goods_start_offset_minutes": {"type": ["integer", "null"]},
                "goods_duration_minutes": {"type": ["integer", "null"]},
                "changeover_every_n": {"type": ["integer", "null"], "description": "転換 N組ごと"},
                "changeover_minutes": {"type": ["integer", "null"], "description": "転換 分"},
            },
            "required": [
                "goods_spaces",
                "set_minutes",
                "has_post_goods",
                "goods_start_offset_minutes",
                "goods_duration_minutes",
                "changeover_every_n",
                "changeover_minutes",
            ],
            "additionalProperties": False,
        },
        "free_texts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": ["string", "null"]},
                    "body": {"type": ["string", "null"]},
                },
                "required": ["title", "body"],
                "additionalProperties": False,
            },
        },
    },
    "required": [
        "event_date",
        "event_name",
        "subtitle",
        "venue",
        "venue_url",
        "open_time",
        "start_time",
        "open_start_note",
        "ticket_common_note",
        "tickets",
        "artists",
        "tt_settings",
        "free_texts",
    ],
    "additionalProperties": False,
}


def _fail(reason: str) -> dict:
    return {"ok": False, "reason": reason, "data": None}


def _log_api_error(e: Exception) -> None:
    """API 例外から取れるだけの手がかりをログに残す。

    「解析に失敗しました」だけでは本番で原因が分からないため、
    HTTP status / レスポンス body / request-id をログに出す。
    body は長くなりうるので先頭 1000 文字で切る。
    """
    status = getattr(e, "status_code", None)
    if status is None:
        status = getattr(getattr(e, "response", None), "status_code", None)

    detail = getattr(e, "body", None)
    if detail is not None:
        try:
            detail = json.dumps(detail, ensure_ascii=False)
        except Exception:
            detail = str(detail)
    else:
        resp = getattr(e, "response", None)
        try:
            detail = resp.text if resp is not None else None
        except Exception:
            detail = None

    logger.error(
        "intake parse API call failed: type=%s status=%s request_id=%s body=%s msg=%s",
        type(e).__name__,
        status,
        getattr(e, "request_id", None),
        (detail or "")[:1000],
        e,
        exc_info=True,
    )


def parse_event_template(text: str) -> dict:
    """記入テンプレを Anthropic の tool use(function calling)でパースする。

    構造化の方法として tool use を使い、tool_choice でその tool の呼び出しを強制する。
    返ってきた tool_use ブロックの .input が抽出結果の dict。
    (output_config.format を使わない理由は _INTAKE_SCHEMA のコメント参照)

    戻り値: {"ok": bool, "reason": str|None, "data": dict|None}
    ★例外を外へ投げない。API キー未設定・SDK 未 install・API 障害はすべて
      reason 付きの失敗として返し、呼び出し側(bot)が案内文を出す。
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.warning("ANTHROPIC_API_KEY is not set; skipping intake parse")
        return _fail(REASON_NO_API_KEY)

    try:
        import anthropic  # 遅延 import(未 install でもモジュール import は通す)
    except ImportError as e:
        logger.error("anthropic SDK is unavailable: %s", e)
        return _fail(REASON_SDK_MISSING)

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=INTAKE_MODEL,
            max_tokens=16000,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": text}],
            tools=[{
                "name": INTAKE_TOOL_NAME,
                "description": "記入テンプレから読み取ったイベント情報を記録する",
                # ★strict は付けない(付けると 16 union 制限で 400 になる)
                "input_schema": _INTAKE_SCHEMA,
            }],
            # この tool の呼び出しを強制する(自由文で返させない)
            tool_choice={"type": "tool", "name": INTAKE_TOOL_NAME},
        )
    except Exception as e:
        _log_api_error(e)
        return _fail(REASON_API_ERROR)

    data = next(
        (b.input for b in response.content
         if getattr(b, "type", None) == "tool_use"
         and getattr(b, "name", None) == INTAKE_TOOL_NAME),
        None,
    )
    if not isinstance(data, dict):
        logger.error(
            "intake parse returned no tool_use block: stop_reason=%s types=%s",
            getattr(response, "stop_reason", None),
            [getattr(b, "type", None) for b in (response.content or [])],
        )
        return _fail(REASON_BAD_OUTPUT)

    return {"ok": True, "reason": None, "data": _normalize(data)}


def _clean_str(v) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _normalize(data: dict) -> dict:
    """LLM 出力を後段が扱いやすい形に整える(空欄除去・型そろえ)。

    schema で縛ってはいるが、空文字や空要素は残りうるのでここで落とす。
    出演者の空欄除去(仕様)もここで行う。
    """
    out = dict(data)

    for key in (
        "event_date", "event_name", "subtitle", "venue", "venue_url",
        "open_time", "start_time", "open_start_note", "ticket_common_note",
    ):
        out[key] = _clean_str(out.get(key))

    # 出演者: 空欄をとばして最大 MAX_ARTISTS 件
    artists = []
    for a in (out.get("artists") or []):
        name = _clean_str(a)
        if name:
            artists.append(name)
    out["artists"] = artists[:MAX_ARTISTS]

    # チケット: 名前も金額も無い行は落とす
    tickets = []
    for t in (out.get("tickets") or []):
        if not isinstance(t, dict):
            continue
        name, price, note = _clean_str(t.get("name")), t.get("price"), _clean_str(t.get("note"))
        if name is None and price is None:
            continue
        tickets.append({"name": name, "price": price, "note": note})
    out["tickets"] = tickets[:MAX_TICKETS]

    # 自由記述: 件名も内容も無い行は落とす
    free_texts = []
    for f in (out.get("free_texts") or []):
        if not isinstance(f, dict):
            continue
        title, body = _clean_str(f.get("title")), _clean_str(f.get("body"))
        if title is None and body is None:
            continue
        free_texts.append({"title": title, "body": body})
    out["free_texts"] = free_texts[:MAX_FREE_TEXTS]

    tt = out.get("tt_settings")
    out["tt_settings"] = tt if isinstance(tt, dict) else {}
    return out


# ---------------------------------------------------------------------------
# 検証
# ---------------------------------------------------------------------------
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def validate_intake(parsed: dict) -> Tuple[bool, List[str]]:
    """必須項目(開催日 / イベント名 / 出演者1人以上)を検証する。

    戻り値: (ok, 不足している項目名のリスト)
    日付が YYYY-MM-DD として読めない場合も「開催日」を不足に入れる。
    """
    data = (parsed or {}).get("data") or {}
    missing: List[str] = []

    date = data.get("event_date")
    if not date or not _DATE_RE.match(str(date)):
        missing.append("開催日")
    if not data.get("event_name"):
        missing.append("イベント名")
    if not data.get("artists"):
        missing.append("出演者(1組以上)")

    return (not missing), missing


# ---------------------------------------------------------------------------
# エコー確認の整形
# ---------------------------------------------------------------------------
ECHO_FOOTER = "※内容はこの解釈です。作成は次のステップ(準備中)"

_FREE_TEXT_PREVIEW = 40


def _preview(text: Optional[str], limit: int = _FREE_TEXT_PREVIEW) -> str:
    if not text:
        return "(なし)"
    one_line = " ".join(str(text).split())
    if len(one_line) <= limit:
        return one_line
    return one_line[:limit] + "…"


def _or_dash(v) -> str:
    return "(未記入)" if v in (None, "", []) else str(v)


def format_intake_echo(parsed: dict) -> str:
    """解析結果を人が確認できるテキストに整える。

    長い自由記述は先頭だけプレビューする(LINE の 1 通が長くなりすぎないため)。
    """
    data = (parsed or {}).get("data") or {}
    lines: List[str] = ["読み取った内容を確認してください。", ""]

    lines.append("【公演概要】")
    lines.append("イベント名: %s" % _or_dash(data.get("event_name")))
    if data.get("subtitle"):
        lines.append("サブタイトル: %s" % data["subtitle"])
    lines.append("開催日: %s" % _or_dash(data.get("event_date")))
    lines.append("会場: %s" % _or_dash(data.get("venue")))
    if data.get("venue_url"):
        lines.append("会場URL: %s" % data["venue_url"])
    lines.append("OPEN / START: %s / %s"
                 % (_or_dash(data.get("open_time")), _or_dash(data.get("start_time"))))
    if data.get("open_start_note"):
        lines.append("開場開演備考: %s" % data["open_start_note"])

    lines.append("")
    lines.append("【料金】")
    tickets = data.get("tickets") or []
    if tickets:
        for t in tickets:
            price = "%s円" % t["price"] if t.get("price") is not None else "(金額未記入)"
            row = "・%s %s" % (_or_dash(t.get("name")), price)
            if t.get("note"):
                row += " (%s)" % t["note"]
            lines.append(row)
    else:
        lines.append("(未記入)")
    if data.get("ticket_common_note"):
        lines.append("共通備考: %s" % data["ticket_common_note"])

    lines.append("")
    artists = data.get("artists") or []
    lines.append("【出演者 %d組】" % len(artists))
    if artists:
        for i, name in enumerate(artists, 1):
            lines.append("%d. %s" % (i, name))
    else:
        lines.append("(未記入)")

    lines.append("")
    lines.append("【タイムテーブル設定】")
    tt = data.get("tt_settings") or {}
    lines.append("物販スペース: %s" % _or_dash(tt.get("goods_spaces")))
    lines.append("出演尺: %s分" % _or_dash(tt.get("set_minutes")))
    if tt.get("has_post_goods") is not None:
        lines.append("終演後物販: %s" % ("あり" if tt["has_post_goods"] else "なし"))
    lines.append("物販: 終演%s分後から%s分"
                 % (_or_dash(tt.get("goods_start_offset_minutes")),
                    _or_dash(tt.get("goods_duration_minutes"))))
    if tt.get("changeover_every_n") or tt.get("changeover_minutes"):
        lines.append("転換: %s組ごとに%s分"
                     % (_or_dash(tt.get("changeover_every_n")),
                        _or_dash(tt.get("changeover_minutes"))))

    free_texts = data.get("free_texts") or []
    if free_texts:
        lines.append("")
        lines.append("【自由記述】")
        for f in free_texts:
            lines.append("・%s: %s" % (_or_dash(f.get("title")), _preview(f.get("body"))))

    lines.append("")
    lines.append(ECHO_FOOTER)
    return "\n".join(lines)
