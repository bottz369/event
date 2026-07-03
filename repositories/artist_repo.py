"""
Artist の CRUD を担うリポジトリ。

流儀は timetable_repo / project_repo に合わせる:
- モジュールレベル関数。db: Session を第 1 引数で受ける。
- repository はセッションを作らない/閉じない(呼び出し側 service が所有)。
- repository は db.commit() を【しない】。commit 境界は service が握る
  (Phase 4 以降の「repo は書くだけ・commit は service」方針)。
- 読み取りは ArtistView(frozen dataclass)で返し、ORM を view に渡さない
  (DetachedInstanceError 回避)。
- 物理削除はしない(is_deleted による論理削除のみ)。
"""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy.orm import Session

from database import Artist
from models.artist import ArtistView
from utils.logger import get_logger

logger = get_logger(__name__)


def _to_view(artist: Artist) -> ArtistView:
    """ORM(Artist)を読み取り用 ArtistView に写し替える。

    crop_* は既存 view (L136-138) の防御的読み取り
    `getattr(a, 'crop_scale', 1.0) or 1.0` と等価な None フォールバックを行う。
    """
    return ArtistView(
        id=artist.id,
        name=artist.name or "",
        image_filename=artist.image_filename,
        is_deleted=bool(artist.is_deleted),
        crop_scale=(artist.crop_scale or 1.0),
        crop_x=(artist.crop_x or 0),
        crop_y=(artist.crop_y or 0),
    )


# ---------------------------------------------------------
# 読み取り系
# ---------------------------------------------------------
def list_artists(db: Session, include_deleted: bool = False) -> List[ArtistView]:
    """アーティスト一覧を名前昇順で返す。

    既定では is_deleted == False のみ(既存 views/artists.py L113 の挙動を厳守。
    うっかり全件返して論理削除済みを復活表示させる事故を防ぐ)。
    include_deleted=True のときのみ削除済みも含めて全件返す。その場合でも
    各要素は ArtistView.is_deleted で生死を判別できる(create-or-restore 判定用)。
    """
    query = db.query(Artist)
    if not include_deleted:
        query = query.filter(Artist.is_deleted == False)  # noqa: E712 (SQLAlchemy 比較)
    artists = query.order_by(Artist.name).all()
    return [_to_view(a) for a in artists]


def get_artist(db: Session, artist_id: int) -> Optional[ArtistView]:
    """ID 指定で 1 件取得。無ければ None。"""
    if artist_id is None:
        return None
    artist = db.query(Artist).filter(Artist.id == artist_id).first()
    return _to_view(artist) if artist else None


def get_artist_by_name(db: Session, name: str) -> Optional[ArtistView]:
    """名前の完全一致で 1 件取得(重複/復元判定用)。無ければ None。

    正規化(大文字小文字/前後空白)は既存 create の同名チェック
    (views/artists.py L95 `filter(Artist.name == n)`)と同じく行わない
    = 完全一致。既存挙動を変えないため。
    """
    artist = db.query(Artist).filter(Artist.name == name).first()
    return _to_view(artist) if artist else None


# ---------------------------------------------------------
# 書き込み系(commit は呼び出し側 service が行う)
# ---------------------------------------------------------
def create_artist(db: Session, name: str, image_filename: Optional[str]) -> ArtistView:
    """新規アーティストを追加する(commit はしない)。

    id を確定させるため db.flush() までは行う。作成結果を ArtistView で返す。
    """
    artist = Artist(name=name, image_filename=image_filename)
    db.add(artist)
    db.flush()  # id 採番のため。commit は service。
    logger.info(f"create_artist: added name={name!r} id={artist.id}")
    return _to_view(artist)


def restore_artist(db: Session, artist_id: int, image_filename: Optional[str]) -> Optional[ArtistView]:
    """論理削除済みアーティストを復元する(commit はしない)。

    既存の create-or-restore ロジック(views/artists.py L96-97)の復元側に相当:
    is_deleted を False に戻し、image_filename を差し替える。
    引数は artist_id に統一(repo が ORM 取得を握り、service は id/View で扱う)。
    対象が無ければ None。
    """
    artist = db.query(Artist).filter(Artist.id == artist_id).first()
    if artist is None:
        return None
    artist.is_deleted = False
    artist.image_filename = image_filename
    logger.info(f"restore_artist: restored id={artist_id}")
    return _to_view(artist)


def update_artist(
    db: Session,
    artist_id: int,
    name: str,
    image_filename: Optional[str] = None,
) -> Optional[ArtistView]:
    """基本情報(名前/画像)を更新する(commit はしない)。

    name は常に更新。image_filename は None 以外が渡されたときのみ差し替える
    (既存 views/artists.py L152-157: 名前は常に更新、画像は新規アップロード時のみ、
     と等価)。対象が無ければ None。
    """
    artist = db.query(Artist).filter(Artist.id == artist_id).first()
    if artist is None:
        return None
    artist.name = name
    if image_filename is not None:
        artist.image_filename = image_filename
    logger.info(
        f"update_artist: id={artist_id} name={name!r} "
        f"image_changed={image_filename is not None}"
    )
    return _to_view(artist)


def update_artist_crop(db: Session, artist_id: int, scale: float, x: int, y: int) -> Optional[ArtistView]:
    """画像位置調整(crop_scale/crop_x/crop_y)を更新する(commit はしない)。

    対象が無ければ None。
    """
    artist = db.query(Artist).filter(Artist.id == artist_id).first()
    if artist is None:
        return None
    artist.crop_scale = scale
    artist.crop_x = x
    artist.crop_y = y
    logger.info(f"update_artist_crop: id={artist_id} scale={scale} x={x} y={y}")
    return _to_view(artist)


def soft_delete_artist(db: Session, artist_id: int) -> bool:
    """論理削除(is_deleted=True)。物理削除はしない(commit はしない)。

    対象が無ければ False、成功したら True。
    """
    artist = db.query(Artist).filter(Artist.id == artist_id).first()
    if artist is None:
        return False
    artist.is_deleted = True
    logger.info(f"soft_delete_artist: id={artist_id}")
    return True


def reassign_timetable_rows(db: Session, old_name: str, new_name: str) -> int:
    """アーティスト統合(merge)時に TimetableRow.artist_name を付け替える。

    付け替えた行数を返す。

    TODO(Phase 5-⑤ merge で実装): 現状はスタブ。
    既存 views/artists.py L247-250 の
    `db.query(TimetableRow).filter(artist_name == old).all()` → 付け替え相当を
    ここへ移す。文字列一致付け替えの意味論(同名衝突・別プロジェクト巻き込み)を
    ⑤で確認したうえで実装する。今回は何もしない。
    """
    return 0
