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

# デフォルト値（引数で渡されない場合の保険）
DEFAULT_COLS = 5      
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
    
    text = "No Image"
    try:
        font = ImageFont.load_default()
    except:
        pass
        
    draw.rectangle([(10, 10), (width-10, height-10)], outline=(100, 100, 100), width=2)
    
    bbox = draw.textbbox((0, 0), text)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    draw.text(((width - tw) / 2, (height - th) / 2), text, fill="white")
    
    return img

def load_image_from_url(url):
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return Image.open(BytesIO(response.content)).convert("RGBA")
    except:
        return None

# =========================================================
# ★修正: 引数に stagger(交互配置) と is_brick_mode(レンガモード) を追加
# =========================================================
def generate_grid_image(artists, image_dir_unused, font_path="fonts/keifont.ttf", cols=5, stagger=False, is_brick_mode=True):
    """
    grid画像を生成する（Supabase対応 & No Image対応 & 高度なレイアウト対応）
    :param cols: 基本の列数
    :param stagger: Trueなら交互配置 (例: 5, 4, 5, 4...)
    :param is_brick_mode: Trueならレンガ(サイズ固定・中央寄せ)、Falseなら両端揃え(サイズ可変)
    """
    target_artists = artists 
    total_images = len(target_artists)
    
    if total_images == 0:
        return None

    if not cols: cols = DEFAULT_COLS

    # 1. アーティストリストを行ごとに分割する
    rows_data = []
    current_idx = 0
    row_iter = 0
    
    while current_idx < total_images:
        # この行の定員を決定
        capacity = cols
        
        # 交互配置がON かつ 偶数行(indexは奇数 1, 3, 5...)の場合、列数を1減らす
        if stagger and (row_iter % 2 == 1):
            capacity = max(1, cols - 1)
            
        chunk = target_artists[current_idx : current_idx + capacity]
        if not chunk: break
        
        rows_data.append(chunk)
        current_idx += len(chunk)
        row_iter += 1

    # 2. キャンバス全体の幅を計算 (最大列数を基準にする)
    # 幅 = (タイル幅 * 列数) + (マージン * (列数+1))
    canvas_total_width = (TILE_WIDTH * cols) + (MARGIN * (cols + 1))
    
    # 3. 各行のレイアウト設定を計算
    row_configs = []
    total_canvas_height = MARGIN 

    for chunk in rows_data:
        count = len(chunk)
        if count == 0: continue
        
        if is_brick_mode:
            # === レンガモード (サイズ統一・中央寄せ) ===
            this_w = int(TILE_WIDTH)
            scale = 1.0 # 拡大縮小なし
            
            # コンテンツの幅 = (タイル幅 * 個数) + (隙間 * (個数-1))
            content_width = (this_w * count) + (MARGIN * (count - 1))
            
            # 中央寄せのための開始位置X
            start_x = (canvas_total_width - content_width) / 2
            
        else:
            # === 両端揃えモード (拡大縮小して埋める) ===
            # 利用可能幅 = 全体幅 - (両端のマージン + 画像間のマージン)
            # 画像間のマージンは (count - 1) 個ではなく、全体のマージン数 (count + 1) で計算して均等割付
            # ここではシンプルに「左右のマージン」と「画像間のマージン」を全て引いた残りを等分する
            
            total_margins = MARGIN * (count + 1)
            available_width = canvas_total_width - total_margins
            
            this_w = available_width / count
            scale = this_w / TILE_WIDTH # 拡大率
            
            start_x = MARGIN # 左端からスタート

        # 高さとフォントサイズをスケールに合わせて調整
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
        
        # 行の高さを加算
        total_canvas_height += (this_h + this_th + MARGIN)

    # 4. キャンバス描画
    canvas = Image.new('RGBA', (int(canvas_total_width), int(total_canvas_height)), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    current_y = MARGIN 
    default_font = ImageFont.load_default()

    for config in row_configs:
        chunk = config["artists"]
        w = config["w"]
        h = config["h"]
        th = config["th"]
        font_max = config["font_max"]
        start_x = config["start_x"]
        
        for col_idx, target_artist in enumerate(chunk):
            artist_name = target_artist.name
            
            # X座標: 行の開始位置 + (インデックス * (幅 + マージン))
            x = start_x + (col_idx * (w + MARGIN))
            
            try:
                # 画像処理 (ここは以前と同じ)
                img = None
                if target_artist.image_filename:
                    img_url = get_image_url(target_artist.image_filename)
                    if img_url:
                        img = load_image_from_url(img_url)
                
                if img:
                    cropped = crop_smart(img)
                else:
                    cropped = create_no_image_placeholder(TILE_WIDTH, TILE_HEIGHT)
                
                # 計算した幅(w, h)にリサイズして配置
                resized_final = cropped.resize((w, h), Image.LANCZOS)
                canvas.paste(resized_final, (int(x), int(current_y)))

                # テキストエリア描画
                text_bg_y = current_y + h
                draw.rectangle([(x, text_bg_y), (x + w, text_bg_y + th)], fill="white")

                # フォントサイズ調整ループ
                current_font_size = font_max
                target_font = default_font
                
                while current_font_size > MIN_FONT_SIZE:
                    try:
                        if font_path and os.path.exists(font_path):
                            target_font = ImageFont.truetype(font_path, int(current_font_size))
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
        
        # 次の行へ
        current_y += (h + th + MARGIN)

    return canvas
