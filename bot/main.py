"""BOTTZ AI — LINE Bot 本体(FastAPI Webhook / §40 B4 アー写更新)。

構成方針:
- モノリス Bot(§40 決定2)。既存 services を直 import して再利用し、新規 DB ロジックは書かない。
  DB/画像に触る処理(get_artists_by_names / update_artist)は関数内で遅延 import する。
  これにより `import bot.main` は SUPABASE_* env 未設定でも失敗しない(import 時に database を
  ロードしない=起動時/リクエスト時に初めて解決する)。
- LINE 連携は公式 SDK ではなく素の HTTP(requests + 標準ライブラリの hmac/hashlib/base64)で実装する。
  §40 で「line-bot-sdk(または生 HTTP)」と明記された選択肢のうち生 HTTP を採る。依存を最小化し、
  署名検証・名前抽出・pending TTL を純関数として import 非依存にユニットテストできるため。

セキュリティ(§40 ガード原則):
- 署名検証必須(X-Line-Signature = channel secret の HMAC-SHA256 → base64)。不一致は 400。
- 実行は「(1)グループ発 (2)送信者 userId が OWNER_USER_IDS (3)テキストで自ボット宛メンション」を
  全て満たす時のみ。DM は完全無視。

秘密情報はコードに持たない。全て環境変数から遅延読み込みする(bot/.env.example 参照)。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import requests
from fastapi import FastAPI, Request, Response

from bot import api  # read 専用 /api ルーター(§11.7 段階A0)。services は遅延 import のため env 非依存。

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bottz_bot")

# --- LINE API エンドポイント ---
LINE_REPLY_ENDPOINT = "https://api.line.me/v2/bot/message/reply"
LINE_CONTENT_ENDPOINT = "https://api-data.line.me/v2/bot/message/{message_id}/content"

# アー写更新の pending 有効期間(テキスト受信 → 画像受信の待ち・§40 = 5 分)。
PENDING_TTL_SECONDS = 5 * 60

# 名前抽出で「○○」の右端に来る合図(この手前を名前候補とみなす)。
# B-3.1: 入口の合図。★名前はテキストから読まない(完全ボタン対話)。
# メンション + マーカーだけで、あとはボタンで選ばせる。
#   REPLACE … アー写を差し替えてから 2 枚生成
#   GET     … 写真は変えず 2 枚だけ取得
_REPLACE_MARKERS = ("アー写変更", "アー写差し替え", "アー写差替", "アー写更新",
                    "写真変更", "写真差し替え", "写真差替")
_GET_MARKERS = ("最新", "フライヤー", "再生成")

# B-4: グループ起動の合図
_ACTIVATE_MARKERS = ("起動",)

# 段階C C-1: 記入テンプレを配る合図(§52)
_INTAKE_MARKERS = ("新規作成",)

# ---------------------------------------------------------------------------
# 返信文言(B-4)。★後で文言だけ直したいときのために 1 箇所へ集約する。
# ---------------------------------------------------------------------------
MSG_ALREADY_ACTIVE = "すでに起動しています。メンションを付けてご依頼ください。"
MSG_ACTIVATED = (
    "起動しました。メンションを付けてご依頼ください。"
    "グループラインに参加している【全員】が僕を利用可能です。"
)
MSG_ACTIVATE_DENIED = (
    "BOTTZからの指示で起動します。BOTTZをこのグループラインへ招待してください。"
)
MSG_NOT_ACTIVATED = (
    "このグループはまだ起動していません。"
    "オーナーが「起動」と送ると、参加者全員が使えるようになります。"
)
# --- 段階C C-1: 記入テンプレのやりとり ---
MSG_INTAKE_PARSING = "受け取りました。読み取り中です…(数秒お待ちください)"
MSG_INTAKE_FAILED = "解析に失敗しました。もう一度お試しください。"
MSG_INTAKE_NO_API_KEY = (
    "解析機能が未設定のため読み取れませんでした。管理者にご連絡ください。"
)


def build_intake_missing_message(missing) -> str:
    """必須項目が読み取れなかったときの案内文。"""
    return "%s が読み取れませんでした。記入して再送してください。" % "、".join(missing)


MSG_OWNER_LEFT = (
    "BOTTZがグループラインから退会したので機能を停止します。"
    "再開する場合はBOTTZをこのグループラインへ招待してください。"
)


# ---------------------------------------------------------------------------
# 設定(環境変数からの遅延読み込み。import 時には読まない)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class BotConfig:
    channel_secret: str
    channel_access_token: str
    owner_user_ids: frozenset
    allowed_group_ids: frozenset


def _parse_id_set(raw: Optional[str]) -> frozenset:
    """カンマ区切りの ID 文字列を空要素を除いた frozenset にする。"""
    if not raw:
        return frozenset()
    return frozenset(part.strip() for part in raw.split(",") if part.strip())


def load_config() -> BotConfig:
    """環境変数から Bot 設定を読む(呼び出しのたびに現在の env を反映)。"""
    return BotConfig(
        channel_secret=os.environ.get("LINE_CHANNEL_SECRET", ""),
        channel_access_token=os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", ""),
        owner_user_ids=_parse_id_set(os.environ.get("OWNER_USER_IDS")),
        allowed_group_ids=_parse_id_set(os.environ.get("ALLOWED_GROUP_IDS")),
    )


# ---------------------------------------------------------------------------
# 純関数: 署名検証 / 名前抽出 / メンション処理(ユニットテスト対象)
# ---------------------------------------------------------------------------
def verify_signature(body: bytes, signature: Optional[str], channel_secret: str) -> bool:
    """X-Line-Signature を channel secret の HMAC-SHA256(base64)と定数時間比較で検証する。"""
    if not channel_secret or not signature:
        return False
    mac = hmac.new(channel_secret.encode("utf-8"), body, hashlib.sha256).digest()
    expected = base64.b64encode(mac).decode("utf-8")
    return hmac.compare_digest(expected, signature)


def is_self_mentioned(mentionees: Optional[List[dict]]) -> bool:
    """メンション先に自ボット(isSelf==true)が含まれるか。"""
    if not mentionees:
        return False
    return any(bool(m.get("isSelf")) for m in mentionees)


def strip_self_mentions(text: str, mentionees: Optional[List[dict]]) -> str:
    """テキストから自ボット宛メンション部(index/length 指定)を除去する。

    LINE の index/length は UTF-16 コードユニット基準だが、ボット表示名は ASCII 想定のため
    コードポイント扱いで十分。後方の span から順に削って index ずれを避ける。
    """
    if not text or not mentionees:
        return text or ""
    spans = [
        (m.get("index"), m.get("length"))
        for m in mentionees
        if m.get("isSelf")
        and isinstance(m.get("index"), int)
        and isinstance(m.get("length"), int)
    ]
    result = text
    for index, length in sorted(spans, key=lambda t: t[0], reverse=True):
        if 0 <= index <= len(result):
            result = result[:index] + result[index + length:]
    return result


# ---------------------------------------------------------------------------
# pending ストア(テキスト → 画像の順待ち・userId 単位・TTL 付き)
# ---------------------------------------------------------------------------
class PendingStore:
    """userId ごとに「画像待ちの (project_id, アーティスト名) + 記録時刻」を TTL 付きで保持する。

    ★B-3.1: payload を名前だけから (pid, artist) に拡張した。
      どのイベント向けの差し替えかはボタンで確定済みなので、画像を受けたら
      そのまま「更新 → その pid の 2 枚生成」まで進める。
    ★ここに入るのは「画像待ち」だけ。会話の選択状態は postback data に埋める。
    時刻(now)は呼び出し側から注入する(テスト決定性のため)。スレッド安全。
    """

    def __init__(self, ttl_seconds: int = PENDING_TTL_SECONDS):
        self._ttl = ttl_seconds
        self._data: Dict[str, Tuple[Tuple[int, str], float]] = {}
        self._lock = threading.Lock()

    def put(self, user_id: str, project_id: int, name: str, now: float) -> None:
        with self._lock:
            self._data[user_id] = ((int(project_id), name), now)

    def pop_valid(self, user_id: str, now: float) -> Optional[Tuple[int, str]]:
        """TTL 内の pending があれば (pid, artist) を返して消費する。無効/期限切れは None。"""
        with self._lock:
            item = self._data.get(user_id)
            if item is None:
                return None
            payload, created = item
            del self._data[user_id]
            if now - created > self._ttl:
                return None
            return payload

    def purge_expired(self, now: float) -> None:
        with self._lock:
            expired = [k for k, (_n, c) in self._data.items() if now - c > self._ttl]
            for k in expired:
                del self._data[k]


# プロセス内シングルトン(LINE は「同一 Bot が 1 プロセス常時起動」前提。§40 Railway 常時起動)。
pending_store = PendingStore()


# ---------------------------------------------------------------------------
# LINE I/O(素の HTTP)
# ---------------------------------------------------------------------------
def download_image(message_id: str, access_token: str, timeout: int = 30) -> Tuple[bytes, str]:
    """message content(画像バイト列)を DL し (bytes, content_type) を返す。"""
    url = LINE_CONTENT_ENDPOINT.format(message_id=message_id)
    resp = requests.get(
        url, headers={"Authorization": f"Bearer {access_token}"}, timeout=timeout
    )
    resp.raise_for_status()
    return resp.content, resp.headers.get("Content-Type", "image/jpeg")


def reply_messages(
    reply_token: str, messages: List[dict], access_token: str, timeout: int = 15
) -> None:
    """reply token で messages 配列をそのまま返信する(best-effort・例外を投げない)。

    ★push ではなく reply を使う: push は無料枠が有限、reply は無制限。
      reply token の有効期限は約 1 分なので、重い生成は先に済ませてから呼ぶこと。
    LINE の 1 リクエスト上限は 5 メッセージ。超過分は落として警告する。
    """
    if not reply_token or not messages:
        return
    if len(messages) > 5:
        logger.warning("too many messages (%d); truncating to 5", len(messages))
        messages = messages[:5]
    try:
        resp = requests.post(
            LINE_REPLY_ENDPOINT,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json={"replyToken": reply_token, "messages": messages},
            timeout=timeout,
        )
        if resp.status_code >= 300:
            logger.warning("reply failed: %s %s", resp.status_code, resp.text[:200])
    except Exception as e:  # 通知失敗で Webhook を落とさない
        logger.warning("reply request error: %s", e)


def reply_text(reply_token: str, text: str, access_token: str, timeout: int = 15) -> None:
    """テキスト 1 通の返信(reply_messages の薄いラッパ)。"""
    reply_messages(
        reply_token, [{"type": "text", "text": text}], access_token, timeout=timeout
    )


# ---------------------------------------------------------------------------
# 段階B B-3: イベント選択クイックリプライ / 生成画像の Storage アップロード
# ---------------------------------------------------------------------------
# LINE のクイックリプライ制約(2026 時点):
#   items <= 13 / action.label <= 20 文字 / postback data <= 300 bytes
# ★選択状態はサーバに持たず postback data に埋める(ステートレス)。
#   pending_store は「テキスト → 画像」の順待ち(既存 B4)専用のまま増やさない。
QUICKREPLY_MAX_ITEMS = 13
QUICKREPLY_LABEL_MAX = 20
POSTBACK_DATA_MAX_BYTES = 300

# postback data の書式(B-3.1: 完全ボタン対話の 4 種別)
#   evt|flow=<replace|get>|pid=<int>   … イベント選択
#   more_evt|flow=<replace|get>|page=<n> … イベント次ページ
#   art|pid=<int>|artist=<name>        … アーティスト選択(差し替え対象)
#   more_art|pid=<int>|page=<n>        … アーティスト次ページ
# ★選択状態はすべてここに埋める(サーバ側の会話ステートは増やさない)。
ACTION_EVENT = "evt"
ACTION_MORE_EVENT = "more_evt"
ACTION_ARTIST = "art"
ACTION_MORE_ARTIST = "more_art"
# 段階C C-1.1: 新規作成のイベント種別選択(§53)
ACTION_NEW_PROJECT = "newproj"

FLOW_REPLACE = "replace"  # アー写を差し替えてから 2 枚生成
FLOW_GET = "get"          # 写真は変えず 2 枚だけ取得
_FLOWS = (FLOW_REPLACE, FLOW_GET)


def _truncate_label(text: str, limit: int = QUICKREPLY_LABEL_MAX) -> str:
    """LINE の label 上限に丸める(超過は末尾を … にする)。"""
    s = (text or "").strip() or "(無題)"
    if len(s) <= limit:
        return s
    return s[: limit - 1] + "…"


def _truncate_utf8(text: str, budget: int) -> str:
    """UTF-8 で budget bytes 以内に収める(マルチバイトの途中で切らない)。"""
    if budget <= 0:
        return ""
    out = []
    used = 0
    for ch in text or "":
        b = len(ch.encode("utf-8"))
        if used + b > budget:
            break
        out.append(ch)
        used += b
    return "".join(out)


def build_postback_data(action: str, **fields) -> str:
    """postback data を組む。300 bytes を超えないよう最後のフィールドだけ丸める。

    例: build_postback_data("art", pid=39, artist="手羽先センセーション")
        -> "art|pid=39|artist=手羽先センセーション"
    丸め対象は可変長になりうる末尾フィールド(artist)のみ。pid / page / flow は短い。
    """
    parts = [action]
    tail_key = None
    tail_val = None
    for k, v in fields.items():
        if k == "artist":
            tail_key, tail_val = k, str(v or "")
            continue
        parts.append("%s=%s" % (k, v))
    head = "|".join(parts)
    if tail_key is None:
        return head
    head = head + "|" + tail_key + "="
    budget = POSTBACK_DATA_MAX_BYTES - len(head.encode("utf-8"))
    return head + _truncate_utf8(tail_val, budget)


def parse_postback_data(data: str) -> Optional[dict]:
    """postback data を {"action":..., ...} に戻す。不正なら None。

    pid / page は int 化する(数値でなければ不正扱い)。未知の action も None。
    """
    if not data:
        return None
    parts = data.split("|")
    action = parts[0]
    if action not in (ACTION_EVENT, ACTION_MORE_EVENT, ACTION_ARTIST,
                      ACTION_MORE_ARTIST, ACTION_NEW_PROJECT):
        return None
    out = {"action": action}
    for p in parts[1:]:
        if "=" not in p:
            continue
        k, v = p.split("=", 1)
        if k in ("pid", "page"):
            try:
                out[k] = int(v)
            except ValueError:
                return None
        else:
            out[k] = v

    # 種別ごとの必須フィールド検査
    if action == ACTION_EVENT:
        if "pid" not in out or out.get("flow") not in _FLOWS:
            return None
    elif action == ACTION_MORE_EVENT:
        if "page" not in out or out.get("flow") not in _FLOWS:
            return None
    elif action == ACTION_ARTIST:
        if "pid" not in out or not out.get("artist"):
            return None
    elif action == ACTION_MORE_ARTIST:
        if "pid" not in out or "page" not in out:
            return None
    elif action == ACTION_NEW_PROJECT:
        # type は services 側の EVENT_TYPES に限る。未知の値は不正扱いにする
        # (テンプレを引けないボタンを通さない)。
        if out.get("type") not in _event_type_values():
            return None
    return out


def _event_label(e) -> Tuple[str, str]:
    """(丸めたラベル, 丸めていない表示テキスト)を返す。"""
    date_part = e.event_date.strftime("%m/%d") if getattr(e, "event_date", None) else "日付未定"
    full = "%s %s" % (date_part, e.title)
    return (_truncate_label(full), full)


def build_event_quickreply(
    events: List[object], flow: str, page: int = 0, has_more: bool = False
) -> dict:
    """イベント選択のクイックリプライを組む(B-3.1)。

    flow="replace" … 差し替えたいイベントを選ぶ
    flow="get"     … フライヤーを出したいイベントを選ぶ
    has_more のとき末尾に【さらに前のイベントを表示】を足す。
    items は 12 件 + ページングボタン 1 = 13(LINE の上限)に収める。
    """
    items = []
    for e in events[:QUICKREPLY_MAX_ITEMS - (1 if has_more else 0)]:
        label, full = _event_label(e)
        items.append({
            "type": "action",
            "action": {
                "type": "postback",
                "label": label,
                "data": build_postback_data(ACTION_EVENT, flow=flow, pid=e.project_id),
                "displayText": full,
            },
        })
    if has_more:
        items.append({
            "type": "action",
            "action": {
                "type": "postback",
                "label": "さらに前のイベントを表示",
                "data": build_postback_data(ACTION_MORE_EVENT, flow=flow, page=int(page) + 1),
                "displayText": "さらに前のイベントを表示",
            },
        })

    prompt = (
        "どのイベントのアー写を差し替えますか?"
        if flow == FLOW_REPLACE
        else "どのイベントのフライヤーを出しますか?"
    )
    return {"type": "text", "text": prompt, "quickReply": {"items": items}}


def build_artist_quickreply(
    project_id: int, artists: List[str], page: int = 0, has_more: bool = False
) -> dict:
    """アーティスト選択のクイックリプライを組む(B-3.1)。

    has_more のとき末尾に【さらに表示】を足す(29 組など 13 を超えるイベント用)。
    """
    items = []
    for name in artists[:QUICKREPLY_MAX_ITEMS - (1 if has_more else 0)]:
        items.append({
            "type": "action",
            "action": {
                "type": "postback",
                "label": _truncate_label(name),
                "data": build_postback_data(ACTION_ARTIST, pid=project_id, artist=name),
                "displayText": name,
            },
        })
    if has_more:
        items.append({
            "type": "action",
            "action": {
                "type": "postback",
                "label": "さらに表示",
                "data": build_postback_data(
                    ACTION_MORE_ARTIST, pid=project_id, page=int(page) + 1
                ),
                "displayText": "さらに表示",
            },
        })
    return {
        "type": "text",
        "text": "どのアーティストのアー写を差し替えますか?",
        "quickReply": {"items": items},
    }


def upload_generated_png(png: bytes, project_id: int, variant: str, now: Optional[float] = None) -> Optional[str]:
    """生成 PNG を Storage に上げ、公開 URL を返す。失敗は None。

    ★キーは (project_id, variant) 固定で毎回上書きする(生成物が無限に増えないように)。
      その代わり CDN / LINE 側のキャッシュを避けるため、返す URL に ?t=<epoch> を付ける。
    DB には何も書かない(Storage のみ)。
    """
    from database import get_image_url, upload_image_to_supabase  # 遅延 import(env 非依存維持)

    filename = "generated/%d/flyer_%s.png" % (int(project_id), variant)
    try:
        saved = upload_image_to_supabase(_NamedBytesIO(png, "flyer_%s.png" % variant), filename)
        if not saved:
            logger.warning("generated image upload failed: %s", filename)
            return None
        url = get_image_url(saved)
        if not url:
            logger.warning("generated image url not available: %s", filename)
            return None
    except Exception as e:
        logger.warning("generated image upload error: %s: %s", type(e).__name__, e)
        return None
    stamp = int(now if now is not None else time.time())
    sep = "&" if "?" in url else "?"
    return "%s%st=%d" % (url, sep, stamp)


def build_preview_png(png: bytes, max_edge: int = 240) -> bytes:
    """LINE の previewImageUrl 用に長辺 max_edge へ縮小した PNG を返す。

    preview は 1MB 目安の制約があるため、フルサイズ(数 MB)をそのまま使わない。
    縮小に失敗したら元の bytes をそのまま返す(送信を止めない)。
    """
    try:
        from PIL import Image  # 遅延 import(env 非依存維持)

        im = Image.open(io.BytesIO(png))
        im.thumbnail((max_edge, max_edge), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, format="PNG")
        return buf.getvalue()
    except Exception as e:
        logger.warning("preview downscale failed: %s: %s", type(e).__name__, e)
        return png


def build_image_message(original_url: str, preview_url: str) -> dict:
    """LINE の image message(URL は HTTPS 必須)。"""
    return {
        "type": "image",
        "originalContentUrl": original_url,
        "previewImageUrl": preview_url or original_url,
    }


# ---------------------------------------------------------------------------
# 段階B B-3: フライヤーセット(2 枚)の生成 → Storage → image message
# ---------------------------------------------------------------------------
FLYER_VARIANTS = ("grid", "tt")
_VARIANT_LABEL = {"grid": "アー写グリッド版", "tt": "タイムテーブル版"}


def render_flyer_set_for_project(project_id: int) -> Tuple[List[dict], List[dict]]:
    """pid のフライヤー 2 枚を生成し、(image message のリスト, failures) を返す。

    ★生成はプロセス内直呼び。Bot と /api は同一 FastAPI プロセスなので HTTP 自己呼び出しはしない。
      failures は Python の list をそのまま受け取る(X-Missing-Assets ヘッダは
      外部クライアント用に温存し、ここではパースしない)。
    生成不能(None)の variant は image message を作らずスキップする。
    生成の直列化は generation_service 側の _render_lock に任せる(ここで追加ロックしない)。
    """
    from services import generation_service  # 遅延 import(bot.main を env 非依存に保つ)

    failures: List[dict] = []
    messages: List[dict] = []

    for variant in FLYER_VARIANTS:
        try:
            png = generation_service.render_flyer_png_for_project(
                project_id, variant=variant, failures=failures
            )
        except Exception as e:
            logger.error(
                "flyer render failed: pid=%s variant=%s: %s", project_id, variant, e,
                exc_info=True,
            )
            continue
        if not png:
            logger.warning("flyer not generated: pid=%s variant=%s", project_id, variant)
            continue

        original_url = upload_generated_png(png, project_id, variant)
        if not original_url:
            continue
        preview_url = upload_generated_png(
            build_preview_png(png), project_id, "%s_preview" % variant
        )
        messages.append(build_image_message(original_url, preview_url or original_url))

    return (messages, failures)


def build_failure_notice(failures: List[dict]) -> Optional[str]:
    """素材取得に失敗した一覧を人間向けの 1 通にまとめる。無ければ None。

    §5 の構造化エントリ {"kind","name","url","reason"} を前提にする。
    2 枚は送ったうえで添える警告なので、断定せず「反映待ちの可能性」に留める。
    """
    if not failures:
        return None
    photos, others = [], []
    for f in failures:
        kind = f.get("kind")
        if kind == "artist_photo":
            name = f.get("name")
            if name and name not in photos:
                photos.append(name)
        elif kind == "flyer_bg":
            others.append("背景画像")
        elif kind == "flyer_logo":
            others.append("ロゴ画像")

    parts = []
    if photos:
        parts.append("アー写: " + " / ".join(photos))
    for o in dict.fromkeys(others):
        parts.append(o)
    if not parts:
        return None
    return (
        "※ 一部の素材を取得できませんでした(" + " , ".join(parts) + ")。\n"
        "アップロード直後で反映待ちの可能性があります。少し待ってからもう一度お試しください。"
    )


# ---------------------------------------------------------------------------
# アー写更新(既存 service へ委譲。DB/画像 import はここで遅延)
# ---------------------------------------------------------------------------
def _ext_from_content_type(content_type: str) -> str:
    ct = (content_type or "").lower()
    if "png" in ct:
        return ".png"
    if "webp" in ct:
        return ".webp"
    return ".jpg"


class _NamedBytesIO(io.BytesIO):
    """artist_service._upload_image が参照する `.name`(拡張子判定用)を持つ BytesIO。

    素の io.BytesIO は属性代入不可なため薄い subclass を用意する。upload_image_to_supabase は
    `.getvalue()` を使うので BytesIO 互換で足りる。
    """

    def __init__(self, data: bytes, name: str):
        super().__init__(data)
        self.name = name


def update_artist_photo(name: str, image_bytes: bytes, content_type: str) -> Tuple[bool, str]:
    """名前でアーティストを特定し画像のみ差し替える。既存 service に委譲。

    戻り値: (成功か, 返信メッセージ)。
    """
    from services import artist_service  # 遅延 import(bot.main を env 非依存に保つ)

    artists = artist_service.get_artists_by_names([name])
    matched = artists[0] if artists else None
    if matched is None:
        return (False, f"「{name}」が見つかりません")

    ext = _ext_from_content_type(content_type)
    file_obj = _NamedBytesIO(image_bytes, f"line_upload{ext}")
    # name は既存名をそのまま渡す(画像のみ差し替え。§40)。
    updated = artist_service.update_artist(matched.id, name=matched.name, image_file=file_obj)
    if updated is None:
        return (False, f"「{matched.name}」の更新に失敗しました")
    return (True, f"{matched.name} のアー写を更新しました")


# ---------------------------------------------------------------------------
# Webhook 処理
# ---------------------------------------------------------------------------
def _source_group_id(source: dict) -> Optional[str]:
    if source.get("type") != "group":
        return None
    return source.get("groupId")


def _passes_group_guard(group_id: Optional[str], config: BotConfig) -> bool:
    """グループ発かどうかだけを見る。DM / ルームは従来どおり不可。

    ★B-4: 静的許可リスト(ALLOWED_GROUP_IDS)によるゲートは撤去した。
      どのグループが使えるかは activation_service(オーナーが「起動」と送ったか)が決める。
      env ALLOWED_GROUP_IDS は互換のため BotConfig に残すが、もう判定には使わない。
    """
    return group_id is not None


_USAGE_TEXT = (
    "使い方(名前の入力は不要です):\n"
    "・新しいイベントを作る → 「新規作成」とメンションしてください\n"
    "・アー写を差し替える → 「アー写変更」とメンションしてください\n"
    "・最新のフライヤーだけ欲しい → 「フライヤー」とメンションしてください\n"
    "そのあとはボタンで選べます。"
)


def _handle_member_left(event: dict, group_id: Optional[str], reply_token: str,
                        config: BotConfig) -> None:
    """オーナーが退会したら、そのグループを無効化して停止を通知する(B-4)。

    オーナー以外の退会は何もしない。既に無効なグループでも何もしない
    (無効化済みに対して停止文言を出すとノイズになる)。
    ★オーナーが再参加しても自動では再有効化しない。再開はオーナーの「起動」で行う。
    """
    members = ((event.get("left") or {}).get("members")) or []
    left_ids = {m.get("userId") for m in members if isinstance(m, dict)}
    if not (left_ids & set(config.owner_user_ids)):
        return  # 退会したのはオーナーではない
    if not _is_group_active(group_id):
        return  # もともと無効
    _deactivate_group(group_id)
    logger.info("group deactivated by owner leave: %s", group_id)
    reply_text(reply_token, MSG_OWNER_LEFT, config.channel_access_token)


def _is_group_active(group_id: Optional[str]) -> bool:
    """グループが起動済みか(activation_service への薄いラッパ)。

    遅延 import で bot.main を env 非依存に保つ。Storage 障害でも webhook を落とさない。
    """
    if not group_id:
        return False
    try:
        from services import activation_service

        return activation_service.is_group_active(group_id)
    except Exception as e:
        logger.error("activation lookup failed: %s", e, exc_info=True)
        return False  # 判定不能なら「無効」に倒す(勝手に使えてしまうより安全)


def _activate_group(group_id: str, user_id: Optional[str]) -> None:
    try:
        from services import activation_service

        activation_service.activate_group(group_id, user_id)
    except Exception as e:
        logger.error("activate failed: %s", e, exc_info=True)


def _deactivate_group(group_id: str) -> None:
    try:
        from services import activation_service

        activation_service.deactivate_group(group_id)
    except Exception as e:
        logger.error("deactivate failed: %s", e, exc_info=True)


def _is_owner(user_id: Optional[str], config: BotConfig) -> bool:
    """送信者がオーナー(OWNER_USER_IDS に含まれる)か。"""
    return bool(user_id) and user_id in config.owner_user_ids


def _is_activation_request(text: str) -> bool:
    """メンション除去後テキストが「起動」の合図を含むか。"""
    if not text:
        return False
    s = text.replace("　", " ")
    return any(m in s for m in _ACTIVATE_MARKERS)


def _event_type_values() -> tuple:
    """services 側が認める種別の値。services が読めない環境でも落とさない。"""
    try:
        from services import event_intake

        return tuple(event_intake.EVENT_TYPES)
    except Exception as e:
        logger.error("event type lookup failed: %s", e, exc_info=True)
        return ()


MSG_ASK_EVENT_TYPE = "イベントの種類はどちらですか?"

_EVENT_TYPE_BUTTONS = (
    ("girls", "ガールズイベント"),
    ("mens", "メンズイベント"),
)


def build_event_type_quickreply() -> dict:
    """新規作成の入口で出すイベント種別のクイックリプライ(C-1.1)。

    ボタンの文言は「ガールズイベント」等だが、これは記入テンプレの見出しを
    含まないので、埋めテンプレ判定(looks_like_filled_template)には掛からない。
    """
    items = [{
        "type": "action",
        "action": {
            "type": "postback",
            "label": label,
            "data": build_postback_data(ACTION_NEW_PROJECT, type=value),
            "displayText": label,
        },
    } for value, label in _EVENT_TYPE_BUTTONS]
    return {"type": "text", "text": MSG_ASK_EVENT_TYPE,
            "quickReply": {"items": items}}


def _reply_event_type_choices(reply_token: str, config: BotConfig) -> None:
    reply_messages(reply_token, [build_event_type_quickreply()],
                   config.channel_access_token)


def _is_intake_request(text: str) -> bool:
    """メンション除去後テキストが「新規作成」の合図を含むか(C-1)。"""
    if not text:
        return False
    s = text.replace("　", " ")
    return any(m in s for m in _INTAKE_MARKERS)


def _looks_like_filled_intake(text: str) -> bool:
    """埋めて返ってきた記入テンプレか(ステートレス判定・C-1)。

    pending を持たないので本文のセクション見出しだけで判定する。判定ロジックは
    services 側(3層規律)。services が読めない環境でも webhook は落とさない。
    """
    try:
        from services import event_intake

        return event_intake.looks_like_filled_template(text)
    except Exception as e:
        logger.error("intake shape check failed: %s", e, exc_info=True)
        return False


def _reply_intake_template(event_type: str, reply_token: str,
                           config: BotConfig) -> None:
    """選ばれた種別の記入テンプレを返信する(C-1.1 (A))。

    テンプレ先頭には【イベント種別】行が入っており、ユーザーが埋めて返信した
    本文にもそれが残るので、pending を持たずに種別を復元できる。
    """
    try:
        from services import event_intake

        template = event_intake.get_intake_template(event_type)
    except Exception as e:
        logger.error("intake template unavailable: %s", e, exc_info=True)
        reply_text(reply_token, MSG_INTAKE_FAILED, config.channel_access_token)
        return
    if not template:
        logger.error("no intake template for event_type=%r", event_type)
        reply_text(reply_token, MSG_INTAKE_FAILED, config.channel_access_token)
        return
    reply_text(reply_token, template, config.channel_access_token)


def _parse_intake_and_reply(text: str, reply_token: str, config: BotConfig) -> None:
    """記入テンプレを解析してエコー確認を返す。★別スレッドから呼ばれる想定。

    LLM 呼び出しは数秒かかるので callback を待たせない(reply token は約 1 分有効)。
    例外は握って必ず何かを返す(無反応が一番困るため)。
    ★C-1 は DB に一切書き込まない。作成は C-2。
    """
    try:
        from services import event_intake

        parsed = event_intake.parse_event_template(text)
        if not parsed.get("ok"):
            reason = parsed.get("reason")
            if reason == event_intake.REASON_NO_API_KEY:
                reply_text(reply_token, MSG_INTAKE_NO_API_KEY, config.channel_access_token)
            else:
                logger.warning("intake parse failed: reason=%s", reason)
                reply_text(reply_token, MSG_INTAKE_FAILED, config.channel_access_token)
            return

        ok, missing = event_intake.validate_intake(parsed)
        if not ok:
            reply_text(
                reply_token,
                build_intake_missing_message(missing),
                config.channel_access_token,
            )
            return

        reply_text(
            reply_token,
            event_intake.format_intake_echo(parsed),
            config.channel_access_token,
        )
    except Exception as e:
        logger.error("intake parse crashed: %s", e, exc_info=True)
        try:
            reply_text(reply_token, MSG_INTAKE_FAILED, config.channel_access_token)
        except Exception:
            logger.error("intake failure reply also failed", exc_info=True)


def _spawn_intake_parse(text: str, reply_token: str,
                        config: BotConfig) -> threading.Thread:
    """テンプレ解析を daemon thread に逃がして即座に戻る(callback は 200 をすぐ返す)。"""
    t = threading.Thread(
        target=_parse_intake_and_reply,
        args=(text, reply_token, config),
        daemon=True,
        name="intake-parse",
    )
    t.start()
    return t


def _detect_flow(text: str) -> Optional[str]:
    """メンション除去後テキストから flow を判定する。合図が無ければ None。

    ★B-3.1: アーティスト名はここでは読まない(完全ボタン対話)。
      差し替え(REPLACE)を先に判定する。「アー写更新」は差し替え側の合図。
    """
    if not text:
        return None
    s = text.replace("　", " ")
    if any(m in s for m in _REPLACE_MARKERS):
        return FLOW_REPLACE
    if any(m in s for m in _GET_MARKERS):
        return FLOW_GET
    return None


def _reply_event_page(reply_token: str, flow: str, page: int, config: BotConfig) -> None:
    """イベント選択ボタンの page ページ目を返す。0 件ならその旨。"""
    from services import event_service  # 遅延 import(bot.main を env 非依存に保つ)

    try:
        events, has_more = event_service.list_recent_events(page=page)
    except Exception as e:
        logger.error("event listing failed: %s", e, exc_info=True)
        events, has_more = [], False

    if not events:
        reply_text(reply_token, "対象のイベントが見つかりませんでした。",
                   config.channel_access_token)
        return
    reply_messages(
        reply_token,
        [build_event_quickreply(events, flow, page=page, has_more=has_more)],
        config.channel_access_token,
    )


def _reply_artist_page(reply_token: str, project_id: int, page: int,
                       config: BotConfig) -> None:
    """アーティスト選択ボタンの page ページ目を返す。0 件ならその旨。"""
    from services import event_service  # 遅延 import

    try:
        artists, has_more = event_service.list_event_artists(project_id, page=page)
    except Exception as e:
        logger.error("artist listing failed: pid=%s: %s", project_id, e, exc_info=True)
        artists, has_more = [], False

    if not artists:
        reply_text(reply_token, "このイベントには出演アーティストが登録されていません。",
                   config.channel_access_token)
        return
    reply_messages(
        reply_token,
        [build_artist_quickreply(project_id, artists, page=page, has_more=has_more)],
        config.channel_access_token,
    )


def _handle_postback(parsed: dict, reply_token: str, user_id: Optional[str],
                     config: BotConfig) -> None:
    """postback の 4 種別を捌く(B-3.1)。"""
    action = parsed.get("action")

    if action == ACTION_EVENT:
        if parsed.get("flow") == FLOW_GET:
            # 写真は変えず 2 枚だけ生成 → 別スレッド(callback は 200 を即返す)
            _spawn_regeneration(parsed["pid"], reply_token, config)
        else:
            _reply_artist_page(reply_token, parsed["pid"], page=0, config=config)
        return

    if action == ACTION_NEW_PROJECT:
        _reply_intake_template(parsed["type"], reply_token, config)
        return

    if action == ACTION_MORE_EVENT:
        _reply_event_page(reply_token, parsed["flow"], page=parsed["page"], config=config)
        return

    if action == ACTION_MORE_ARTIST:
        _reply_artist_page(reply_token, parsed["pid"], page=parsed["page"], config=config)
        return

    if action == ACTION_ARTIST:
        if not user_id:
            return  # pending は userId 単位。取れないなら写真待ちに入れない
        artist = parsed["artist"]
        pending_store.put(user_id, parsed["pid"], artist, time.time())
        reply_text(
            reply_token,
            "「%s」の新しい画像を送ってください(5分以内)。" % artist,
            config.channel_access_token,
        )
        return


def _update_photo_and_reply(project_id: int, artist: str, message_id: str,
                            reply_token: str, config: BotConfig) -> None:
    """画像 DL → アー写更新 → 2 枚生成 を 1 回の reply にまとめて返す。

    ★別スレッドから呼ばれる想定。DB 書き込みは既存 B4 の update_artist_photo だけ。
    例外は握って必ず何かを返す(無反応が一番困るため)。
    """
    try:
        image_bytes, content_type = download_image(message_id, config.channel_access_token)
    except Exception as e:
        logger.warning("image download failed: %s", e)
        reply_text(reply_token, "画像の取得に失敗しました。", config.channel_access_token)
        return

    try:
        ok, reply = update_artist_photo(artist, image_bytes, content_type)
    except Exception as e:
        logger.error("update_artist_photo failed: %s", e, exc_info=True)
        ok, reply = False, "「%s」の更新に失敗しました" % artist

    if not ok:
        reply_text(reply_token, reply, config.channel_access_token)
        return

    # 更新できたら、そのまま選択済みイベントの 2 枚を作って同じ reply にまとめる。
    try:
        images, failures = render_flyer_set_for_project(project_id)
    except Exception as e:
        logger.error("regenerate after update failed: pid=%s: %s", project_id, e, exc_info=True)
        images, failures = [], []

    messages: List[dict] = [{"type": "text", "text": reply}]
    if images:
        messages.extend(images)
        notice = build_failure_notice(failures)
        if notice:
            messages.append({"type": "text", "text": notice})
    else:
        messages.append({
            "type": "text",
            "text": "画像の再生成に失敗しました(アー写の更新は完了しています)。",
        })
    reply_messages(reply_token, messages, config.channel_access_token)


def _spawn_photo_update(project_id: int, artist: str, message_id: str,
                        reply_token: str, config: BotConfig) -> threading.Thread:
    """写真更新 + 再生成を daemon thread に逃がして即座に戻る。"""
    t = threading.Thread(
        target=_update_photo_and_reply,
        args=(project_id, artist, message_id, reply_token, config),
        daemon=True,
        name="photo-update-%s" % project_id,
    )
    t.start()
    return t


def _regenerate_and_reply(project_id: int, reply_token: str,
                          config: BotConfig) -> None:
    """フライヤー 2 枚を生成して reply する。★別スレッドから呼ばれる想定。

    生成は数十秒かかりうるので callback を待たせない。reply token は約 1 分有効なので
    その範囲で返す。例外は握って必ず何かを返す(無反応が一番困るため)。
    """
    try:
        messages, failures = render_flyer_set_for_project(project_id)
    except Exception as e:
        logger.error("regenerate failed: pid=%s: %s", project_id, e, exc_info=True)
        reply_text(reply_token, "画像の生成に失敗しました。", config.channel_access_token)
        return

    if not messages:
        reply_text(
            reply_token,
            "このイベントの画像を生成できませんでした(出演者やタイムテーブルの設定をご確認ください)。",
            config.channel_access_token,
        )
        return

    notice = build_failure_notice(failures)
    if notice:
        messages = messages + [{"type": "text", "text": notice}]
    reply_messages(reply_token, messages, config.channel_access_token)


def _spawn_regeneration(project_id: int, reply_token: str,
                        config: BotConfig) -> threading.Thread:
    """再生成を daemon thread に逃がして即座に戻る(callback は 200 をすぐ返す)。"""
    t = threading.Thread(
        target=_regenerate_and_reply,
        args=(project_id, reply_token, config),
        daemon=True,
        name="flyer-regen-%s" % project_id,
    )
    t.start()
    return t


def handle_event(event: dict, config: BotConfig) -> None:
    """1 イベントを処理する。ガード非通過は静かに無視(reply しない)。"""
    event_type = event.get("type")
    if event_type not in ("message", "postback", "memberLeft", "leave", "join"):
        return
    source = event.get("source") or {}
    message = event.get("message") or {}
    reply_token = event.get("replyToken", "")

    group_id = _source_group_id(source)
    user_id = source.get("userId")

    # 共通ガード: グループ発 + 許可グループであること。DM は完全無視。
    # ★段階B B-3(合意済み): 送信者が OWNER かどうかのゲートは撤去した。
    #   許可グループの中なら誰でも使える。代わりに【テキストのトリガーは
    #   自ボット宛メンション必須】(is_self_mentioned)を維持して誤爆を防ぐ。
    #   config.owner_user_ids は互換のため残すが、ゲートには使わない。
    if not _passes_group_guard(group_id, config):
        return

    # --- B-4: メンバー/ボット自身の出入り ---
    if event_type == "memberLeft":
        _handle_member_left(event, group_id, reply_token, config)
        return
    if event_type == "leave":
        # Bot 自身が退出 / kick された。もう発言できないので静かに掃除するだけ。
        logger.info("bot left group: %s", group_id)
        _deactivate_group(group_id)
        return
    if event_type == "join":
        # Bot が追加された。★デフォルト無効なので何もしない(オーナーの「起動」待ち)。
        logger.info("bot joined group: %s (inactive until owner activates)", group_id)
        return

    # --- postback(ボタン)---
    # ボタンはメンション起動フローの続きなので、ここではメンションを要求しない
    # (グループ許可リストのガードは上で通過済み)。
    if event_type == "postback":
        # B-4: ボタンは有効グループにしか出さないが、念のため再チェックする
        # (古いボタンを無効化後に押された場合など)。
        if not _is_group_active(group_id):
            reply_text(reply_token, MSG_NOT_ACTIVATED, config.channel_access_token)
            return
        parsed = parse_postback_data(((event.get("postback") or {}).get("data")) or "")
        if not parsed:
            return  # 不正 data は静かに無視
        _handle_postback(parsed, reply_token, source.get("userId"), config)
        return

    msg_type = message.get("type")
    now = time.time()
    pending_store.purge_expired(now)

    if msg_type == "text":
        mentionees = ((message.get("mention") or {}).get("mentionees")) or []
        if not is_self_mentioned(mentionees):
            return  # 自ボット宛でないテキストは無視
        cleaned = strip_self_mentions(message.get("text", ""), mentionees)

        # --- B-4: 起動制御を最上流で捌く ---
        active = _is_group_active(group_id)
        if _is_activation_request(cleaned):
            if active:
                reply_text(reply_token, MSG_ALREADY_ACTIVE, config.channel_access_token)
            elif _is_owner(user_id, config):
                _activate_group(group_id, user_id)
                reply_text(reply_token, MSG_ACTIVATED, config.channel_access_token)
            else:
                reply_text(reply_token, MSG_ACTIVATE_DENIED, config.channel_access_token)
            return

        # 通常の依頼は有効グループのときだけ処理する
        if not active:
            reply_text(reply_token, MSG_NOT_ACTIVATED, config.channel_access_token)
            return

        # --- 段階C C-1: 記入テンプレのやりとり ---
        # ★「埋めたテンプレ」判定を先に置く。テンプレ本文が「新規作成」等の語を
        #   含んでいても、テンプレを配り直さずに解析へ進めるため(見出しの有無で
        #   判定するので、素の「新規作成」はここに掛からない)。
        if _looks_like_filled_intake(cleaned):
            _spawn_intake_parse(cleaned, reply_token, config)
            return
        if _is_intake_request(cleaned):
            # C-1.1: いきなりテンプレを出さず、まず種別を選ばせる
            # (種別で自由記述と料金の既定値が違うため)
            _reply_event_type_choices(reply_token, config)
            return

        # ★B-3.1: 名前はテキストから読まない。マーカーで flow を決めてボタンに渡す。
        flow = _detect_flow(cleaned)
        if flow is None:
            reply_text(reply_token, _USAGE_TEXT, config.channel_access_token)
            return
        _reply_event_page(reply_token, flow, page=0, config=config)
        return

    if msg_type == "image":
        if not _is_group_active(group_id):
            return  # 無効グループの画像は静かに無視(pending も持たないはず)
        pending = pending_store.pop_valid(user_id, now)
        if not pending:
            return  # 直近の pending が無い画像は無視
        project_id, artist = pending
        # ★download → 更新 → 2 枚生成 まで数十秒かかるのでバックグラウンドへ。
        #   callback は 200 を即返す(reply token は約 1 分有効)。
        _spawn_photo_update(
            project_id, artist, message.get("id"), reply_token, config
        )
        return

    # その他のメッセージ種別は無視


# ---------------------------------------------------------------------------
# FastAPI アプリ
# ---------------------------------------------------------------------------
app = FastAPI(title="BOTTZ AI LINE Bot")
app.include_router(api.router)  # /api/* read エンドポイント(API キー認証・§11.7 段階A0)


@app.get("/")
def health() -> dict:
    return {"status": "ok", "service": "bottz-ai-line-bot"}


@app.post("/callback")
async def callback(request: Request) -> Response:
    config = load_config()
    body = await request.body()
    signature = request.headers.get("X-Line-Signature")

    if not verify_signature(body, signature, config.channel_secret):
        return Response(status_code=400, content="invalid signature")

    try:
        payload = json.loads(body.decode("utf-8"))
    except Exception:
        return Response(status_code=400, content="invalid body")

    for event in payload.get("events", []):
        try:
            handle_event(event, config)
        except Exception as e:  # 1 イベントの失敗で 200 を返せなくしない
            logger.error("handle_event error: %s", e, exc_info=True)

    return Response(status_code=200, content="OK")
