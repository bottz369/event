from PIL import Image, ImageDraw, ImageFont, ImageOps
import math
import os
import requests
from io import BytesIO
import streamlit as st

# ================= 設定エリア =================
# 1mm = 10px の高解像度で設定し、印刷時(300dpi等)に綺麗に出るようにします
CANVAS_HEIGHT = 2400       # 全体の高さ (240mm) 固定
COL1_CANVAS_WIDTH = 2800   # 1列モードの幅 (280mm)
COL2_CANVAS_WIDTH = 3600   # 2列モードの幅 (360mm)
COLUMN_GAP = 120           # 2列モード時の列と列の隙間

COLOR_BG_ALL = (0, 0, 0, 0)        # 背景透過
OVERLAY_OPACITY = 170              # 写真上の黒フィルターの濃さ
COLOR_TEXT = (255, 255, 255, 255)  # 文字色

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

def draw_one_row(draw, canvas, base_x, base_y, row_data, font_path, db, row_width, row_height, columns):
    time_str, name_str = row_data[0], str(row_data[1]).strip()
    goods_time, goods_place = row_data[2], row_data[3]

    # 行の高さに合わせてフォントサイズを動的に計算 (上限・下限を設定)
    font_size_artist = min(80, max(20, int(row_height * 0.45)))
    font_size_time = min(70, max(18, int(row_height * 0.40)))
    font_size_goods = min(50, max(15, int(row_height * 0.35)))

    # 列数に応じたエリア幅と座標の計算
    if columns == 1:
        time_w = int(row_width * 0.15)
        goods_w = int(row_width * 0.25)
        artist_w = row_width - time_w - goods_w - 80 
        
        time_x = 40
        artist_x = time_x + time_w
        goods_x = row_width - goods_w - 40
    else:
        time_w = int(row_width * 0.20)
        goods_w = int(row_width * 0.30)
        artist_w = row_width - time_w - goods_w - 40
        
        time_x = 20
        artist_x = time_x + time_w
        goods_x = row_width - goods_w - 20

    # ---------------------------------------------------------
    # 1. 画像処理 & 透過黒フィルター合成
    # ---------------------------------------------------------
    row_img = Image.new('RGBA', (int(row_width), int(row_height)), (0, 0, 0, 0))
    has_image = False

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
                        img_fitted = ImageOps.fit(img, (int(row_width), int(row_height)), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
                        row_img.paste(img_fitted, (0, 0))
                        has_image = True
        except Exception: pass

    if has_image:
        overlay_color = (0, 0, 0, OVERLAY_OPACITY)
    else:
        overlay_color = (40, 40, 40, 230)

    overlay = Image.new('RGBA', (int(row_width), int(row_height)), overlay_color)
    
    # 画像とフィルターを合成してキャンバスに貼り付け
    row_composite = Image.alpha_composite(row_img, overlay)
    canvas.paste(row_composite, (int(base_x), int(base_y)), row_composite)

    # ---------------------------------------------------------
    # 2. テキスト描画
    # ---------------------------------------------------------
    draw_centered_text(draw, time_str, base_x + time_x, base_y, time_w, row_height, font_path, font_size_time, align="left")
    draw_centered_text(draw, name_str, base_x + artist_x, base_y, artist_w, row_height, font_path, font_size_artist, align="center")
    
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
    draw_centered_text(draw, goods_info, base_x + goods_x, base_y, goods_w, row_height, font_path, font_size_goods, align="left")

def generate_timetable_image(timetable_data, font_path=None, columns=2):
    if not timetable_data: return Image.new('RGBA', (COL1_CANVAS_WIDTH, CANVAS_HEIGHT), (0,0,0,255))
    
    st.toast("画像生成完了！", icon="✅")
    
    from database import SessionLocal
    db = SessionLocal()

    try:
        total_artists = len(timetable_data)
        
        # 安全策: ロジック側でも24組以上は強制2列にする
        if total_artists >= 24:
            columns = 2

        if columns == 1:
            left_data = timetable_data
            right_data = []
            canvas_width = COL1_CANVAS_WIDTH
            rows_in_column = total_artists
        else:
            half_idx = math.ceil(total_artists / 2)
            left_data = timetable_data[:half_idx]
            right_data = timetable_data[half_idx:]
            canvas_width = COL2_CANVAS_WIDTH
            rows_in_column = max(len(left_data), len(right_data))

        if rows_in_column == 0: rows_in_column = 1
        
        # ---------------------------------------------------------
        # ★ 高さの自動調整ロジック
        # ---------------------------------------------------------
        margin_between_rows = 12  # 行と行の間の隙間(px)
        
        # キャンバス全体(2400px)を均等に割る
        slot_height = CANVAS_HEIGHT / rows_in_column
        # 実際に描画する高さは、割り当てられた高さからマージンを引いたもの
        row_height = max(10, int(slot_height - margin_between_rows))

        # キャンバス生成
        canvas = Image.new('RGBA', (canvas_width, CANVAS_HEIGHT), COLOR_BG_ALL)
        draw = ImageDraw.Draw(canvas)

        # 1列あたりの幅を計算
        if columns == 1:
            single_col_width = canvas_width
        else:
            single_col_width = int((canvas_width - COLUMN_GAP) / 2)

        # --- 左列の描画 ---
        y = margin_between_rows / 2
        for row in left_data:
            draw_one_row(draw, canvas, 0, y, row, font_path, db, single_col_width, row_height, columns)
            y += slot_height

        # --- 右列の描画 ---
        if columns == 2:
            right_col_start_x = single_col_width + COLUMN_GAP
            y = margin_between_rows / 2 
            for row in right_data:
                draw_one_row(draw, canvas, right_col_start_x, y, row, font_path, db, single_col_width, row_height, columns)
                y += slot_height
            
        return canvas

    except Exception as e:
        st.error(f"エラー: {e}")
        return Image.new('RGBA', (COL1_CANVAS_WIDTH, CANVAS_HEIGHT), (255,0,0,255))
    finally:
        db.close()
