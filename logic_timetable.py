from PIL import Image, ImageDraw, ImageFont, ImageOps
import math
import os
import requests
from io import BytesIO
import streamlit as st

# ================= 設定エリア =================
SINGLE_COL_WIDTH = 1450      
COLUMN_GAP = 80             
WIDTH = (SINGLE_COL_WIDTH * 2) + COLUMN_GAP
ROW_HEIGHT = 130            
ROW_MARGIN = 12             

FONT_SIZE_TIME = 60         
FONT_SIZE_ARTIST = 60       
FONT_SIZE_GOODS = 48        

# ★変更1: 全体の背景を「完全透明」に設定
COLOR_BG_ALL = (0, 0, 0, 0)        

# ★変更2: 黒フィルターの濃さをアップ (130 -> 170)
# 数値を大きくするとさらに暗くなります (最大255)
OVERLAY_OPACITY = 170

COLOR_TEXT = (255, 255, 255, 255)   

AREA_TIME_X = 20
AREA_TIME_W = 320 
AREA_ARTIST_X = 350
AREA_ARTIST_W = 650
AREA_GOODS_X = 1020
AREA_GOODS_W = 410

# ================= ヘルパー関数 =================

def get_font(path, size):
    candidates = [
        path,
        os.path.join("assets", "fonts", "keifont.ttf"),
        "fonts/keifont.ttf",
        "keifont.ttf"
    ]
    for c in candidates:
        if c and os.path.exists(c):
            try: return ImageFont.truetype(c, size)
            except: continue
    return ImageFont.load_default()

def load_image(path_or_url):
    if not path_or_url: return None
    try:
        if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
            response = requests.get(path_or_url, timeout=10)
            if response.status_code != 200: return None
            return Image.open(BytesIO(response.content)).convert("RGBA")
        if os.path.exists(path_or_url):
             return Image.open(path_or_url).convert("RGBA")
        return None
    except Exception: return None

def draw_centered_text(draw, text, box_x, box_y, box_w, box_h, font_path, max_font_size, align="center"):
    text = str(text).strip()
    if not text: return
    current_font_size = max_font_size
    font = get_font(font_path, current_font_size)
    min_font_size = 15
    while current_font_size > min_font_size:
        bbox = draw.multiline_textbbox((0, 0), text, font=font, spacing=4)
        if (bbox[2]-bbox[0]) <= (box_w - 10) and (bbox[3]-bbox[1]) <= (box_h - 4): break
        current_font_size -= 2
        font = get_font(font_path, current_font_size)
    
    bbox = draw.multiline_textbbox((0, 0), text, font=font, spacing=4)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    final_y = box_y + (box_h - text_h) / 2
    if align == "center": final_x = box_x + (box_w - text_w) / 2
    elif align == "right": final_x = box_x + box_w - text_w
    else: final_x = box_x
    
    # 視認性を高めるためのテキストの影（ドロップシャドウ）
    draw.multiline_text((final_x+2, final_y+2), text, fill=(0,0,0,200), font=font, spacing=4, align=align)
    draw.multiline_text((final_x, final_y), text, fill=COLOR_TEXT, font=font, spacing=4, align=align)

def draw_one_row(draw, canvas, base_x, base_y, row_data, font_path, db):
    time_str, name_str = row_data[0], str(row_data[1]).strip()
    goods_time, goods_place = row_data[2], row_data[3]

    # ---------------------------------------------------------
    # 1. 画像処理 & 透過黒フィルター合成
    # ---------------------------------------------------------
    
    # ベースとなる透明な行画像を作成
    row_img = Image.new('RGBA', (SINGLE_COL_WIDTH, ROW_HEIGHT), (0, 0, 0, 0))
    has_image = False

    # 特殊行以外は画像を検索して貼り付け
    if name_str and name_str not in ["OPEN / START", "開演前物販", "終演後物販"]:
        try:
            from database import Artist, get_image_url
            artist = db.query(Artist).filter(Artist.name == name_str, Artist.is_deleted == False).first()
            if not artist:
                clean = name_str.replace(" ", "").replace("　", "")
                if clean: artist = db.query(Artist).filter(Artist.name.ilike(f"%{clean}%"), Artist.is_deleted == False).first()

            if artist and artist.image_filename:
                url = get_image_url(artist.image_filename)
                if url:
                    img = load_image(url)
                    if img:
                        img_fitted = ImageOps.fit(img, (SINGLE_COL_WIDTH, ROW_HEIGHT), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
                        row_img.paste(img_fitted, (0, 0))
                        has_image = True
        except Exception: pass

    # 黒フィルターの適用ロジック
    if has_image:
        # 画像がある場合: 指定した濃さの黒を重ねる
        overlay_color = (0, 0, 0, OVERLAY_OPACITY)
    else:
        # 画像がない場合: 背景を少し濃いグレーにする（デフォルト背景）
        # ※ここはお好みですが、画像なしの行も統一感を出すために設定
        overlay_color = (40, 40, 40, 230)

    overlay = Image.new('RGBA', (SINGLE_COL_WIDTH, ROW_HEIGHT), overlay_color)
    
    # 画像とフィルターを合成
    row_composite = Image.alpha_composite(row_img, overlay)
    
    # キャンバスに貼り付け
    canvas.paste(row_composite, (int(base_x), int(base_y)), row_composite)

    # ---------------------------------------------------------
    # 2. テキスト描画
    # ---------------------------------------------------------
    draw_centered_text(draw, time_str, base_x + AREA_TIME_X, base_y, AREA_TIME_W, ROW_HEIGHT, font_path, FONT_SIZE_TIME, align="left")
    draw_centered_text(draw, name_str, base_x + AREA_ARTIST_X, base_y, AREA_ARTIST_W, ROW_HEIGHT, font_path, FONT_SIZE_ARTIST, align="center")
    
    goods_info = "-"
    if goods_time:
        if " / " in goods_time:
            g_times = goods_time.split(" / ")
            g_places = goods_place.split(" / ") if goods_place else []
            fmt = []
            for idx, t in enumerate(g_times):
                p = g_places[idx] if idx < len(g_places) else (g_places[-1] if g_places else "")
                fmt.append(f"{t} ({p})" if p else t)
            goods_info = "\n".join(fmt)
        else:
            goods_info = f"{goods_time} ({goods_place})" if goods_place else goods_time
    draw_centered_text(draw, goods_info, base_x + AREA_GOODS_X, base_y, AREA_GOODS_W, ROW_HEIGHT, font_path, FONT_SIZE_GOODS, align="left")

def generate_timetable_image(timetable_data, font_path=None):
    if not timetable_data: return Image.new('RGBA', (WIDTH, ROW_HEIGHT), (0,0,0,255))
    
    # 完了メッセージだけシンプルに表示
    st.toast("画像生成完了！", icon="✅")
    
    from database import SessionLocal
    db = SessionLocal()

    try:
        half_idx = math.ceil(len(timetable_data) / 2)
        left_data = timetable_data[:half_idx]
        right_data = timetable_data[half_idx:]
        
        rows_in_column = max(len(left_data), len(right_data))
        if rows_in_column == 0: rows_in_column = 1
        total_height = rows_in_column * (ROW_HEIGHT + ROW_MARGIN)
        
        # 全体背景を透明で初期化
        canvas = Image.new('RGBA', (WIDTH, total_height), COLOR_BG_ALL)
        draw = ImageDraw.Draw(canvas)

        y = 0
        for row in left_data:
            draw_one_row(draw, canvas, 0, y, row, font_path, db)
            y += (ROW_HEIGHT + ROW_MARGIN)

        right_col_start_x = SINGLE_COL_WIDTH + COLUMN_GAP
        y = 0 
        for row in right_data:
            draw_one_row(draw, canvas, right_col_start_x, y, row, font_path, db)
            y += (ROW_HEIGHT + ROW_MARGIN)
            
        return canvas

    except Exception as e:
        st.error(f"エラー: {e}")
        return Image.new('RGBA', (WIDTH, ROW_HEIGHT), (255,0,0,255))
    finally:
        db.close()
