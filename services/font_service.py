"""
Font 関連のビジネスロジック(read + フォント確保の副作用)。

view 層からはこの service を呼び、直接 repository / DB / utils helper を
触らせない。session の生成/クローズは service が所有する(artist_service と同型)。
read のみで commit はしないが、トランザクション境界(open/close)はここで握る。

★ 画面非依存: streamlit を import しない(将来 API / LINE Bot 化の前提, §11.3)。
  フォント確保の状態は戻り値(str)で返し、toast 等の UI は view(grid.py)が担う。

提供:
- list_sorted_fonts()          -> list[dict]  : 共用 helper get_sorted_font_list に own_db を渡す
- build_specimen(font_dicts)   -> PIL.Image   : 共用 helper create_font_specimen_img に own_db を渡す
- ensure_font_available(name)  -> str         : フォントを FS に確保。状態を 4 値で返す
    "cached" / "downloaded_url" / "downloaded_db" / "not_found"
  ※ 共用 helper(get_sorted_font_list / create_font_specimen_img)は無改造。
    ここは own_db を渡すだけの薄いラッパ。
"""
from __future__ import annotations

import os

import requests
from PIL import ImageFont

from constants import FONT_DIR
from database import SessionLocal, get_image_url
from repositories import font_repo
from utils import get_sorted_font_list, create_font_specimen_img
from utils.flyer_helpers import ensure_font_file_exists
from utils.logger import get_logger

from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from PIL import Image

logger = get_logger(__name__)


def _is_usable_font(path: str) -> bool:
    """FONT_DIR 上のファイルが PIL で実際に開けるフォントかを検査する。

    必要な理由: Storage が 200 を返しつつ本文が HTML/JSON のエラーだった場合、
    旧実装は「size>0」だけを見て以後ずっと "cached" を返し続けるため、
    一度壊れたファイルを掴むとコンテナが生きている限り自己修復せず
    日本語ラベルが豆腐(□)のままになる。書き出し後・cached 判定時の両方で検証する。
    """
    try:
        ImageFont.truetype(path, 12)
        return True
    except Exception as e:
        logger.warning("font file is not usable: path=%s err=%s", path, e)
        return False


def _discard_broken(path: str) -> None:
    """使えないフォントファイルを消す(次回の再取得を可能にする)。"""
    try:
        os.remove(path)
        logger.warning("removed unusable font file: %s", path)
    except Exception as e:
        logger.warning("could not remove unusable font file %s: %s", path, e)


def list_sorted_fonts() -> List[dict]:
    """フォント一覧(dict list)を返す。own_db を共用 helper に渡すだけ(helper 無改造)。"""
    db = SessionLocal()
    try:
        return get_sorted_font_list(db)
    finally:
        db.close()


def build_specimen(font_dicts: List[dict]) -> "Image.Image":
    """フォント見本画像(PIL.Image)を返す。own_db を共用 helper に渡すだけ(helper 無改造)。"""
    db = SessionLocal()
    try:
        return create_font_specimen_img(db, font_dicts)
    finally:
        db.close()


def ensure_font_path(filename: str) -> Optional[str]:
    """フォントを FS に確保し、その絶対パス(str)を返す。無ければ None。

    own_db を共用 helper utils.flyer_helpers.ensure_font_file_exists(db, filename) に
    渡すだけの透過ラッパ(helper 無改造)。ensure_font_available(状態返し・grid 用)とは
    別物: こちらはパスを返す(flyer の styles にパスを埋める用途)。
    """
    db = SessionLocal()
    try:
        return ensure_font_file_exists(db, filename)
    finally:
        db.close()


def get_default_font_name() -> str:
    """標準フォントのファイル名を返す。未設定なら "keifont.ttf"(旧 flyer L132-133 と同一)。"""
    db = SessionLocal()
    try:
        sys_conf = font_repo.get_system_font_config(db)
        return sys_conf.filename if sys_conf else "keifont.ttf"
    finally:
        db.close()


def ensure_font_available(filename) -> str:
    """
    フォントファイルを FONT_DIR に確保する。分岐の骨格は旧 grid.py
    check_and_download_font を踏襲(S0-1)しつつ、§42 追撃で「置いたファイルが
    本当にフォントとして開けるか」の検証を各分岐に足している(下記)。
    戻り値で状態を返し、st.toast は書かない(view 戻し)。

    分岐:
      ① 空入力 → "not_found"(旧は無印 return=無 toast。view 戻しでは状態が要るため
         "not_found" に寄せる。空入力=異常入力も not_found 扱い)
      ② makedirs + file_path 算出
      ③ 既にローカルに存在(size>0)かつ PIL で開ける → "cached"
         開けなければ壊れファイルとして削除し、④以降で取り直す
      ④ URL 経路: Asset → get_image_url → requests.get 200 → 保存 → 検証 → "downloaded_url"
      ⑤ binary 経路: AssetFile.file_data → 保存 → 検証 → "downloaded_db"
      ⑥ どれも当たらず → "not_found"
    戻り値の 4 値は従来と同一(views/grid.py の分岐は無改修)。

    §42 追撃で変更した点(いずれも「materialize の確実化」):
      - 書き出し後 / cached 判定時に _is_usable_font で検証する。200 応答でも中身が
        フォントでない場合に size>0 のまま "cached" が固着し、コンテナが生きている
        限り豆腐が直らない事故を防ぐ。
      - 例外を print から logger.warning(exc_info) へ。Railway のログで追えるようにする。
      - timeout=10 → (connect 10s, read 60s)。keifont.ttf は約 4.3MB あり、
        単一の 10 秒では回線が細いときに read timeout で落ちうる。
    own_db は try/finally で確実に close。
    """
    if not filename:
        return "not_found"

    abs_font_dir = os.path.abspath(FONT_DIR)
    os.makedirs(abs_font_dir, exist_ok=True)
    file_path = os.path.join(abs_font_dir, filename)

    if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
        if _is_usable_font(file_path):
            return "cached"
        _discard_broken(file_path)

    db = SessionLocal()
    try:
        # URL 経路(Asset)
        try:
            asset = font_repo.get_font_asset(db, filename)
            if asset:
                url = get_image_url(asset.image_filename)
                if url:
                    response = requests.get(url, timeout=(10, 60))
                    if response.status_code == 200:
                        with open(file_path, "wb") as f:
                            f.write(response.content)
                        if _is_usable_font(file_path):
                            return "downloaded_url"
                        # 中身がフォントでない → 消して binary 経路へ落とす
                        _discard_broken(file_path)
                    else:
                        logger.warning(
                            "font download failed: name=%s status=%s url=%s",
                            filename, response.status_code, url,
                        )
        except Exception as e:
            logger.warning("URL font download error: name=%s err=%s", filename, e, exc_info=True)

        # binary 経路(AssetFile)
        try:
            asset_file = font_repo.get_font_asset_file(db, filename)
            if asset_file and asset_file.file_data:
                with open(file_path, "wb") as f:
                    f.write(asset_file.file_data)
                if _is_usable_font(file_path):
                    return "downloaded_db"
                _discard_broken(file_path)
        except Exception as e:
            logger.warning("binary font write error: name=%s err=%s", filename, e, exc_info=True)

        logger.warning("font not available anywhere: name=%s dir=%s", filename, abs_font_dir)
        return "not_found"
    finally:
        db.close()
