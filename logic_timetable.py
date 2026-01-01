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

# 全体の背景色（ダークグレー）
COLOR_BG_ALL = (50, 50, 50, 255)        

# ★変更点: 行の背景色を「完全透明 (0,0,0,0)」に設定しました
# これで画像の上に何も被さらなくなります
COLOR_ROW_BG = (0, 0, 0, 0)      

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
    """URLまたはローカルパスから画像を読み込む"""
    if not path_or_url: return None
    try:
        if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
            response = requests.get(path_or_url, timeout=10)
            if response.status_code != 200:
                return None
            return Image.open(BytesIO(response.content)).convert("RGBA")
        
        if os.path.exists(path_or_url):
             return Image.open(path_or_url).convert("RGBA")
        return None
    except Exception:
        return None

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
    draw.multiline_text((final_x, final_y), text, fill=COLOR_TEXT, font=font, spacing=4, align=align)

def draw_debug_msg(draw, text, x, y, color="red"):
    """デバッグメッセージを書き込む"""
    try:
        font = get_font(None, 30)
        # 背景をつけて読みやすくする
        bbox = draw.textbbox((x, y), text, font=font)
        draw.rectangle(bbox, fill="black")
        draw.text((x, y), text, fill=color, font=font)
    except: pass

def draw_one_row(draw, canvas, base_x, base_y, row_data, font_path, db):
    time_str, name_str = row_data[0], str(row_data[1]).strip()
    goods_time, goods_place = row_data[2], row_data[3]

    # 特殊行以外のみ画像処理
    if name_str and name_str not in ["OPEN / START", "開演前物販", "終演後物販"]:
        try:
            from database import Artist, get_image_url
            
            # 1. DB検索
            artist = db.query(Artist).filter(Artist.name == name_str, Artist.is_deleted == False).first()
            if not artist:
                clean = name_str.replace(" ", "").replace("　", "")
                if clean: artist = db.query(Artist).filter(Artist.name.ilike(f"%{clean}%"), Artist.is_deleted == False).first()

            if artist:
                if artist.image_filename:
                    # 2. URL取得
                    url = get_image_url(artist.image_filename)
                    if url:
                        # 3. 画像読み込み
                        img = load_image(url)
                        if img:
                            # ★成功: 画像を貼り付け
                            img_fitted = ImageOps.fit(img, (SINGLE_COL_WIDTH, ROW_HEIGHT), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
                            canvas.paste(img_fitted, (int(base_x), int(base_y)))
                            
                            # 確認用: 成功マーク
                            draw_debug_msg(draw, "OK", base_x + 10, base_y + 10, "#00FF00") 
                        else:
                            draw_debug_msg(draw, "LOAD ERROR", base_x + 10, base_y + 10, "red")
                    else:
                        draw_debug_msg(draw, "URL ERROR", base_x + 10, base_y + 10, "orange")
                else:
                    # DBにはあるがファイル名がない (正常)
                    pass
            else:
                # DBにない
                draw_debug_msg(draw, "DB MISSING", base_x + 10, base_y + 10, "magenta")
                
        except Exception as e:
            print(f"Error: {e}")
            draw_debug_msg(draw, "SYS ERROR", base_x + 10, base_y + 10, "red")

    # 背景(半透明黒)の描画
    # ★今回は透明度100%(COLOR_ROW_BG = (0,0,0,0))なので何も描画されません
    if COLOR_ROW_BG[3] > 0:
        draw.rectangle([(base_x, base_y), (base_x + SINGLE_COL_WIDTH, base_y + ROW_HEIGHT)], fill=COLOR_ROW_BG)

    # テキスト描画
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
    
    st.write("🔄 画像生成プロセス実行中 (透過テスト)...")
    
    from database import SessionLocal
    db = SessionLocal()

    try:
        half_idx = math.ceil(len(timetable_data) / 2)
        left_data = timetable_data[:half_idx]
        right_data = timetable_data[half_idx:]
        
        rows_in_column = max(len(left_data), len(right_data))
        if rows_in_column == 0: rows_in_column = 1
        total_height = rows_in_column * (ROW_HEIGHT + ROW_MARGIN)
        
        # 背景色: 全体はダークグレー
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
            
        st.write("✅ 生成完了")
        return canvas

    except Exception as e:
        st.error(f"全体エラー: {e}")
        return Image.new('RGBA', (WIDTH, ROW_HEIGHT), (255,0,0,255))
    finally:
        db.close()
