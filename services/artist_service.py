"""
アーティスト関連のビジネスロジック。

view 層からはこの service を呼び、直接 repository / DB は触らない。
session の生成/クローズと commit/rollback は service が所有する
(project_service と同じ流儀)。repository は「書くだけ・commit しない」ので、
トランザクション境界(commit/rollback)はすべてここで握る。

キャッシュ(@st.cache_data 等)は入れない(罠17: 導入するなら
create/update/delete/merge 全経路の invalidation とセット設計が必要。
その判断は Phase 6)。
"""
from __future__ import annotations

import os
import time
import uuid
from typing import List, Optional, Tuple

from database import SessionLocal, upload_image_to_supabase
from models.artist import ArtistView
from repositories import artist_repo, project_repo
from utils.logger import get_logger

logger = get_logger(__name__)


def _upload_image(image_file) -> Optional[str]:
    """アップロードファイルがあれば uuid ファイル名で Supabase に上げ、その名前を返す。
    無ければ None。既存 views/artists.py L98-101 / L154-156 と等価。
    """
    if image_file is None:
        return None
    ext = os.path.splitext(image_file.name)[1].lower()
    fname = f"{uuid.uuid4()}{ext}"
    upload_image_to_supabase(image_file, fname)
    return fname


# ---------------------------------------------------------
# 読み取り
# ---------------------------------------------------------
def list_artists(include_deleted: bool = False) -> List[ArtistView]:
    """アーティスト一覧(既定 is_deleted==False)を ArtistView で返す。"""
    db = SessionLocal()
    try:
        return artist_repo.list_artists(db, include_deleted=include_deleted)
    finally:
        db.close()


def get_artists_by_names(names) -> List[ArtistView]:
    """名前リストに対応する ArtistView を入力順・重複保持で返す。"""
    db = SessionLocal()
    try:
        return artist_repo.get_artists_by_names(db, names)
    finally:
        db.close()


# アー写グリッド用: 未登録の名前を表すスタンドインの識別子は負の連番にする。
# ★_fetch_grid_images_parallel が a.id で dedupe するため、未登録が複数あっても
#   1 件に潰れないよう一意である必要がある(全部 None にすると潰れる)。
FAILURE_KIND_ARTIST_NOT_REGISTERED = "artist_not_registered"


def _standin(neg_id: int, name: str) -> ArtistView:
    """artists に無い名前を「アー写の無いアーティスト」として表す一時オブジェクト。

    ★DB には保存しない。描画のためだけに作る。
      image_filename=None なので logic_grid は C-6a の黒プレースホルダを描く。
    ArtistView をそのまま使うのは、下流(_fetch_grid_images_parallel /
    generate_grid_image)が参照する属性が id / name / image_filename / crop_* だけで、
    ArtistView がちょうどその形だから(専用型を増やす必要が無い)。
    """
    return ArtistView(
        id=neg_id,
        name=name,
        image_filename=None,
        is_deleted=False,
        crop_scale=1.0,
        crop_x=0,
        crop_y=0,
    )


def resolve_artists_in_order(names, failures=None) -> List[ArtistView]:
    """名前リストを、1 件も落とさずに ArtistView のリストへ解決する。

    get_artists_by_names は「artists に無い名前を skip する」既存仕様なので、
    そのまま grid に渡すと未登録の出演者の枠ごと消える(#4)。マージで改名された
    旧表記(例「Luna moon」→「LunaMoon」)を書いた場合などに起きる。
    ここでは未登録の名前にもスタンドインを立て、**枠を残して黒プレースホルダで
    可視化する**(C-6a と合流)。

    failures に list を渡すと、未登録だった名前を §5 の形式で積む:
        {"kind": "artist_not_registered", "name": "<name>"}

    ★get_artists_by_names 自体の挙動は変えない(アー写更新など「実体が必要」な
      呼び出し側がそちらを使い続けるため)。差し込みはこの service 層だけで行う。
    """
    names = list(names or [])
    if not names:
        return []

    resolved = get_artists_by_names(names)
    by_name = {a.name: a for a in resolved}

    out: List[ArtistView] = []
    neg = 0
    for n in names:
        found = by_name.get(n)
        if found is not None:
            out.append(found)
            continue
        neg -= 1
        out.append(_standin(neg, n))
        if failures is not None:
            failures.append({"kind": FAILURE_KIND_ARTIST_NOT_REGISTERED, "name": n})
    if neg:
        logger.info("resolve_artists_in_order: %d unregistered name(s) kept as placeholders",
                    -neg)
    return out


# ---------------------------------------------------------
# 書き込み(commit/rollback は service が握る)
# ---------------------------------------------------------
def create_artist(name: str, image_file=None) -> Tuple[Optional[ArtistView], str]:
    """新規登録(create-or-restore)。

    既存 views/artists.py L88-102 の分岐を bit 一致で踏襲する:
      - 既存なし              → 新規作成       status="created"
      - 既存 & is_deleted     → 復元           status="restored"
      - 既存 & 生存中          → 何もしない      status="exists"
    ※ 画像アップロードは exists 判定より前に行う(既存挙動どおり。exists の場合は
       アップロード済み画像が孤児になるが、これも既存と同一)。
    ※ 名前の正規化(大文字小文字/前後空白)は行わない(既存挙動維持)。

    戻り値: (ArtistView or None, status)。status ∈ {"created","restored","exists","error"}。
    """
    if not name:
        return (None, "error")
    db = SessionLocal()
    try:
        image_filename = _upload_image(image_file)
        existing = artist_repo.get_artist_by_name(db, name)
        if existing is None:
            view = artist_repo.create_artist(db, name, image_filename)
            db.commit()
            return (view, "created")
        if existing.is_deleted:
            view = artist_repo.restore_artist(db, existing.id, image_filename)
            db.commit()
            return (view, "restored")
        # 既存 & 生存中: 登録済み。書き込みは行わない。
        db.rollback()
        return (existing, "exists")
    except Exception as e:
        db.rollback()
        logger.error(f"create_artist failed: {e}", exc_info=True)
        return (None, "error")
    finally:
        db.close()


def update_artist(artist_id: int, name: str, image_file=None) -> Optional[ArtistView]:
    """基本情報(名前/画像)を更新する。既存 views/artists.py L150-158 相当。

    name は常に更新(呼び出し側で new_name の空チェックを行う前提。既存 L151)。
    image_file が渡されたときのみ画像を差し替える。対象が無ければ None。
    """
    db = SessionLocal()
    try:
        image_filename = _upload_image(image_file)
        view = artist_repo.update_artist(db, artist_id, name, image_filename)
        if view is None:
            db.rollback()
            return None
        db.commit()
        return view
    except Exception as e:
        db.rollback()
        logger.error(f"update_artist failed: {e}", exc_info=True)
        return None
    finally:
        db.close()


def update_artist_crop(artist_id: int, scale: float, x: int, y: int) -> Optional[ArtistView]:
    """画像位置調整(crop_scale/crop_x/crop_y)を更新する。既存 L187-191 相当。
    対象が無ければ None。
    """
    db = SessionLocal()
    try:
        view = artist_repo.update_artist_crop(db, artist_id, scale, x, y)
        if view is None:
            db.rollback()
            return None
        db.commit()
        return view
    except Exception as e:
        db.rollback()
        logger.error(f"update_artist_crop failed: {e}", exc_info=True)
        return None
    finally:
        db.close()


def soft_delete_artist(artist_id: int) -> bool:
    """論理削除。既存 views/artists.py L200-201 と bit 一致:
    name を `{name}_del_{int(time.time())}` に改名 + is_deleted=True。
    (改名は削除済みの名前を空けて、同名の新規登録が復元でなく新規作成になるようにする
     既存挙動。repo を単機能に保つため update_artist(改名) + soft_delete_artist を合成。)

    対象が無ければ False、成功したら True。物理削除はしない。
    """
    db = SessionLocal()
    try:
        current = artist_repo.get_artist(db, artist_id)
        if current is None:
            return False
        del_name = f"{current.name}_del_{int(time.time())}"
        artist_repo.update_artist(db, artist_id, del_name)  # 改名(image は None なので不変)
        artist_repo.soft_delete_artist(db, artist_id)        # is_deleted=True
        db.commit()
        return True
    except Exception as e:
        db.rollback()
        logger.error(f"soft_delete_artist failed: {e}", exc_info=True)
        return False
    finally:
        db.close()


def merge_artists(winner_id: int, loser_id: int) -> Tuple[int, int, str]:
    """アーティスト統合(名寄せ)。1 トランザクションで以下を合成する:

      1. winner / loser を取得。どちらか無ければ (0, 0, "not_found")
      2. rows_count = TimetableRow.artist_name を loser 現名 → winner 現名 に付け替え
         ※ rename 前の loser 名で付け替える(順序厳守)
      3. grid_count = 全プロジェクトの grid_order_json 内 order の loser 名を winner 名へ名寄せ
         (⑤-b で追加。TimetableRow と同じく rename 前の loser 名で。順序: TT → grid → rename)
      4. loser を `{loser名}_merged_{int(time.time())}` にリネーム
         (image_filename は None 渡しで不変)
      5. loser を is_deleted=True(論理削除)
      6. commit → (rows_count, grid_count, "merged")。例外時 rollback → (0, 0, "error")(詳細は log)

    ※ _merged_ リネームは delete の _del_ とは別物のため、service.soft_delete_artist
      (改名 _del_ 込み)は使わず、repo 単機能(reassign / update_artist / soft_delete_artist)
      を組み合わせて merge 専用の合成を作る。
    ※ 対応済みの名前保持箇所: timetable_rows.artist_name(⑤-a)/ grid_order_json.order(⑤-b)。
      未対応(既知の制限): 旧 data_json の ARTIST(書き手ゼロ不変条件を守るため触らない。
      未移行プロジェクトは一度保存すれば timetable_rows に移行し解消)/ loser の Storage 画像
      (孤児化は現行仕様。削除は破壊的操作のため非対応)。詳細は開発知見ドキュメント §19 罠26。

    戻り値: (rows_count, grid_count, status)。status ∈ {"merged", "not_found", "error"}。
    """
    db = SessionLocal()
    try:
        winner = artist_repo.get_artist(db, winner_id)
        loser = artist_repo.get_artist(db, loser_id)
        if winner is None or loser is None:
            db.rollback()
            return (0, 0, "not_found")
        # 1. TimetableRow の付け替え(rename 前の loser 名で。順序厳守)
        rows_count = artist_repo.reassign_timetable_rows(db, loser.name, winner.name)
        # 2. grid_order_json の名寄せ(同一トランザクション・rename 前の loser 名で)
        grid_count = project_repo.reassign_grid_orders(db, loser.name, winner.name)
        # 3. loser をリネーム(衝突回避。image は None 渡しで不変)
        merged_name = f"{loser.name}_merged_{int(time.time())}"
        artist_repo.update_artist(db, loser_id, merged_name)
        # 4. loser を論理削除
        artist_repo.soft_delete_artist(db, loser_id)
        db.commit()
        return (rows_count, grid_count, "merged")
    except Exception as e:
        db.rollback()
        logger.error(f"merge_artists failed: {e}", exc_info=True)
        return (0, 0, "error")
    finally:
        db.close()
