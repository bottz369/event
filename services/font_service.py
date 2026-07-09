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

from constants import FONT_DIR
from database import SessionLocal, get_image_url
from repositories import font_repo
from utils import get_sorted_font_list, create_font_specimen_img


def list_sorted_fonts():
    """フォント一覧(dict list)を返す。own_db を共用 helper に渡すだけ(helper 無改造)。"""
    db = SessionLocal()
    try:
        return get_sorted_font_list(db)
    finally:
        db.close()


def build_specimen(font_dicts):
    """フォント見本画像(PIL.Image)を返す。own_db を共用 helper に渡すだけ(helper 無改造)。"""
    db = SessionLocal()
    try:
        return create_font_specimen_img(db, font_dicts)
    finally:
        db.close()


def ensure_font_available(filename) -> str:
    """
    フォントファイルを FONT_DIR に確保する。旧 grid.py check_and_download_font の
    分岐順を厳密踏襲(S0-1)。戻り値で状態を返し、st.toast は書かない(view 戻し)。

    分岐:
      ① 空入力 → "not_found"(旧は無印 return=無 toast。view 戻しでは状態が要るため
         "not_found" に寄せる。空入力=異常入力も not_found 扱い)
      ② makedirs + file_path 算出
      ③ 既にローカルに存在(size>0) → "cached"(旧: 早期 return・無 toast)
      ④ URL 経路: Asset → get_image_url → requests.get 200 → 保存 → "downloaded_url"
      ⑤ binary 経路: AssetFile.file_data → 保存 → "downloaded_db"
      ⑥ どれも当たらず → "not_found"
    例外は旧同様 print で握りつぶし(粒度踏襲)。own_db は try/finally で確実に close。
    """
    if not filename:
        return "not_found"

    abs_font_dir = os.path.abspath(FONT_DIR)
    os.makedirs(abs_font_dir, exist_ok=True)
    file_path = os.path.join(abs_font_dir, filename)

    if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
        return "cached"

    db = SessionLocal()
    try:
        # URL 経路(Asset)
        try:
            asset = font_repo.get_font_asset(db, filename)
            if asset:
                url = get_image_url(asset.image_filename)
                if url:
                    response = requests.get(url, timeout=10)
                    if response.status_code == 200:
                        with open(file_path, "wb") as f:
                            f.write(response.content)
                        return "downloaded_url"
        except Exception as e:
            print(f"URL Download Error: {e}")

        # binary 経路(AssetFile)
        try:
            asset_file = font_repo.get_font_asset_file(db, filename)
            if asset_file and asset_file.file_data:
                with open(file_path, "wb") as f:
                    f.write(asset_file.file_data)
                return "downloaded_db"
        except Exception as e:
            print(f"Binary Write Error: {e}")

        return "not_found"
    finally:
        db.close()
