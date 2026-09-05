import os
import math
import unicodedata
import re
from concurrent.futures import ThreadPoolExecutor
import cv2
import numpy as np
import requests
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont, ImageOps
import logging
from database import get_image_url

# ★追加: パス解決のために constants からディレクトリ情報をインポート
try:
    from constants import FONT_DIR, BASE_DIR
except ImportError:
    # 万が一 constants が読み込めない場合のバックアップ設定
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    FONT_DIR = os.path.join(BASE_DIR, "assets", "fonts")

logger = logging.getLogger(__name__)

# §5: 素材取得失敗の可観測化。ログは failures の有無に関わらず常に出す。
# failures は任意 out-param(既定 None)で、None のときは従来と完全に同一挙動。
# 構造化エントリの収集はメインスレッドで url_jobs と image_cache を突合して行う
# (contextvars は ThreadPoolExecutor の worker へ伝播しないので使わない)。

# ================= 設定エリア =================
TILE_WIDTH = 800       
TILE_HEIGHT = 450      
TEXT_AREA_HEIGHT = 160 
MARGIN = 25           

MAX_FONT_SIZE = 80     
MIN_FONT_SIZE = 25     
# ============================================

def get_face_center_y_from_cv_img(cv_img):
    """OpenCV画像データから顔の中心Y座標を返す"""
    if cv_img is None: return None
    gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)
    face_cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
    # カスケードファイルがない場合のフォールバック
    if not os.path.exists(face_cascade_path):
        return None
        
    face_cascade = cv2.CascadeClassifier(face_cascade_path)
    faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))
    if len(faces) > 0:
        total_y = sum([y + (h / 2) for (x, y, w, h) in faces])
        return total_y / len(faces)
    return None

def crop_smart(pil_img):
    """スマートクロッピング関数"""
    img_width, img_height = pil_img.size
    try:
        # OpenCV形式への変換
        open_cv_image = np.array(pil_img.convert('RGB')) 
        open_cv_image = open_cv_image[:, :, ::-1].copy() 
        face_y = get_face_center_y_from_cv_img(open_cv_image)
    except Exception:
        face_y = None
    
    crop_width = TILE_WIDTH
    crop_height = TILE_HEIGHT
    
    # リサイズ比率の計算
    scale_factor = max(crop_width / img_width, crop_height / img_height)
    resized_w = int(img_width * scale_factor)
    resized_h = int(img_height * scale_factor)
    resized_img = pil_img.resize((resized_w, resized_h), Image.LANCZOS)
    
    left = (resized_w - crop_width) // 2
    
    # 顔位置に合わせてクロップ位置を調整
    if face_y is not None:
        target_y = face_y * scale_factor
        top = target_y - (crop_height // 2)
    else:
        # 顔が見つからない場合は少し上寄り(15%)を中心にする
        top = (resized_h * 0.15) - (crop_height // 2)
        
    if top < 0: top = 0
    if top + crop_height > resized_h: top = resized_h - crop_height
    
    return resized_img.crop((left, int(top), left + int(crop_width), int(top) + int(crop_height)))

# --- ★修正: 手動トリミングロジック (縮小・黒背景対応) ---
def apply_manual_crop(img, scale=1.0, x_off=0, y_off=0, target_w=TILE_WIDTH, target_h=TILE_HEIGHT):
    """
    画像を中心からトリミング・リサイズ・配置する関数
    scale: 1.0=基準サイズ, <1.0=縮小, >1.0=拡大
    x_off: 正=右へ移動, 負=左へ移動 (ピクセル)
    y_off: 正=下へ移動, 負=上へ移動 (ピクセル)
    余白は黒塗り(0,0,0)で埋めます。
    """
    if not img: return create_no_image_placeholder(target_w, target_h)

    # 1. 基準サイズ(Cover)の計算
    img_ratio = img.width / img.height
    target_ratio = target_w / target_h

    if img_ratio > target_ratio:
        # 画像の方が横長 -> 高さを合わせる
        base_h = target_h
        base_w = int(base_h * img_ratio)
    else:
        # 画像の方が縦長 -> 幅を合わせる
        base_w = target_w
        base_h = int(base_w / img_ratio)

    # 2. スケール適用 (縮小も許可)
    final_w = max(1, int(base_w * scale))
    final_h = max(1, int(base_h * scale))

    resized_img = img.resize((final_w, final_h), Image.LANCZOS)

    # 3. 黒背景のキャンバス作成
    canvas = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 255))

    # 4. 配置位置の計算
    # キャンバス中心 (target_w/2, target_h/2) に 画像中心 (final_w/2, final_h/2) を合わせる
    # そこにオフセット (x_off, y_off) を加算
    paste_x = int((target_w - final_w) / 2 + x_off)
    paste_y = int((target_h - final_h) / 2 + y_off)

    # 5. 貼り付け (透過情報も考慮)
    if resized_img.mode != "RGBA":
        resized_img = resized_img.convert("RGBA")
    
    canvas.paste(resized_img, (paste_x, paste_y), resized_img)

    return canvas.convert("RGB")


def create_no_image_placeholder(width, height):
    """No Image画像を生成する"""
    img = Image.new("RGBA", (width, height), (30, 30, 30, 255))
    draw = ImageDraw.Draw(img)
    text = "No Image"
    try: font = ImageFont.load_default()
    except Exception: pass
    
    draw.rectangle([(10, 10), (width-10, height-10)], outline=(100, 100, 100), width=2)
    bbox = draw.textbbox((0, 0), text)
    # 中央寄せ
    draw.text(((width - (bbox[2]-bbox[0])) / 2, (height - (bbox[3]-bbox[1])) / 2), text, fill="white")
    return img

# =========================================================
# アー写未登録枠のプレースホルダ(段階C C-6a)
# =========================================================
# 写真が引けない枠を黒背景 + 案内文で描く。新規イベントで出演者がまだ未登録でも
# グリッド/フライヤーが穴あきに見えず、次に何をすればいいかが画像から分かる。
#
# ★create_no_image_placeholder(既存の "No Image")とは別関数にしてある。
#   あちらは views/artists.py のアー写プレビューでも使われており、そちらに
#   LINE 向けの案内文が出るのは筋が違うため。グリッド生成だけがこちらを使う。
UNREGISTERED_PHOTO_TITLE = "アー写未登録"
UNREGISTERED_PHOTO_GUIDE = "メンションを付けて\nアー写の新規登録を進めてください"

# タイル高に対する文字サイズの比率(収まらなければ縮めていく)
_PLACEHOLDER_TITLE_RATIO = 0.13
_PLACEHOLDER_GUIDE_RATIO = 0.075
_PLACEHOLDER_MIN_FONT = 10


def _load_font(font_path, size):
    """指定サイズでフォントを開く。開けなければ PIL 既定フォント。"""
    if font_path:
        try:
            return ImageFont.truetype(font_path, int(size))
        except Exception:
            pass
    try:
        return ImageFont.load_default()
    except Exception:
        return None


def _wrap_to_width(draw, text, font, max_width):
    """max_width に収まるよう文字単位で折り返す(日本語なので単語境界を使わない)。

    元テキストの改行は尊重する。
    """
    lines = []
    for paragraph in str(text).split("\n"):
        if not paragraph:
            lines.append("")
            continue
        current = ""
        for ch in paragraph:
            trial = current + ch
            if draw.textlength(trial, font=font) <= max_width or not current:
                current = trial
            else:
                lines.append(current)
                current = ch
        if current:
            lines.append(current)
    return lines


def _measure(draw, lines, font, line_gap):
    """折り返し済みの行群の (幅, 高さ) を返す。"""
    if not lines:
        return 0, 0
    widths = [draw.textlength(l, font=font) for l in lines]
    bbox = draw.textbbox((0, 0), "あA", font=font)
    line_h = (bbox[3] - bbox[1]) + line_gap
    return max(widths), line_h * len(lines)


def create_unregistered_photo_placeholder(width, height, font_path=None):
    """アー写が無い枠を黒背景 + 案内文で描く。

    中央に「アー写未登録」と、その下に登録手順の案内を出す。案内はセル幅に
    合わせて折り返し、それでも収まらなければ文字サイズを下げる。最後まで
    収まらない極端に小さいセルでは、タイトルだけでも読めるようにする。

    font_path には materialize 済みの実パスを渡すこと(渡さないと PIL 既定
    フォントになり日本語が豆腐化する・罠40)。
    """
    width = max(int(width), 1)
    height = max(int(height), 1)
    img = Image.new("RGBA", (width, height), (0, 0, 0, 255))
    draw = ImageDraw.Draw(img)

    # 枠線(黒背景だけだと隣のセルとの境界が分からないため)
    draw.rectangle([(0, 0), (width - 1, height - 1)], outline=(70, 70, 70), width=2)

    inner_w = width * 0.86
    inner_h = height * 0.86
    line_gap = max(int(height * 0.012), 1)
    block_gap = max(int(height * 0.05), 2)

    title_size = max(height * _PLACEHOLDER_TITLE_RATIO, _PLACEHOLDER_MIN_FONT)
    guide_size = max(height * _PLACEHOLDER_GUIDE_RATIO, _PLACEHOLDER_MIN_FONT)

    title_lines = guide_lines = []
    title_font = guide_font = None
    total_h = 0
    # 収まるまで縮める(タイトルと案内を同じ比率で下げる)
    for _ in range(12):
        title_font = _load_font(font_path, title_size)
        guide_font = _load_font(font_path, guide_size)
        if title_font is None or guide_font is None:
            return img  # フォントが全く使えない環境。黒枠だけ返す(落とさない)
        title_lines = _wrap_to_width(draw, UNREGISTERED_PHOTO_TITLE, title_font, inner_w)
        guide_lines = _wrap_to_width(draw, UNREGISTERED_PHOTO_GUIDE, guide_font, inner_w)
        _, th = _measure(draw, title_lines, title_font, line_gap)
        _, gh = _measure(draw, guide_lines, guide_font, line_gap)
        total_h = th + block_gap + gh
        if total_h <= inner_h:
            break
        if title_size <= _PLACEHOLDER_MIN_FONT and guide_size <= _PLACEHOLDER_MIN_FONT:
            # これ以上小さくできない。案内を落としてタイトルだけ残す
            guide_lines = []
            _, total_h = _measure(draw, title_lines, title_font, line_gap)
            break
        title_size = max(title_size * 0.85, _PLACEHOLDER_MIN_FONT)
        guide_size = max(guide_size * 0.85, _PLACEHOLDER_MIN_FONT)

    def _draw_block(lines, font, y):
        bbox = draw.textbbox((0, 0), "あA", font=font)
        line_h = (bbox[3] - bbox[1]) + line_gap
        for line in lines:
            w = draw.textlength(line, font=font)
            draw.text(((width - w) / 2, y), line, font=font, fill=(255, 255, 255, 255))
            y += line_h
        return y

    y = (height - total_h) / 2
    y = _draw_block(title_lines, title_font, y)
    if guide_lines:
        y += block_gap
        _draw_block(guide_lines, guide_font, y)
    return img


def load_image_from_url(url):
    if not url:
        return None  # 空 URL は失敗ではない(ログも出さない)
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return Image.open(BytesIO(response.content)).convert("RGBA")
    except Exception as e:
        logger.warning(
            "artist photo load failed: url=%r reason=%s: %s", url, type(e).__name__, e
        )
        return None


# =========================================================
# OOM 対策: 読み込み時 downscale(最長辺の上限)
# =========================================================
# grid 生成で保持する元アー写の最長辺の上限(px)。元画像が高解像度(実測で 22MP 等)
# だとデコード RGBA と中間コピーがメモリを圧迫し OOM する。タイルは 800px 描画なので
# 1200px あれば出力画質は不変。縮小のみ(元が小さい画像は拡大しない)。
# ※ apply_manual_crop の crop_x/crop_y/crop_scale はタイル(800x450)空間基準のため、
#   元画像を縮小しても座標の再スケールは不要(アスペクト比は維持する)。
GRID_MAX_LOAD_EDGE = 1200


def _downscale_max_edge(img, max_edge=GRID_MAX_LOAD_EDGE):
    """アスペクト比を維持して最長辺を max_edge 以下へ縮小する(in-place)。

    元画像が max_edge 以下なら何もしない(拡大はしない)。縮小は LANCZOS。
    """
    if img is None:
        return img
    if max(img.size) <= max_edge:
        return img
    img.thumbnail((max_edge, max_edge), Image.LANCZOS)
    return img


def _load_and_downscale(url):
    """URL 取得 → JPEG draft デコード → downscale。worker スレッド内で縮小する。

    OOM 対策: Image.draft("RGB", (1200,1200)) を load 前に呼び、巨大 JPEG を
    DCT スケールを落として復号する(22MP をフル復号せず ~1/4 で読む)。フル解像度の
    RGBA を一度も確保しないため、ピーク一時確保と断片化を大きく抑える。
    - draft は JPEG のみ有効。PNG 等では no-op(例外時も従来どおり続行)。
    - draft は load()(=convert)より前に呼ぶ必要がある。draft 後に _downscale_max_edge
      で最終 1200px へ確定。crop 座標はタイル空間基準のため再スケール不要(不変)。
    ※ アプリ共有の load_image_from_url は変更しない(この grid 専用経路のみ draft する)。
    """
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        im = Image.open(BytesIO(response.content))
        try:
            im.draft("RGB", (GRID_MAX_LOAD_EDGE, GRID_MAX_LOAD_EDGE))
        except Exception:
            pass  # draft 非対応(PNG 等)/失敗時はフル復号にフォールバック
        im = im.convert("RGBA")
        return _downscale_max_edge(im)
    except Exception as e:
        logger.warning(
            "artist photo load failed: url=%r reason=%s: %s", url, type(e).__name__, e
        )
        return None


# =========================================================
# Phase 3 P2: アー写画像並列取得ヘルパー
# =========================================================
def _fetch_grid_images_parallel(target_artists, failures=None):
    """target_artists の各 image_filename を ThreadPoolExecutor で並列取得し、
    {artist.id: PIL.Image or None} の dict を返す。出力画像 (キャンバス合成結果)
    は不変。HTTP 取得の wall-clock 時間を短縮するための取得フェーズのみ並列化。

    - artist.id で dedupe (同一 ID の重複取得を防ぐ)
    - URL 生成 (get_image_url) は直列 (DB を引かない・軽い文字列処理)
    - HTTP 取得は max_workers=8 で並列
    - 失敗時は None を返す (既存 load_image_from_url の挙動と同じ)
    - image_filename が無い / URL が None の artist は dict に含めない
      → 呼び出し側で None が返り、create_unregistered_photo_placeholder にフォールバック
    """
    # dedupe (artist.id がキー)
    by_id = {}
    for a in target_artists:
        if a.id in by_id:
            continue
        by_id[a.id] = a

    # 取得対象を url_jobs にまとめる (URL 生成は直列・軽い)
    url_jobs = []  # list of (artist_id, url)
    for a in by_id.values():
        if not a.image_filename:
            continue
        url = get_image_url(a.image_filename)
        if not url:
            continue
        url_jobs.append((a.id, url))

    image_cache = {}
    if url_jobs:
        with ThreadPoolExecutor(max_workers=8) as executor:
            # OOM 対策: worker 内で取得直後に最長辺 1200px へ縮小(_load_and_downscale)。
            # 完了済み future にフル解像度が滞留せず、合成前に保持するのも縮小済み画像のみ。
            # 縮小のみ・アスペクト比維持なので手動クロップ座標の補正は不要。
            future_to_id = {executor.submit(_load_and_downscale, url): aid for (aid, url) in url_jobs}
            for fut in future_to_id:
                aid = future_to_id[fut]
                try:
                    image_cache[aid] = fut.result()
                except Exception as e:
                    logger.warning(
                        "artist photo worker failed: id=%r reason=%s: %s",
                        aid, type(e).__name__, e,
                    )
                    image_cache[aid] = None

    # §5: 失敗の構造化収集は【メインスレッド】で、全 future 解決後に行う。
    # 「取得を試みた(url_jobs にある)のに結果が None」= 失敗。
    # image_filename が無い / URL 化できないアーティストは url_jobs に入らないので数えない。
    if failures is not None:
        for aid, url in url_jobs:
            if image_cache.get(aid) is None:
                artist = by_id.get(aid)
                failures.append({
                    "kind": "artist_photo",
                    "name": getattr(artist, "name", None),
                    "url": url,
                    "reason": "fetch_failed",
                })

    return image_cache


# =========================================================
# フォントパス解決ロジック
# =========================================================
def resolve_font_path(font_path_input):
    """
    入力されたフォントパスから実在するパスを返す
    """
    if not font_path_input:
        return None

    # 検索候補リスト
    candidates = [
        font_path_input,                                                      
        os.path.join(FONT_DIR, os.path.basename(font_path_input)), 
        os.path.join("assets", "fonts", os.path.basename(font_path_input)), 
        os.path.join(BASE_DIR, "assets", "fonts", os.path.basename(font_path_input)), 
        os.path.join("fonts", os.path.basename(font_path_input)), 
        os.path.join(os.getcwd(), os.path.basename(font_path_input)), 
    ]

    for path in candidates:
        if os.path.exists(path) and os.path.isfile(path):
            return path
    
    return None

def generate_grid_image(artists, image_dir_unused, font_path="keifont.ttf", row_counts=None, is_brick_mode=True, alignment="center", failures=None):
    """
    grid画像を生成する
    """
    target_artists = artists 
    total_images = len(target_artists)
    if total_images == 0: return None

    # Phase 3 P2: アー写画像を並列取得 (取得フェーズと加工フェーズの分離・出力不変)
    image_cache = _fetch_grid_images_parallel(target_artists, failures=failures)

    # 行指定がない場合の安全策
    if not row_counts: row_counts = [5] * 10

    # 1. アーティストリストを行ごとに分割する
    rows_data = []
    current_idx = 0
    
    for capacity in row_counts:
        if current_idx >= total_images: break
        if capacity <= 0: capacity = 1 
        
        chunk = target_artists[current_idx : current_idx + capacity]
        if not chunk: break
        
        rows_data.append(chunk)
        current_idx += len(chunk)
    
    while current_idx < total_images:
        capacity = 5 
        chunk = target_artists[current_idx : current_idx + capacity]
        rows_data.append(chunk)
        current_idx += len(chunk)

    # 2. キャンバス全体の幅を決定
    max_cols = max(row_counts) if row_counts else 5
    max_cols = max(max_cols, max([len(r) for r in rows_data]))

    canvas_total_width = (TILE_WIDTH * max_cols) + (MARGIN * (max_cols + 1))
    
    # 3. 各行のレイアウト設定を計算
    row_configs = []
    total_canvas_height = MARGIN 

    for chunk in rows_data:
        count = len(chunk)
        if count == 0: continue
        
        if is_brick_mode:
            # レンガモード
            this_w = int(TILE_WIDTH)
            scale = 1.0 
            content_width = (this_w * count) + (MARGIN * (count - 1))
            
            if alignment == "left":
                start_x = MARGIN
            elif alignment == "right":
                start_x = canvas_total_width - MARGIN - content_width
            else: # center
                start_x = (canvas_total_width - content_width) / 2
        else:
            # 両端揃えモード
            total_margins = MARGIN * (count + 1)
            available_width = canvas_total_width - total_margins
            this_w = available_width / count
            scale = this_w / TILE_WIDTH
            start_x = MARGIN 

        this_h = int(TILE_HEIGHT * scale)
        this_th = int(TEXT_AREA_HEIGHT * scale)
        this_font_max = int(MAX_FONT_SIZE * scale)
        
        row_configs.append({
            "artists": chunk,
            "w": int(this_w),
            "h": this_h,
            "th": this_th,
            "font_max": this_font_max,
            "start_x": start_x
        })
        
        total_canvas_height += (this_h + this_th + MARGIN)

    # 4. キャンバス描画開始
    canvas = Image.new('RGBA', (int(canvas_total_width), int(total_canvas_height)), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    current_y = MARGIN 
    default_font = ImageFont.load_default()

    # フォントパスの解決
    valid_font_path = resolve_font_path(font_path)
    if not valid_font_path:
        valid_font_path = resolve_font_path("keifont.ttf")
    font_exists = (valid_font_path is not None)

    for config in row_configs:
        chunk = config["artists"]
        w = config["w"]
        h = config["h"]
        th = config["th"]
        font_max = config["font_max"]
        start_x = config["start_x"]
        
        for col_idx, target_artist in enumerate(chunk):
            artist_name = target_artist.name
            
            x = start_x + (col_idx * (w + MARGIN))
            
            # --- 画像描画 ---
            try:
                img = None
                if target_artist.image_filename:
                    # Phase 3 P2: 並列取得済みの image_cache から取り出し (出力不変・get_image_url/load_image_from_url の直列呼び出しを置換)
                    img = image_cache.get(target_artist.id)
                
                if img:
                    # DB値の読み込み
                    crop_scale = getattr(target_artist, 'crop_scale', 1.0) or 1.0
                    crop_x = getattr(target_artist, 'crop_x', 0) or 0
                    crop_y = getattr(target_artist, 'crop_y', 0) or 0

                    # Phase 3 P2 コミットB: 顔検出(crop_smart)を grid から撤去。
                    # 未設定(scale=1.0,x=0,y=0)でも apply_manual_crop は中央寄せ Cover
                    # (黒余白なし)になるため分岐不要。手動設定済みは従来通り設定値が
                    # 反映される(動作不変)。
                    # crop_smart 関数自体は views/artists.py が使うため残置(ここから
                    # 呼ばないだけ)。
                    cropped = apply_manual_crop(img, crop_scale, crop_x, crop_y, TILE_WIDTH, TILE_HEIGHT)
                else:
                    # C-6a: アー写が無い/引けない枠は黒プレースホルダ + 案内文。
                    # 解決済みフォントを渡さないと案内が豆腐になる(罠40)。
                    cropped = create_unregistered_photo_placeholder(
                        TILE_WIDTH, TILE_HEIGHT,
                        font_path=valid_font_path if font_exists else None,
                    )
                
                resized_final = cropped.resize((w, h), Image.LANCZOS)
                canvas.paste(resized_final, (int(x), int(current_y)))
            except Exception as e:
                logger.warning("artist photo render failed: name=%r: %s",
                               artist_name, e, exc_info=True)
                # 加工中の例外でも、利用者から見れば「写真が出ていない枠」なので
                # 同じ案内を出す(やることも同じ = アー写を登録し直す)。
                ph = create_unregistered_photo_placeholder(
                    w, h, font_path=valid_font_path if font_exists else None)
                canvas.paste(ph, (int(x), int(current_y)))

            # --- テキストエリア背景 ---
            text_bg_y = current_y + h
            draw.rectangle([(x, text_bg_y), (x + w, text_bg_y + th)], fill="white")

            # --- テキスト描画 ---
            current_font_size = font_max
            target_font = default_font

            while current_font_size > MIN_FONT_SIZE:
                try:
                    if font_exists:
                        target_font = ImageFont.truetype(valid_font_path, int(current_font_size))
                    else:
                        target_font = default_font
                        break
                except Exception:
                    target_font = default_font
                    break

                bbox = draw.textbbox((0, 0), artist_name, font=target_font)
                text_w = bbox[2] - bbox[0]
                
                if text_w < (w - 10):
                    break 
                
                current_font_size -= 2 

            try:
                bbox = draw.textbbox((0, 0), artist_name, font=target_font)
                text_w = bbox[2] - bbox[0]
                text_h = bbox[3] - bbox[1]
                
                text_x = x + (w - text_w) / 2
                text_y = text_bg_y + (th - text_h) / 2 - bbox[1]
                
                draw.text((text_x, text_y), artist_name, fill="black", font=target_font)
            except Exception:
                pass
        
        current_y += (h + th + MARGIN)

    return canvas
