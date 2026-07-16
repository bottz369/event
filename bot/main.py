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
_ARTWORK_MARKERS = ("アー写", "アーティスト写真")


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


def extract_artist_name(text: str) -> Optional[str]:
    """メンション除去後テキストから「○○のアー写更新 / ○○ アー写」の ○○ を取り出す。

    見つからなければ None。全角スペースは半角に正規化し、合図(アー写等)の手前を名前候補、
    末尾の助詞「の」を 1 つだけ除去する。
    """
    if not text:
        return None
    s = text.replace("　", " ").strip()
    marker_pos = -1
    for marker in _ARTWORK_MARKERS:
        i = s.find(marker)
        if i != -1:
            marker_pos = i if marker_pos == -1 else min(marker_pos, i)
    if marker_pos <= 0:  # 合図が無い / 先頭にある(名前が無い)
        return None
    name = s[:marker_pos].strip()
    if name.endswith("の"):
        name = name[:-1].strip()
    return name or None


# ---------------------------------------------------------------------------
# pending ストア(テキスト → 画像の順待ち・userId 単位・TTL 付き)
# ---------------------------------------------------------------------------
class PendingStore:
    """userId ごとに「更新対象アーティスト名 + 記録時刻」を TTL 付きで保持する。

    時刻(now)は呼び出し側から注入する(テスト決定性のため)。スレッド安全。
    """

    def __init__(self, ttl_seconds: int = PENDING_TTL_SECONDS):
        self._ttl = ttl_seconds
        self._data: Dict[str, Tuple[str, float]] = {}
        self._lock = threading.Lock()

    def put(self, user_id: str, name: str, now: float) -> None:
        with self._lock:
            self._data[user_id] = (name, now)

    def pop_valid(self, user_id: str, now: float) -> Optional[str]:
        """TTL 内の pending があれば名前を返して消費する。無効/期限切れは None。"""
        with self._lock:
            item = self._data.get(user_id)
            if item is None:
                return None
            name, created = item
            del self._data[user_id]
            if now - created > self._ttl:
                return None
            return name

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


def reply_text(reply_token: str, text: str, access_token: str, timeout: int = 15) -> None:
    """reply token でテキスト返信する(best-effort。失敗しても例外は投げず log のみ)。"""
    if not reply_token:
        return
    try:
        resp = requests.post(
            LINE_REPLY_ENDPOINT,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json={"replyToken": reply_token, "messages": [{"type": "text", "text": text}]},
            timeout=timeout,
        )
        if resp.status_code >= 300:
            logger.warning("reply failed: %s %s", resp.status_code, resp.text[:200])
    except Exception as e:  # 通知失敗で Webhook を落とさない
        logger.warning("reply request error: %s", e)


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
    """グループ発 & (許可リストが空なら全許可 / 非空なら含まれること)。"""
    if group_id is None:  # グループ以外(DM/ルーム)は不可
        return False
    if config.allowed_group_ids and group_id not in config.allowed_group_ids:
        return False
    return True


def handle_event(event: dict, config: BotConfig) -> None:
    """1 イベントを処理する。ガード非通過は静かに無視(reply しない)。"""
    if event.get("type") != "message":
        return
    source = event.get("source") or {}
    message = event.get("message") or {}
    reply_token = event.get("replyToken", "")

    group_id = _source_group_id(source)
    user_id = source.get("userId")

    # 共通ガード: グループ発 + 送信者が OWNER。DM は完全無視。
    if not _passes_group_guard(group_id, config):
        return
    if not user_id or user_id not in config.owner_user_ids:
        return

    msg_type = message.get("type")
    now = time.time()
    pending_store.purge_expired(now)

    if msg_type == "text":
        mentionees = ((message.get("mention") or {}).get("mentionees")) or []
        if not is_self_mentioned(mentionees):
            return  # 自ボット宛でないテキストは無視
        cleaned = strip_self_mentions(message.get("text", ""), mentionees)
        name = extract_artist_name(cleaned)
        if not name:
            reply_text(
                reply_token,
                "アー写更新は「<アーティスト名>のアー写更新」と送ってから画像を送ってください。",
                config.channel_access_token,
            )
            return
        pending_store.put(user_id, name, now)
        reply_text(
            reply_token,
            f"「{name}」のアー写を待っています。画像を送ってください(5分以内)。",
            config.channel_access_token,
        )
        return

    if msg_type == "image":
        name = pending_store.pop_valid(user_id, now)
        if not name:
            return  # 直近の pending が無い画像は無視
        try:
            image_bytes, content_type = download_image(
                message.get("id"), config.channel_access_token
            )
        except Exception as e:
            logger.warning("image download failed: %s", e)
            reply_text(reply_token, "画像の取得に失敗しました。", config.channel_access_token)
            return
        try:
            _ok, reply = update_artist_photo(name, image_bytes, content_type)
        except Exception as e:
            logger.error("update_artist_photo failed: %s", e, exc_info=True)
            reply = f"「{name}」の更新に失敗しました"
        reply_text(reply_token, reply, config.channel_access_token)
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
