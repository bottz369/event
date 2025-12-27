import os
import math
import unicodedata
import re
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

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

def get_face_center_y(img_path):
    try:
        n = np.fromfile(img_path, np.uint8)
        cv_img = cv2.imdecode(n, cv2.IMREAD_COLOR)
    except:
        return None

    if cv_img is None: return None
    
    gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)
    face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
    faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))
    
    if len(faces) > 0:
        total_y = sum([y + (h / 2) for (x, y, w, h) in faces])
        return total_y / len(faces)
    return None

def crop_smart(pil_img, img_path, crop_width, crop_height):
    img_width, img_height = pil_img.size
    face_y = get_face_center_y(img_path)
    
    scale = max(crop_width / img_width, crop_height / img_height)
    new_width = int(img_width * scale)
    new_height = int(img_height * scale)
    
    resized_img = pil_img.resize((new_width, new_height), Image.LANCZOS)
    
    left = (new_width - crop_width) // 2
    
    if face_y is not None:
        target_y = face_y * scale
        top = target_y - (crop_height // 2)
    else:
        top = (new_height * 0.15) - (crop_height // 2)

    if top < 0: top = 0
    if top + crop_height > new_height: top = new_height - crop_height
    
    return resized_img.crop((left, int(top), left + int(crop_width), int(top) + int(crop_height)))

def get_row_distribution(total, base_cols, max_cols):
    """
    従来の自動計算ロジック（列数が指定されない場合に使用）
    """
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

def generate_grid_image(artists, image_dir, font_path="fonts/keifont.ttf", cols=None):
    """
    grid画像を生成する
    cols: 指定された列数（int）。Noneの場合は自動計算。
    """
    valid_artists = [a for a in artists if a.image_filename]
    total_images = len(valid_artists)
    
    if total_images == 0:
        return None

    # --- 行ごとの枚数とレイアウトモードの決定 ---
    if cols and cols > 0:
        # 【カスタムモード】指定された列数で固定する
        # 端数が出ても拡大せず、左詰めで表示する
        row_counts = []
        temp_total = total_images
        while temp_total > 0:
            take = min(cols, temp_total)
            row_counts.append(take)
            temp_total -= take
        
        reference_cols = cols  # キャンバス幅の基準列数
        fixed_grid_mode = True # グリッド固定モード（最後の行を拡大しない）
    else:
        # 【デフォルトモード】自動計算
        row_counts = get_row_distribution(total_images, BASE_COLUMNS, MAX_COLUMNS)
        reference_cols = BASE_COLUMNS
        fixed_grid_mode = False

    # キャンバス全体の幅を計算
    canvas_total_width = (TILE_WIDTH * reference_cols) + (MARGIN * (reference_cols + 1))
    
    # 行ごとの設定（高さやフォントサイズ）を計算
    total_canvas_height = MARGIN 
    row_configs = [] 
    
    for count in row_counts:
        if fixed_grid_mode:
            # 固定モード：常に「基準列数(reference_cols)」で割って1枚のサイズを決める
            # これにより、行の枚数が少なくても画像サイズが巨大化しない
            divisor = reference_cols
            margin_deduction = MARGIN * (reference_cols + 1)
        else:
            # 自動モード：その行の枚数(count)で割って横幅いっぱいに広げる
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

    for config in row_configs:
        count = config["count"]
        w = config["w"]
        h = config["h"]
        th = config["th"]
        font_max = config["font_max"]
        
        for col_idx in range(count):
            if current_img_idx >= total_images: break
            
            target_artist = valid_artists[current_img_idx]
            filename = target_artist.image_filename
            artist_name = target_artist.name
            
            # X座標の計算
            x = MARGIN + (col_idx * (w + MARGIN))
            
            try:
                img_path = os.path.join(image_dir, filename)
                
                if os.path.exists(img_path):
                    img = Image.open(img_path)
                    cropped = crop_smart(img, img_path, w, h)
                    canvas.paste(cropped, (int(x), int(current_y)))

                    # テキストエリア描画
                    text_bg_y = current_y + h
                    draw.rectangle([(x, text_bg_y), (x + w, text_bg_y + th)], fill="white")

                    # フォントサイズ調整
                    current_font_size = font_max
                    while current_font_size > MIN_FONT_SIZE:
                        try:
                            font = ImageFont.truetype(font_path, current_font_size)
                        except:
                            font = ImageFont.load_default()
                            break
                        
                        left, top, right, bottom = draw.textbbox((0, 0), artist_name, font=font)
                        text_w = right - left
                        if text_w < (w - 10): 
                            break 
                        current_font_size -= 2 

                    # 文字配置
                    text_h = bottom - top
                    text_x = x + (w - text_w) / 2
                    text_y = text_bg_y + (th - text_h) / 2 - top 

                    draw.text((text_x, text_y), artist_name, fill="black", font=font)
            except Exception as e:
                print(f"Error processing image {filename}: {e}")
            
            current_img_idx += 1
        
        current_y += (h + th + MARGIN)

    return canvas