from PIL import Image, ImageDraw, ImageFont, ImageOps
import math
import os
import requests
from io import BytesIO

# --- DB関連のインポート (失敗してもアプリを落とさない) ---
try:
    from database import SessionLocal, Artist, get_image_url
except ImportError:
    SessionLocal = None
    Artist = None
    get_image_url = None

# ================= 設定エリア =================
SINGLE_COL_WIDTH = 1450     
COLUMN_GAP = 80             
WIDTH = (SINGLE_COL_WIDTH * 2) + COLUMN_GAP
ROW_HEIGHT = 130            
ROW_MARGIN = 12             

FONT_SIZE_TIME = 60         
FONT_SIZE_ARTIST = 60       
FONT_SIZE_GOODS = 48        

COLOR_BG_ALL = (0, 0, 0, 0)        # 全体の背景（透明）
COLOR_ROW_BG = (0, 0, 0, 210)      # 行の背景（透過黒）
COLOR_TEXT = (255, 255, 255, 255)  # 白文字

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
    except:
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

def draw_one_row(draw, canvas, base_x, base_y, row_data, font_path):
    time_str = row_data[0]
    name_str = str(row_data[1]).strip()
    goods_time = row_data[2]
    goods_place = row_data[3]

    # ---------------------------------------------------------
    # [レイヤー1] アーティスト写真 (あれば表示、なければスキップ)
    # ---------------------------------------------------------
    # 特殊な行でなければ処理開始
    if name_str and name_str not in ["OPEN / START", "開演前物販", "終演後物販"]:
        # 必要な機能がインポートできているか確認
        if SessionLocal and Artist and get_image_url:
            db = None
            try:
                db = SessionLocal()
                # 1. DB検索
                artist = db.query(Artist).filter(Artist.name == name_str).first()
                
                # 2. アーティストがいて、かつ画像ファイル名を持っている場合のみ進む
                if artist and artist.image_filename:
                    url = get_image_url(artist.image_filename)
                    if url:
                        # 3. 画像ダウンロード
                        img = load_image_from_url(url)
                        if img:
                            # 4. 切り抜いて貼り付け
                            img_fitted = ImageOps.fit(
                                img, 
                                (SINGLE_COL_WIDTH, ROW_HEIGHT), 
                                method=Image.LANCZOS, 
                                centering=(0.5, 0.5)
                            )
                            # 座標を整数にして貼り付け
                            canvas.paste(img_fitted, (int(base_x), int(base_y)))
            except Exception:
                # ★ポイント: DBエラーや画像なしエラーが起きても、ここでは何もしない(pass)
                # これにより、処理が止まらずに次の「黒背景描画」へ進みます
                pass
            finally:
                if db: db.close()

    # ---------------------------------------------------------
    # [レイヤー2] 行全体の背景（半透明の黒）- 常に描画
    # ---------------------------------------------------------
    # アー写があってもなくても、ここを通るので必ず背景がつきます
    draw.rectangle(
        [(base_x, base_y), (base_x + SINGLE_COL_WIDTH, base_y + ROW_HEIGHT)], 
        fill=COLOR_ROW_BG
    )

    # ---------------------------------------------------------
    # [レイヤー3] テキスト情報 - 常に描画
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
