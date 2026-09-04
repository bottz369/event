"""グループ起動制御(段階B B-4)。

「誰でも Bot をグループに追加できるが、デフォルトは無効。オーナーが『起動』と送った
グループだけが使える」という動的な有効化を管理する。

★永続化は Supabase Storage の JSON 1 ファイル(DB スキーマは変更しない)。
  Railway の再デプロイ / 再起動でも有効化状態が残るようにするため。

  形: {"groups": {"<groupId>": {"activated_by": "<userId>", "activated_at": <epoch>}}}

★Storage を SSOT に、プロセス内メモリはライトスルー・キャッシュ:
  - 初回アクセス時に Storage から読み、以後はメモリを参照(webhook ごとの Storage 読みはしない)
  - activate / deactivate はメモリ更新 + Storage 書き込み(ライトスルー)
  - webhook とバックグラウンド thread の両方から触るので Lock で保護する
  - Storage 読み失敗(ファイル未作成を含む)は **空集合として起動**しログのみ
    (起動できないより「まだ誰も起動していない」状態で動く方が安全)
  - 書き込み失敗もログのみ。メモリは更新済みなので、そのプロセスが生きている間は有効

★ 画面非依存: streamlit を import しない(罠39 / §42)。
★ DB には一切書かない(Storage の JSON のみ)。
"""
from __future__ import annotations

import io
import json
import threading
import time
from typing import Dict, Optional

from utils.logger import get_logger

logger = get_logger(__name__)

# Storage 上の固定キー(1 ファイルで全グループを保持する)
STORAGE_KEY = "bot/activated_groups.json"

_lock = threading.Lock()
# None = 未ロード。{} = ロード済みで空。
_cache: Optional[Dict[str, dict]] = None


def _bucket():
    """Storage バケットのプロキシ。遅延 import(bot.main を env 非依存に保つ)。

    テストではこの関数を monkeypatch して実 Storage に触らせない。
    """
    from database import BUCKET_NAME, supabase

    return supabase.storage.from_(BUCKET_NAME)


def _load_from_storage() -> Dict[str, dict]:
    """Storage から読む。未作成 / 壊れ / 失敗はすべて空 dict(安全側)。"""
    try:
        raw = _bucket().download(STORAGE_KEY)
    except Exception as e:
        # ファイル未作成の初回もここに来る(まだ誰も起動していない状態)
        logger.warning(
            "activation store not loaded (treating as empty): %s: %s", type(e).__name__, e
        )
        return {}
    try:
        data = json.loads(bytes(raw).decode("utf-8"))
        groups = data.get("groups") if isinstance(data, dict) else None
        if not isinstance(groups, dict):
            logger.warning("activation store has unexpected shape; treating as empty")
            return {}
        return {str(k): (v if isinstance(v, dict) else {}) for k, v in groups.items()}
    except Exception as e:
        logger.warning("activation store parse failed (treating as empty): %s", e)
        return {}


def _save_to_storage(groups: Dict[str, dict]) -> bool:
    """Storage へ書き戻す(upsert)。失敗は False + ログ(例外は投げない)。"""
    payload = json.dumps({"groups": groups}, ensure_ascii=False).encode("utf-8")
    try:
        _bucket().upload(
            path=STORAGE_KEY,
            file=payload,
            file_options={"content-type": "application/json", "upsert": "true"},
        )
        return True
    except Exception as e:
        logger.error(
            "activation store save failed (memory is updated, lost on restart): %s: %s",
            type(e).__name__, e,
        )
        return False


def _ensure_loaded_locked() -> Dict[str, dict]:
    """_lock を保持した状態で呼ぶこと。未ロードなら Storage から読む。"""
    global _cache
    if _cache is None:
        _cache = _load_from_storage()
        logger.info("activation store loaded: %d group(s)", len(_cache))
    return _cache


def reload_from_storage() -> None:
    """キャッシュを捨てて次回アクセス時に読み直す(テスト / 運用の手動同期用)。"""
    global _cache
    with _lock:
        _cache = None


def is_group_active(group_id: Optional[str]) -> bool:
    """そのグループが起動済みか。group_id が無ければ常に False。"""
    if not group_id:
        return False
    with _lock:
        return group_id in _ensure_loaded_locked()


def activate_group(group_id: str, user_id: Optional[str]) -> None:
    """グループを有効化する(メモリ更新 + Storage 書き込みのライトスルー)。"""
    if not group_id:
        return
    with _lock:
        groups = _ensure_loaded_locked()
        groups[group_id] = {
            "activated_by": user_id or "",
            "activated_at": int(time.time()),
        }
        _save_to_storage(groups)
    logger.info("group activated: %s by %s", group_id, user_id)


def deactivate_group(group_id: str) -> None:
    """グループを無効化する。存在しなければ何もしない(書き込みもしない)。"""
    if not group_id:
        return
    with _lock:
        groups = _ensure_loaded_locked()
        if group_id not in groups:
            return
        del groups[group_id]
        _save_to_storage(groups)
    logger.info("group deactivated: %s", group_id)
