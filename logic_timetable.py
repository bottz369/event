from PIL import Image, ImageDraw, ImageFont
import math
import os

# ================= 設定エリア =================
# 全体の解像度とサイズ感
SINGLE_COL_WIDTH = 1100     # 片側の列の幅
COLUMN_GAP = 80             # 左右の列の間隔
WIDTH = (SINGLE_COL_WIDTH * 2) + COLUMN_GAP
ROW_HEIGHT = 130            # 1行の高さ
ROW_MARGIN = 12             # 行と行の間隔

# フォントサイズ設定 (枠に合わせて自動縮小されるため、最大値を指定)
FONT_SIZE_TIME = 38         
FONT_SIZE_ARTIST = 60       
FONT_SIZE_GOODS = 32        

# 色の設定
COLOR_BG_ALL = (0, 0, 0, 0)        # 全体の背景（透明）
COLOR_ROW_BG = (0, 0, 0, 210)      # 行の背景（半透明の黒）
COLOR_TEXT = (255, 255, 255, 255)  # 白文字

# ★レイアウトの境界線設定 (重なり防止のため、間隔を確保)
# [開始X座標, 幅]
# 1. 時間エリア (左端)
AREA_TIME_X = 30
AREA_TIME_W = 220 

# 2. アーティストエリア (真ん中・一番広い)
# 時間エリア(30+220=250)から少し間隔を空けてスタート
AREA_ARTIST_X = 270
AREA_ARTIST_W = 560

# 3. 物販・場所エリア (右端)
# アーティストエリア(270+560=830)から間隔を空けてスタート
AREA_GOODS_X = 850
AREA_GOODS_W = 220

def get_font(path, size):
    """フォント読み込みのヘルパー関数"""
    try:
        if path and os.path.exists(path):
            return ImageFont.truetype(path, size)
        if os.path.exists("keifont.ttf"):
            return ImageFont.truetype("keifont.ttf", size)
    except:
        pass
    return ImageFont.load_default()

def draw_centered_text(draw, text, box_x, box_y, box_w, box_h, font_path, max_font_size, align="center"):
    """指定されたボックス内に収まるように文字を描画する（自動縮小機能付き）"""
    text = str(text).strip()
    if not text: return

    current_font_size = max_font_size
    font = get_font(font_path, current_font_size)
    
    # 枠に収まるまでフォントサイズを小さくするループ
    min_font_size = 15 # 最小サイズ制限
    
    while current_font_size > min_font_size:
        # multiline_textbbox で複数行のサイズも考慮して計測
        bbox = draw.multiline_textbbox((0, 0), text, font=font, spacing=4)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        
        # 横幅も高さも収まっていればOK（パディングとして -10px の余裕を持たせる）
        if text_w <= (box_w - 10) and text_h <= (box_h - 4):
            break
        
        current_font_size -= 2
        font = get_font(font_path, current_font_size)

    # 最終的なサイズで座標計算
    bbox = draw.multiline_textbbox((0, 0), text, font=font, spacing=4)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    # 上下中央揃え
    final_y = box_y + (box_h - text_h) / 2

    # 左右揃え
    if align == "center":
        final_x = box_x + (box_w - text_w) / 2
    elif align == "right":
        final_x = box_x + box_w - text_w
    else: # left
        final_x = box_x

    draw.multiline_text((final_x, final_y), text, fill=COLOR_TEXT, font=font, spacing=4, align=align)


def draw_one_row(draw, base_x, base_y, row_data, font_path):
    """1行分の描画"""
    # 1. 行全体の背景（半透明の黒）を描画
    draw.rectangle(
        [(base_x, base_y), (base_x + SINGLE_COL_WIDTH, base_y + ROW_HEIGHT)], 
        fill=COLOR_ROW_BG
    )

    # データの取り出し
    time_str = row_data[0]
    name_str = row_data[1]
    goods_time = row_data[2]
    goods_place = row_data[3]

    # --- 1. 時間エリア ---
    draw_centered_text(
        draw, time_str, 
        base_x + AREA_TIME_X, base_y, AREA_TIME_W, ROW_HEIGHT, 
        font_path, FONT_SIZE_TIME, align="left"
    )
    
    # --- 2. アーティストエリア ---
    draw_centered_text(
        draw, name_str, 
        base_x + AREA_ARTIST_X, base_y, AREA_ARTIST_W, ROW_HEIGHT, 
        font_path, FONT_SIZE_ARTIST, align="center"
    )
    
    # --- 3. 物販情報エリア ---
    # 文字列の整形
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

    draw_centered_text(
        draw, goods_info, 
        base_x + AREA_GOODS_X, base_y, AREA_GOODS_W, ROW_HEIGHT, 
        font_path, FONT_SIZE_GOODS, align="left"
    )


def generate_timetable_image(timetable_data, font_path=None):
    """
    メイン関数: アプリからデータを受け取って画像を返す
    """
    # データを半分に分割 (左右2列レイアウト)
    half_idx = math.ceil(len(timetable_data) / 2)
    left_data = timetable_data[:half_idx]
    right_data = timetable_data[half_idx:]
    
    # 全体の高さを計算
    rows_in_column = max(len(left_data), len(right_data))
    if rows_in_column == 0: rows_in_column = 1
    total_height = rows_in_column * (ROW_HEIGHT + ROW_MARGIN)
    
    # キャンバス作成
    canvas = Image.new('RGBA', (WIDTH, total_height), COLOR_BG_ALL)
    draw = ImageDraw.Draw(canvas)

    # 左列を描画
    y = 0
    for row in left_data:
        draw_one_row(draw, 0, y, row, font_path)
        y += (ROW_HEIGHT + ROW_MARGIN)

    # 右列を描画
    right_col_start_x = SINGLE_COL_WIDTH + COLUMN_GAP
    y = 0 
    for row in right_data:
        draw_one_row(draw, right_col_start_x, y, row, font_path)
        y += (ROW_HEIGHT + ROW_MARGIN)

    return canvas
