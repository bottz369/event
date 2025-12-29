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

BASE_COLUMNS = 5      
MAX_COLUMNS = 6       
# ============================================

def get_face_center_y_from_cv_img(cv_img):
    """OpenCV画像データから顔の中心Y座標を返す"""
    if cv_img is None: return None
    
    gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)
    face_cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
    
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
    
    # PIL -> OpenCV変換
    try:
        open_cv_image = np.array(pil_img.convert('RGB')) 
        # RGB to BGR
        open_cv_image = open_cv_image[:, :, ::-1].copy() 
        face_y = get_face_center_y_from_cv_img(open_cv_image)
    except:
        face_y = None
    
    crop_width = TILE_WIDTH
    crop_height = TILE_HEIGHT

    # リサイズ倍率の決定 (隙間なく埋めるため max を使用)
    scale_factor = max(crop_width / img_width, crop_height / img_height)
    resized_w = int(img_width * scale_factor)
    resized_h = int(img_height * scale_factor)
    
    resized_img = pil_img.resize((resized_w, resized_h), Image.LANCZOS)
    
    # クロップ位置の決定
    left = (resized_w - crop_width) // 2
    
    if face_y is not None:
        target_y = face_y * scale_factor
        top = target_y - (crop_height // 2)
    else:
        top = (resized_h * 0.15) - (crop_height // 2)

    # はみ出し補正
    if top < 0: top = 0
    if top + crop_height > resized_h: top = resized_h - crop_height
    
    return resized_img.crop((left, int(top), left + int(crop_width), int(top) + int(crop_height)))

def create_no_image_placeholder(width, height):
    """No Image画像を生成する"""
    # 黒背景
    img = Image.new("RGBA", (width, height), (30, 30, 30, 255))
    draw = ImageDraw.Draw(img)
    
    # テキスト描画 "No Image"
    text = "No Image"
    try:
        # デフォルトフォントより少し大きいフォントを使いたいが、
        # 汎用性を考慮してここではデフォルトを使用（本来はfonts/keifont.ttfなどを読み込むと良い）
        font = ImageFont.load_default()
    except:
        pass
        
    # 中央に配置
    # 文字サイズが小さいので、枠線などで装飾
    draw.rectangle([(10, 10), (width-10, height-10)], outline=(100, 100, 100), width=2)
    
    # 中心座標計算 (簡易的)
    bbox = draw.textbbox((0, 0), text)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    draw.text(((width - tw) / 2, (height - th) / 2), text, fill="white")
    
    return img

def get_row_distribution(total, base_cols, max_cols):
    """自動レイアウト計算"""
    if total == 0: return []
    rows = math.ceil(total / base_cols)
    if rows <= 1: return [total]
    if math.ceil(total / (rows - 1)) <= max_cols: rows -= 1
    base_count = total // rows
    remainder = total % rows
    distribution = []
    for i in range(rows):
        if i >= (rows - remainder): distribution.append(base_count + 1)
        else: distribution.append(base_count)
    return distribution

def load_image_from_url(url):
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return Image.open(BytesIO(response.content)).convert("RGBA")
    except:
        return None

def generate_grid_image(artists, image_dir_unused, font_path="fonts/keifont.ttf", cols=None):
    """
    grid画像を生成する（Supabase対応 & No Image対応）
    """
    # ★変更: 画像がないアーティストも除外せず、全て対象にする
    target_artists = artists 
    total_images = len(target_artists)
    
    if total_images == 0:
        return None

    # --- 行ごとの枚数とレイアウトモードの決定 ---
    if cols and cols > 0:
        row_counts = []
        temp_total = total_images
        while temp_total > 0:
            take = min(cols, temp_total)
            row_counts.append(take)
            temp_total -= take
        reference_cols = cols  
        fixed_grid_mode = True 
    else:
        row_counts = get_row_distribution(total_images, BASE_COLUMNS, MAX_COLUMNS)
        reference_cols = BASE_COLUMNS
        fixed_grid_mode = False

    # キャンバス全体の幅を計算
    canvas_total_width = (TILE_WIDTH * reference_cols) + (MARGIN * (reference_cols + 1))
    
    # 行ごとの設定を計算
    total_canvas_height = MARGIN 
    row_configs = [] 
    
    for count in row_counts:
        if fixed_grid_mode:
            divisor = reference_cols
            margin_deduction = MARGIN * (reference_cols + 1)
        else:
            divisor = count
            margin_deduction = MARGIN * (count + 1)

        available_width = canvas_total_width - margin_deduction
        this_tile_width = available_width / divisor
        
        scale = this_tile_width / TILE_WIDTH
        
        this_tile_height = int(TILE_HEIGHT * scale)
        this_text_height = int(TEXT_AREA_HEIGHT * scale)
        this_font_max = int(MAX_FONT_SIZE * scale)
        
        row_configs.append({
            "count": count,
            "w": int(this_tile_width),
            "h": this_tile_height,
            "th": this_text_height,
            "font_max": this_font_max
        })
        total_canvas_height += (this_tile_height + this_text_height + MARGIN)

    # キャンバス作成
    canvas = Image.new('RGBA', (int(canvas_total_width), int(total_canvas_height)), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    current_img_idx = 0
    current_y = MARGIN 

    default_font = ImageFont.load_default()

    for config in row_configs:
        count = config["count"]
        w = config["w"]
        h = config["h"]
        th = config["th"]
        font_max = config["font_max"]
        
        for col_idx in range(count):
            if current_img_idx >= total_images: break
            
            target_artist = target_artists[current_img_idx]
            artist_name = target_artist.name
            
            # X座標の計算
            x = MARGIN + (col_idx * (w + MARGIN))
            
            try:
                # 1. 画像読み込みを試みる
                img = None
                if target_artist.image_filename:
                    img_url = get_image_url(target_artist.image_filename)
                    if img_url:
                        img = load_image_from_url(img_url)
                
                # 2. クロップまたはNo Image生成
                if img:
                    # 画像がある場合: スマートクロップ
                    cropped = crop_smart(img)
                else:
                    # 画像がない場合: プレースホルダ生成
                    cropped = create_no_image_placeholder(TILE_WIDTH, TILE_HEIGHT)
                
                # 3. グリッドのセルサイズに合わせてリサイズして貼り付け
                resized_final = cropped.resize((w, h), Image.LANCZOS)
                canvas.paste(resized_final, (int(x), int(current_y)))

                # 4. テキストエリア描画
                text_bg_y = current_y + h
                draw.rectangle([(x, text_bg_y), (x + w, text_bg_y + th)], fill="white")

                # フォントサイズ調整
                current_font_size = font_max
                target_font = default_font # 初期値
                
                while current_font_size > MIN_FONT_SIZE:
                    try:
                        if font_path and os.path.exists(font_path):
                            target_font = ImageFont.truetype(font_path, current_font_size)
                        else:
                            target_font = default_font
                            break
                    except:
                        target_font = default_font
                        break
                    
                    bbox = draw.textbbox((0, 0), artist_name, font=target_font)
                    text_w = bbox[2] - bbox[0]
                    if text_w < (w - 10): 
                        break 
                    current_font_size -= 2 

                # 文字配置
                bbox = draw.textbbox((0, 0), artist_name, font=target_font)
                text_w = bbox[2] - bbox[0]
                text_h = bbox[3] - bbox[1]
                
                text_x = x + (w - text_w) / 2
                text_y = text_bg_y + (th - text_h) / 2 - bbox[1]

                draw.text((text_x, text_y), artist_name, fill="black", font=target_font)
                    
            except Exception as e:
                print(f"Error processing artist {artist_name}: {e}")
            
            current_img_idx += 1
        
        current_y += (h + th + MARGIN)

    return canvas
