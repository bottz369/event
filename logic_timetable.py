from PIL import Image, ImageDraw, ImageFont, ImageOps
import math
import os
import requests
from io import BytesIO

# ================= 設定エリア =================
SINGLE_COL_WIDTH = 1450     
COLUMN_GAP = 80             
WIDTH = (SINGLE_COL_WIDTH * 2) + COLUMN_GAP
ROW_HEIGHT = 130            
ROW_MARGIN = 12             

FONT_SIZE_TIME = 60         
FONT_SIZE_ARTIST = 60       
FONT_SIZE_GOODS = 48        

COLOR_BG_ALL = (0, 0, 0, 0)        
COLOR_ROW_BG = (0, 0, 0, 100)      
COLOR_TEXT = (255, 255, 255, 255)  

AREA_TIME_X = 20
AREA_TIME_W = 320 
AREA_ARTIST_X = 350
AREA_ARTIST_W = 650
AREA_GOODS_X = 1020
AREA_GOODS_W = 410

# ================= ヘルパー関数 =================

def get_font(path, size):
    try:
        if path and os.path.exists(path): return ImageFont.truetype(path, size)
        if os.path.exists("fonts/keifont.ttf"): return ImageFont.truetype("fonts/keifont.ttf", size)
        if os.path.exists("keifont.ttf"): return ImageFont.truetype("keifont.ttf", size)
    except: pass
    return ImageFont.load_default()

def load_image_from_url(url):
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        return Image.open(BytesIO(response.content)).convert("RGBA")
    except Exception as e:
        return None

def draw_centered_text(draw, text, box_x, box_y, box_w, box_h, font_path, max_font_size, align="center"):
    text = str(text).strip()
    if not text: return
    
    current_font_size = max_font_size
    font = get_font(font_path, current_font_size)
    min_font_size = 15
    
    while current_font_size > min_font_size:
        bbox = draw.multiline_textbbox((0, 0), text, font=font, spacing=4)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        if text_w <= (box_w - 10) and text_h <= (box_h - 4): break
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

# ★デバッグ用: 画像に文字を書く関数
def draw_debug_info(draw, text, x, y, color="red"):
    try:
        font = get_font(None, 20)
        draw.text((x, y), text, fill=color, font=font)
    except: pass

def draw_one_row(draw, canvas, base_x, base_y, row_data, font_path):
    time_str = row_data[0]
    name_str = str(row_data[1]).strip()
    goods_time = row_data[2]
    goods_place = row_data[3]

    # ---------------------------------------------------------
    # [レイヤー1] アーティスト写真描画 (診断モード)
    # ---------------------------------------------------------
    if name_str and name_str not in ["OPEN / START", "開演前物販", "終演後物販"]:
        try:
            from database import SessionLocal, Artist, get_image_url
            
            db = SessionLocal()
            try:
                # 1. 検索 (削除フラグも考慮)
                artist = db.query(Artist).filter(Artist.name == name_str, Artist.is_deleted == False).first()
                
                # 見つからない場合、あいまい検索
                if not artist:
                    clean_name = name_str.replace(" ", "").replace("　", "")
                    if clean_name:
                        artist = db.query(Artist).filter(Artist.name.ilike(f"%{clean_name}%"), Artist.is_deleted == False).first()

                if artist:
                    if artist.image_filename:
                        url = get_image_url(artist.image_filename)
                        if url:
                            img = load_image_from_url(url)
                            if img:
                                # ★成功時
                                img_fitted = ImageOps.fit(img, (SINGLE_COL_WIDTH, ROW_HEIGHT), method=Image.LANCZOS, centering=(0.5, 0.5))
                                canvas.paste(img_fitted, (int(base_x), int(base_y)))
                                # 青文字で成功を記録 (確認できたら消してください)
                                # draw_debug_info(draw, "OK", base_x + 10, base_y + 10, "cyan")
                            else:
                                # 画像DL失敗
                                draw_debug_info(draw, f"DL Error: {url[:30]}...", base_x + 10, base_y + 10, "red")
                        else:
                            # URL生成失敗
                            draw_debug_info(draw, "URL Gen Fail", base_x + 10, base_y + 10, "red")
                    else:
                        # DBにはいるが画像なし
                        draw_debug_info(draw, "No Image File", base_x + 10, base_y + 10, "yellow")
                else:
                    # DBにいない
                    draw_debug_info(draw, f"Not Found: {name_str}", base_x + 10, base_y + 10, "magenta")
            finally:
                db.close()
        except Exception as e:
            draw_debug_info(draw, f"Sys Error: {e}", base_x + 10, base_y + 10, "red")

    # ---------------------------------------------------------
    # [レイヤー2] 行全体の背景（半透明の黒）
    # ---------------------------------------------------------
    draw.rectangle([(base_x, base_y), (base_x + SINGLE_COL_WIDTH, base_y + ROW_HEIGHT)], fill=COLOR_ROW_BG)

    # ---------------------------------------------------------
    # [レイヤー3] テキスト情報
    # ---------------------------------------------------------
    draw_centered_text(draw, time_str, base_x + AREA_TIME_X, base_y, AREA_TIME_W, ROW_HEIGHT, font_path, FONT_SIZE_TIME, align="left")
    draw_centered_text(draw, name_str, base_x + AREA_ARTIST_X, base_y, AREA_ARTIST_W, ROW_HEIGHT, font_path, FONT_SIZE_ARTIST, align="center")
    
    goods_info = "-"
    if goods_time:
        if " / " in goods_time:
            g_times = goods_time.split(" / ")
            g_places = goods_place.split(" / ") if goods_place else []
            formatted_list = []
            for idx, t in enumerate(g_times):
                p = g_places[idx] if idx < len(g_places) else (g_places[-1] if g_places else "")
                formatted_list.append(f"{t} ({p})" if p else t)
            goods_info = "\n".join(formatted_list)
        else:
            goods_info = f"{goods_time} ({goods_place})" if goods_place else goods_time

    draw_centered_text(draw, goods_info, base_x + AREA_GOODS_X, base_y, AREA_GOODS_W, ROW_HEIGHT, font_path, FONT_SIZE_GOODS, align="left")

def generate_timetable_image(timetable_data, font_path=None):
    half_idx = math.ceil(len(timetable_data) / 2)
    left_data = timetable_data[:half_idx]
    right_data = timetable_data[half_idx:]
    rows_in_column = max(len(left_data), len(right_data))
    if rows_in_column == 0: rows_in_column = 1
    total_height = rows_in_column * (ROW_HEIGHT + ROW_MARGIN)
    canvas = Image.new('RGBA', (WIDTH, total_height), COLOR_BG_ALL)
    draw = ImageDraw.Draw(canvas)
    y = 0
    for row in left_data:
        draw_one_row(draw, canvas, 0, y, row, font_path)
        y += (ROW_HEIGHT + ROW_MARGIN)
    right_col_start_x = SINGLE_COL_WIDTH + COLUMN_GAP
    y = 0 
    for row in right_data:
        draw_one_row(draw, canvas, right_col_start_x, y, row, font_path)
        y += (ROW_HEIGHT + ROW_MARGIN)
    return canvas
