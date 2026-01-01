import os
import math
import unicodedata
import re
import cv2
import numpy as np
import requests
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
from database import get_image_url

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
    if not os.path.exists(face_cascade_path): return None
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
        open_cv_image = np.array(pil_img.convert('RGB')) 
        open_cv_image = open_cv_image[:, :, ::-1].copy() 
        face_y = get_face_center_y_from_cv_img(open_cv_image)
    except:
        face_y = None
    
    crop_width = TILE_WIDTH
    crop_height = TILE_HEIGHT
    scale_factor = max(crop_width / img_width, crop_height / img_height)
    resized_w = int(img_width * scale_factor)
    resized_h = int(img_height * scale_factor)
    resized_img = pil_img.resize((resized_w, resized_h), Image.LANCZOS)
    left = (resized_w - crop_width) // 2
    if face_y is not None:
        target_y = face_y * scale_factor
        top = target_y - (crop_height // 2)
    else:
        top = (resized_h * 0.15) - (crop_height // 2)
    if top < 0: top = 0
    if top + crop_height > resized_h: top = resized_h - crop_height
    return resized_img.crop((left, int(top), left + int(crop_width), int(top) + int(crop_height)))

def create_no_image_placeholder(width, height):
    """No Image画像を生成する"""
    img = Image.new("RGBA", (width, height), (30, 30, 30, 255))
    draw = ImageDraw.Draw(img)
    text = "No Image"
    try: font = ImageFont.load_default()
    except: pass
    draw.rectangle([(10, 10), (width-10, height-10)], outline=(100, 100, 100), width=2)
    bbox = draw.textbbox((0, 0), text)
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
# ★修正済み: フォント適用ロジックを強化
# =========================================================
def generate_grid_image(artists, image_dir_unused, font_path="fonts/keifont.ttf", row_counts=None, is_brick_mode=True, alignment="center"):
    """
    grid画像を生成する
    :param row_counts: 各行の枚数リスト [3, 4, 6] など
    :param is_brick_mode: Trueならレンガ(サイズ固定)、Falseなら両端揃え
    :param alignment: "left", "center", "right" (レンガモード時の配置)
    """
    target_artists = artists 
    total_images = len(target_artists)
    if total_images == 0: return None

    # 行指定がない場合の安全策
    if not row_counts: row_counts = [5] * 10

    # 1. アーティストリストを行ごとに分割する
    rows_data = []
    current_idx = 0
    
    # 指定されたカウントに従って切り出していく
    for capacity in row_counts:
        if current_idx >= total_images: break
        if capacity <= 0: capacity = 1 # 0除算防止
        
        chunk = target_artists[current_idx : current_idx + capacity]
        if not chunk: break
        
        rows_data.append(chunk)
        current_idx += len(chunk)
    
    # リストに余りが出た場合（設定より画像が多い場合）、新しい行に追加
    while current_idx < total_images:
        capacity = 5 # デフォルト
        chunk = target_artists[current_idx : current_idx + capacity]
        rows_data.append(chunk)
        current_idx += len(chunk)

    # 2. キャンバス全体の幅を決定
    # 設定された中で「最大枚数」を基準にキャンバス幅を決める
    max_cols = max(row_counts) if row_counts else 5
    # 実際のデータ上の最大枚数とも比較（設定が [2,2] なのにデータが10個ある場合などへの対処）
    max_cols = max(max_cols, max([len(r) for r in rows_data]))

    canvas_total_width = (TILE_WIDTH * max_cols) + (MARGIN * (max_cols + 1))
    
    # 3. 各行のレイアウト設定を計算
    row_configs = []
    total_canvas_height = MARGIN 

    for chunk in rows_data:
        count = len(chunk)
        if count == 0: continue
        
        if is_brick_mode:
            # === レンガモード (サイズ統一・指定位置揃え) ===
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
            # === 両端揃えモード (拡大縮小して埋める) ===
            # 左揃えなどは関係なく、常に両端いっぱいに広がる
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

    # 4. キャンバス描画
    canvas = Image.new('RGBA', (int(canvas_total_width), int(total_canvas_height)), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    current_y = MARGIN 
    default_font = ImageFont.load_default()

    # ★デバッグ用: フォントパスが正しいか一度確認してコンソールに出す
    font_exists = False
    if font_path and os.path.exists(font_path):
        font_exists = True
    else:
        print(f"⚠️ Warning: Font file not found at '{font_path}'. Using default font.")

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
            
            try:
                img = None
                if target_artist.image_filename:
                    img_url = get_image_url(target_artist.image_filename)
                    if img_url:
                        img = load_image_from_url(img_url)
                
                if img:
                    cropped = crop_smart(img)
                else:
                    cropped = create_no_image_placeholder(TILE_WIDTH, TILE_HEIGHT)
                
                resized_final = cropped.resize((w, h), Image.LANCZOS)
                canvas.paste(resized_final, (int(x), int(current_y)))

                text_bg_y = current_y + h
                draw.rectangle([(x, text_bg_y), (x + w, text_bg_y + th)], fill="white")

                # === ★ここを修正: フォントサイズ自動調整ロジック ===
                current_font_size = font_max
                target_font = default_font # 初期値

                while current_font_size > MIN_FONT_SIZE:
                    try:
                        # フォントファイルが存在する場合のみ読み込みを試行
                        if font_exists:
                            target_font = ImageFont.truetype(font_path, int(current_font_size))
                        else:
                            # 存在しない場合はループを抜けてデフォルトフォントを使用
                            target_font = default_font
                            break
                    except Exception as e:
                        print(f"Font load error: {e}")
                        target_font = default_font
                        break

                    bbox = draw.textbbox((0, 0), artist_name, font=target_font)
                    text_w = bbox[2] - bbox[0]
                    
                    # 幅に収まれば決定
                    if text_w < (w - 10):
                        break 
                    
                    # 収まらなければサイズを小さくして再トライ
                    current_font_size -= 2 

                # 最終的な描画
                bbox = draw.textbbox((0, 0), artist_name, font=target_font)
                text_w = bbox[2] - bbox[0]
                text_h = bbox[3] - bbox[1]
                text_x = x + (w - text_w) / 2
                text_y = text_bg_y + (th - text_h) / 2 - bbox[1]
                draw.text((text_x, text_y), artist_name, fill="black", font=target_font)
                    
            except Exception as e:
                print(f"Error processing artist {artist_name}: {e}")
        
        current_y += (h + th + MARGIN)

    return canvas
