from PIL import Image, ImageDraw, ImageFont
import math
import os

# ================= 設定エリア =================
# 文字を大きく見やすくするための設定（サイズ拡大版）
SINGLE_COL_WIDTH = 1000     # 列の幅を少し広げました (900 -> 1000)
COLUMN_GAP = 60           
WIDTH = (SINGLE_COL_WIDTH * 2) + COLUMN_GAP
ROW_HEIGHT = 120            # 行の高さを広げました (80 -> 120)
ROW_MARGIN = 10

# フォントサイズ設定
FONT_SIZE_TIME = 38         # 時間 (36 -> 38)
FONT_SIZE_ARTIST = 55       # アーティスト名 (36 -> 55: これでかなり大きく見えます)
FONT_SIZE_GOODS = 32        # 物販情報 (24 -> 32)

# 色の設定
COLOR_BG_ALL = (0, 0, 0, 0)        
COLOR_ROW_BG = (0, 0, 0, 204)      # 黒の80%透過
COLOR_TEXT = (255, 255, 255, 255)  

# レイアウト調整 (座標設定)
TIME_COL_X = 40             # 時間の開始位置
ARTIST_COL_CENTER_X = 500   # アーティスト名の中心位置 (幅に合わせて調整)
ARTIST_MAX_WIDTH = 550      # アーティスト名が許容される最大幅
GOODS_COL_START_X = 780     # 物販情報の開始位置

def get_font(path, size):
    """フォント読み込みのヘルパー関数"""
    try:
        if path and os.path.exists(path):
            return ImageFont.truetype(path, size)
        # デフォルトフォントのフォールバック
        if os.path.exists("keifont.ttf"):
            return ImageFont.truetype("keifont.ttf", size)
    except:
        pass
    return ImageFont.load_default()

def draw_one_row(draw, base_x, base_y, row_data, font_path):
    """1行描画用サブ関数"""
    # 行の背景を描画
    draw.rectangle(
        [(base_x, base_y), (base_x + SINGLE_COL_WIDTH, base_y + ROW_HEIGHT)], 
        fill=COLOR_ROW_BG
    )

    time_str = row_data[0]
    name_str = row_data[1]
    goods_time = row_data[2]
    goods_place = row_data[3]
    
    # 各箇所のフォントをロード
    font_time = get_font(font_path, FONT_SIZE_TIME)
    font_artist = get_font(font_path, FONT_SIZE_ARTIST)
    font_goods = get_font(font_path, FONT_SIZE_GOODS)

    # --- 1. 時間 (左寄せ・上下中央) ---
    bbox = draw.textbbox((0, 0), time_str, font=font_time)
    text_h = bbox[3] - bbox[1]
    text_y = base_y + (ROW_HEIGHT - text_h) / 2 - 5 # 少し上に微調整
    draw.text((base_x + TIME_COL_X, text_y), time_str, fill=COLOR_TEXT, font=font_time)
    
    # --- 2. アーティスト (中央寄せ・自動縮小) ---
    current_font_size = FONT_SIZE_ARTIST
    current_font = font_artist
    
    # 幅に収まるまでループで小さくする処理
    while True:
        bbox = draw.textbbox((0, 0), name_str, font=current_font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        
        if text_w <= ARTIST_MAX_WIDTH or current_font_size <= 20:
            break
            
        current_font_size -= 2
        current_font = get_font(font_path, current_font_size)

    # センター配置の座標計算
    text_x = base_x + ARTIST_COL_CENTER_X - (text_w / 2)
    text_y = base_y + (ROW_HEIGHT - text_h) / 2 - 8 # アーティスト名は中心より少し上が見やすい
    
    draw.text((text_x, text_y), name_str, fill=COLOR_TEXT, font=current_font)
    
    # --- 3. 物販情報 (右側) ---
    goods_info = "-"
    if goods_time:
        # 「 / 」で区切られている場合は改行して表示
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
    
    # 物販情報の上下中央揃え
    # 複数行になっても中央に来るように計算
    bbox_g = draw.multiline_textbbox((0, 0), goods_info, font=font_goods, spacing=6)
    goods_h = bbox_g[3] - bbox_g[1]
    goods_y = base_y + (ROW_HEIGHT - goods_h) / 2 - 2
    
    draw.multiline_text(
        (base_x + GOODS_COL_START_X, goods_y), 
        goods_info, 
        fill=COLOR_TEXT, 
        font=font_goods, 
        spacing=6,
        align="left"
    )


def generate_timetable_image(timetable_data, font_path=None):
    """
    メイン関数: アプリからデータを受け取って画像を返す
    timetable_data: [["10:00-10:20", "ArtistA", "10:25-11:25", "A"], ...]
    font_path: アプリ側で選択されたフォントファイルのパス
    """
    
    # データを半分に分割 (左右2列レイアウト)
    half_idx = math.ceil(len(timetable_data) / 2)
    left_data = timetable_data[:half_idx]
    right_data = timetable_data[half_idx:]
    
    # 全体の高さを計算（データ量に応じて可変）
    rows_in_column = max(len(left_data), len(right_data))
    if rows_in_column == 0: rows_in_column = 1
    total_height = rows_in_column * (ROW_HEIGHT + ROW_MARGIN)
    
    # 透明背景のキャンバス作成
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
