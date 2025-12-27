from PIL import Image, ImageDraw, ImageFont
import math

# ================= 設定エリア =================
# ここで定義した変数は関数内から参照されます
FONT_PATH = "keifont.ttf"

# 基本サイズ設定
SINGLE_COL_WIDTH = 900    
COLUMN_GAP = 60           
WIDTH = (SINGLE_COL_WIDTH * 2) + COLUMN_GAP
ROW_HEIGHT = 80
ROW_MARGIN = 10
FONT_SIZE = 36

# 色の設定
COLOR_BG_ALL = (0, 0, 0, 0)        
COLOR_ROW_BG = (0, 0, 0, 204)      # 黒の80%透過
COLOR_TEXT = (255, 255, 255, 255)  

# レイアウト調整
ARTIST_COL_CENTER_X = 465  
ARTIST_MAX_WIDTH = 420
GOODS_COL_START_X = 680

def draw_one_row(draw, base_x, base_y, row_data, font_text, font_small):
    """1行描画用サブ関数"""
    # 行の背景
    draw.rectangle(
        [(base_x, base_y), (base_x + SINGLE_COL_WIDTH, base_y + ROW_HEIGHT)], 
        fill=COLOR_ROW_BG
    )

    time_str = row_data[0]
    name_str = row_data[1]
    goods_time = row_data[2]
    goods_place = row_data[3]
    
    # --- 物販情報の処理 ---
    text_y_offset = 25
    goods_info = "-"
    if goods_time:
        if " / " in goods_time:
            g_times = goods_time.split(" / ")
            g_places = goods_place.split(" / ") if goods_place else []
            formatted_list = []
            for idx, t in enumerate(g_times):
                if not g_places:
                    p = ""
                elif len(g_places) == 1:
                    p = g_places[0]
                elif idx < len(g_places):
                    p = g_places[idx]
                else:
                    p = g_places[-1]
                formatted_list.append(f"{t} ({p})" if p else t)
            goods_info = "\n".join(formatted_list)
            text_y_offset = 15
        else:
            goods_info = f"{goods_time} ({goods_place})" if goods_place else goods_time
    
    # --- 描画 ---
    # 1. 時間
    draw.text((base_x + 30, base_y + 20), time_str, fill=COLOR_TEXT, font=font_text)
    
    # 2. アーティスト（自動縮小）
    current_font_size = FONT_SIZE
    current_font = font_text
    while True:
        bbox = draw.textbbox((0, 0), name_str, font=current_font)
        text_w = bbox[2] - bbox[0]
        if text_w <= ARTIST_MAX_WIDTH or current_font_size <= 10:
            break
        current_font_size -= 2
        try:
            current_font = ImageFont.truetype(FONT_PATH, current_font_size)
        except:
            current_font = ImageFont.load_default()

    # 高さ調整（センター寄せ）
    original_h = 36 
    current_h = current_font_size
    y_adjust = (original_h - current_h) / 2

    text_x = base_x + ARTIST_COL_CENTER_X - (text_w / 2)
    draw.text((text_x, base_y + 20 + y_adjust), name_str, fill=COLOR_TEXT, font=current_font)
    draw.text((text_x + 1, base_y + 20 + y_adjust), name_str, fill=COLOR_TEXT, font=current_font)
    
    # 3. 物販情報
    draw.text((base_x + GOODS_COL_START_X, base_y + text_y_offset), goods_info, fill=COLOR_TEXT, font=font_small)


def generate_timetable_image(timetable_data):
    """
    メイン関数: アプリからデータを受け取って画像を返す
    timetable_data: [["10:00-10:20", "ArtistA", "10:25-11:25", "A"], ...]
    """
    
    # データを半分に分割
    half_idx = math.ceil(len(timetable_data) / 2)
    left_data = timetable_data[:half_idx]
    right_data = timetable_data[half_idx:]
    
    # 高さを計算（データ量に応じて可変）
    rows_in_column = max(len(left_data), len(right_data)) # 長い方に合わせる
    if rows_in_column == 0: rows_in_column = 1
    total_height = rows_in_column * (ROW_HEIGHT + ROW_MARGIN)
    
    # キャンバス作成
    canvas = Image.new('RGBA', (WIDTH, total_height), COLOR_BG_ALL)
    draw = ImageDraw.Draw(canvas)

    try:
        font_text = ImageFont.truetype(FONT_PATH, FONT_SIZE)
        font_small = ImageFont.truetype(FONT_PATH, 24)
    except:
        font_text = ImageFont.load_default()
        font_small = ImageFont.load_default()

    # 左列
    y = 0
    for row in left_data:
        draw_one_row(draw, 0, y, row, font_text, font_small)
        y += (ROW_HEIGHT + ROW_MARGIN)

    # 右列
    right_col_start_x = SINGLE_COL_WIDTH + COLUMN_GAP
    y = 0 
    for row in right_data:
        draw_one_row(draw, right_col_start_x, y, row, font_text, font_small)
        y += (ROW_HEIGHT + ROW_MARGIN)

    return canvas