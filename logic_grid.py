import os
import math
import unicodedata
import re
import cv2
import numpy as np
import requests
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont, ImageOps
from database import get_image_url

# ★追加: パス解決のために constants からディレクトリ情報をインポート
try:
    from constants import FONT_DIR, BASE_DIR
except ImportError:
    # 万が一 constants が読み込めない場合のバックアップ設定
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    FONT_DIR = os.path.join(BASE_DIR, "assets", "fonts")

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
    except:
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
    except: pass
    
    draw.rectangle([(10, 10), (width-10, height-10)], outline=(100, 100, 100), width=2)
    bbox = draw.textbbox((0, 0), text)
    # 中央寄せ
    draw.text(((width - (bbox[2]-bbox[0])) / 2, (height - (bbox[3]-bbox[1])) / 2), text, fill="white")
    return img

def load_image_from_url(url):
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return Image.open(BytesIO(response.content)).convert("RGBA")
    except:
        return None

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

def generate_grid_image(artists, image_dir_unused, font_path="keifont.ttf", row_counts=None, is_brick_mode=True, alignment="center"):
    """
    grid画像を生成する
    """
    target_artists = artists 
    total_images = len(target_artists)
    if total_images == 0: return None

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
                    img_url = get_image_url(target_artist.image_filename)
                    if img_url:
                        img = load_image_from_url(img_url)
                
                if img:
                    # DB値の読み込み
                    crop_scale = getattr(target_artist, 'crop_scale', 1.0) or 1.0
                    crop_x = getattr(target_artist, 'crop_x', 0) or 0
                    crop_y = getattr(target_artist, 'crop_y', 0) or 0

                    is_manual = (crop_scale != 1.0) or (crop_x != 0) or (crop_y != 0)

                    if is_manual:
                        # ★修正: 縮小対応版の apply_manual_crop を呼び出す
                        cropped = apply_manual_crop(img, crop_scale, crop_x, crop_y, TILE_WIDTH, TILE_HEIGHT)
                    else:
                        # 自動調整
                        cropped = crop_smart(img)
                else:
                    cropped = create_no_image_placeholder(TILE_WIDTH, TILE_HEIGHT)
                
                resized_final = cropped.resize((w, h), Image.LANCZOS)
                canvas.paste(resized_final, (int(x), int(current_y)))
            except Exception as e:
                print(f"Image Error ({artist_name}): {e}")
                ph = create_no_image_placeholder(w, h)
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
