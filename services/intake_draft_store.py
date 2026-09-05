"""記入テンプレ解析結果の下書き保持(段階C C-2a・§52)。

エコー確認 → 作成ボタン の間、解析結果をどこかに置いておく必要がある。
postback data は 300 bytes しか無く解析結果は載らないので、Storage に JSON で
置いて **draft_id だけを postback に載せる**。

★永続化は Supabase Storage の JSON(DB スキーマは変更しない)。activation_service と
  同じ仕組みだが、ファイルの持ち方だけ変えてある:

    activation_service … 全グループを 1 ファイル + メモリキャッシュ
    ここ              … 下書き 1 件 = 1 ファイル(bot/intake_drafts/<id>.json)

  1 ファイルにまとめると、別々のリクエスト(別プロセスでもよい)が同時に
  read-modify-write して互いを消しうる。下書きは「書いた人が後で 1 回読む」だけ
  なので、1 件 1 ファイルにすれば読み書きが衝突しない。キャッシュも要らないので
  再デプロイを跨いでも確実に読める。

★TTL は読み出し時に判定する(期限切れは無いものとして扱い、掃除も試みる)。
  Storage の一覧 API を叩いて回る定期 GC は持たない。

★ streamlit を import しない(罠39)。DB にも一切書かない(Storage の JSON のみ)。
★ 例外を外へ投げない。Storage 障害は「下書きが無い」に倒して webhook を落とさない。
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Optional

from utils.logger import get_logger

logger = get_logger(__name__)

# Storage 上の置き場所(1 件 1 ファイル)
STORAGE_PREFIX = "bot/intake_drafts"

# 下書きの寿命。エコーを見てから作成ボタンを押すまでの猶予。
DRAFT_TTL_SECONDS = 24 * 60 * 60


def _bucket():
    """Storage バケットのプロキシ。遅延 import(bot.main を env 非依存に保つ)。

    テストではこの関数を monkeypatch して実 Storage に触らせない。
    """
    from database import BUCKET_NAME, supabase

    return supabase.storage.from_(BUCKET_NAME)


def _key(draft_id: str) -> str:
    return "%s/%s.json" % (STORAGE_PREFIX, draft_id)


def _is_valid_id(draft_id) -> bool:
    """postback から来た id を Storage パスに使う前に検証する。

    32 桁の hex だけを許し、'..' や '/' が混ざったパス細工を弾く。
    """
    if not draft_id or not isinstance(draft_id, str):
        return False
    if len(draft_id) != 32:
        return False
    return all(c in "0123456789abcdef" for c in draft_id)


def save_draft(data: dict) -> Optional[str]:
    """解析結果を保存して draft_id を返す。失敗は None(例外は投げない)。"""
    draft_id = uuid.uuid4().hex
    payload = json.dumps(
        {"saved_at": time.time(), "data": data}, ensure_ascii=False
    ).encode("utf-8")
    try:
        _bucket().upload(
            path=_key(draft_id),
            file=payload,
            file_options={"content-type": "application/json", "upsert": "true"},
        )
    except Exception as e:
        logger.error("intake draft save failed: %s: %s", type(e).__name__, e,
                     exc_info=True)
        return None
    logger.info("intake draft saved: id=%s", draft_id)
    return draft_id


def load_draft(draft_id: str) -> Optional[dict]:
    """draft_id の解析結果を返す。無い / 壊れ / 期限切れ / 失敗はすべて None。

    期限切れを見つけたら削除も試みる(取り置きを溜めないため)。
    """
    if not _is_valid_id(draft_id):
        logger.warning("intake draft id is malformed: %r", draft_id)
        return None
    try:
        raw = _bucket().download(_key(draft_id))
    except Exception as e:
        # 期限切れで消したあと / 存在しない id もここに来る
        logger.warning("intake draft not loaded: id=%s %s: %s",
                       draft_id, type(e).__name__, e)
        return None
    try:
        doc = json.loads(bytes(raw).decode("utf-8"))
    except Exception as e:
        logger.warning("intake draft parse failed: id=%s: %s", draft_id, e)
        return None
    if not isinstance(doc, dict):
        return None

    saved_at = doc.get("saved_at")
    try:
        age = time.time() - float(saved_at)
    except (TypeError, ValueError):
        logger.warning("intake draft has no usable saved_at: id=%s", draft_id)
        return None
    if age > DRAFT_TTL_SECONDS:
        logger.info("intake draft expired: id=%s age=%.0fs", draft_id, age)
        delete_draft(draft_id)
        return None

    data = doc.get("data")
    return data if isinstance(data, dict) else None


def delete_draft(draft_id: str) -> bool:
    """下書きを消す。無くても失敗しても False + ログ(例外は投げない)。

    ★消すのは Storage 上の下書きだけ。プロジェクトや DB には触らない。
    """
    if not _is_valid_id(draft_id):
        return False
    try:
        _bucket().remove([_key(draft_id)])
    except Exception as e:
        logger.warning("intake draft delete failed: id=%s %s: %s",
                       draft_id, type(e).__name__, e)
        return False
    logger.info("intake draft deleted: id=%s", draft_id)
    return True
