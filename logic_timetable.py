from PIL import Image, ImageDraw, ImageFont, ImageOps
import math
import os
import requests
from io import BytesIO

# --- デバッグ用: インポート状況の確認 ---
print("--- logic_timetable.py 読み込み開始 ---")
try:
    from database import SessionLocal, Artist, get_image_url
    print("✅ database モジュールのインポートに成功しました")
except ImportError as e:
    print(f"❌ database モジュールのインポートに失敗しました: {e}")
    SessionLocal = None
    Artist = None
    get_image_url = None

# ================= 設定エリア =================

# 全体の解像度とサイズ感
SINGLE_COL_WIDTH = 1450     
COLUMN_GAP = 80             
WIDTH = (SINGLE_COL_WIDTH * 2) + COLUMN_GAP
ROW_HEIGHT = 130            
ROW_MARGIN = 12             

# フォントサイズ設定
FONT_SIZE_TIME = 60         
FONT_SIZE_ARTIST = 60       
FONT_SIZE_GOODS = 48        

# 色の設定
COLOR_BG_ALL = (0, 0, 0, 0)        # 全体の背景（透明）
COLOR_ROW_BG = (0, 0, 0, 210)      # 行の背景（透過黒）
COLOR_TEXT = (255, 255, 255, 255)  # 白文字

# レイアウトの境界線設定
AREA_TIME_X = 20
AREA_TIME_W = 320 
AREA_ARTIST_X = 350
AREA_ARTIST_W = 650
AREA_GOODS_X = 1020
AREA_GOODS_W = 410

# ================= ヘルパー関数 =================

def get_font(path, size):
    """フォント読み込み"""
    try:
        if path and os.path.exists(path):
            return ImageFont.truetype(path, size)
        if os.path.exists("fonts/keifont.ttf"):
            return ImageFont.truetype("fonts/keifont.ttf", size)
        if os.path.exists("keifont.ttf"):
            return ImageFont.truetype("keifont.ttf", size)
    except:
        pass
    return ImageFont.load_default()

def load_image_from_url(url):
    """URLから画像をダウンロードしてPIL Imageとして返す"""
    try:
        # print(f"ダウンロード開始: {url}") # デバッグ時はコメントアウト解除してもOK
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        return Image.open(BytesIO(response.content)).convert("RGBA")
    except Exception as e:
        print(f"❌ 画像ダウンロード失敗: {url}, エラー: {e}") 
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
        if text_w <= (box_w - 10) and text_h <= (box_h - 4):
            break
        current_font_size -= 2
        font = get_font(font_path, current_font_size)

    bbox = draw.multiline_textbbox((0, 0), text, font=font, spacing=4)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    final_y = box_y + (box_h - text_h) / 2

    if align == "center":
        final_x = box_x + (box_w - text_w) / 2
    elif align == "right":
        final_x = box_x + box_w - text_w
    else: 
        final_x = box_x

    draw.multiline_text((final_x, final_y), text, fill=COLOR_TEXT, font=font, spacing=4, align=align)


def draw_one_row(draw, canvas, base_x, base_y, row_data, font_path):
    """
    1行分の描画。
    レイヤー順: [最下層:アー写] -> [中間:半透明黒] -> [最上層:テキスト]
    """
    time_str = row_data[0]
    name_str = str(row_data[1]).strip() # ★重要: 空白除去
    goods_time = row_data[2]
    goods_place = row_data[3]

    # --- [レイヤー1] アーティスト写真の描画 ---
    
    # 実行条件のチェック（ログ出力）
    can_draw_image = False
    if SessionLocal and Artist and get_image_url:
        can_draw_image = True
    else:
        # 初回のみ警告を出すなどしてもよいが、ここでは毎回ログに出るのを避けるため何もしない
        pass

    if can_draw_image and name_str and name_str not in ["OPEN / START", "開演前物販", "終演後物販"]:
        db = SessionLocal()
        try:
            # DBからアーティストを検索
            artist = db.query(Artist).filter(Artist.name == name_str).first()
            
            if artist:
                if artist.image_filename:
                    # URLを取得
                    img_url = get_image_url(artist.image_filename)
                    # print(f"検索中: {name_str} -> {img_url}") 

                    if img_url:
                        # 画像をダウンロード
                        img = load_image_from_url(img_url)
                        
                        if img:
                            # 画像を枠のサイズに合わせて中央切り抜き
                            img_fitted = ImageOps.fit(
                                img, 
                                (SINGLE_COL_WIDTH, ROW_HEIGHT), 
                                method=Image.LANCZOS, 
                                centering=(0.5, 0.5)
                            )
                            
                            # ★修正: 座標を int にキャストしてから paste
                            paste_x = int(base_x)
                            paste_y = int(base_y)
                            canvas.paste(img_fitted, (paste_x, paste_y))
                            # print(f"✅ 画像貼り付け成功: {name_str}")
                        else:
                            print(f"⚠️ 画像データ取得失敗: {name_str} (URL: {img_url})")
                    else:
                        print(f"⚠️ 画像URL生成失敗: {name_str} (Filename: {artist.image_filename})")
                else:
                    # print(f"ℹ️ 画像ファイル名未登録: {name_str}")
                    pass
            else:
                print(f"⚠️ DBにアーティストが見つかりません: '{name_str}'")

        except Exception as e:
            print(f"❌ アー写処理エラー ({name_str}): {e}")
        finally:
            db.close()
    elif not can_draw_image:
         # インポート失敗している場合
         pass 

    # --- [レイヤー2] 行全体の背景（半透明の黒）を描画 ---
    draw.rectangle(
        [(base_x, base_y), (base_x + SINGLE_COL_WIDTH, base_y + ROW_HEIGHT)], 
        fill=COLOR_ROW_BG
    )

    # --- [レイヤー3] テキストの描画 ---
    draw_centered_text(
        draw, time_str, 
        base_x + AREA_TIME_X, base_y, AREA_TIME_W, ROW_HEIGHT, 
        font_path, FONT_SIZE_TIME, align="left"
    )
    
    draw_centered_text(
        draw, name_str, 
        base_x + AREA_ARTIST_X, base_y, AREA_ARTIST_W, ROW_HEIGHT, 
        font_path, FONT_SIZE_ARTIST, align="center"
    )
    
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
    メイン関数
    """
    half_idx = math.ceil(len(timetable_data) / 2)
    left_data = timetable_data[:half_idx]
    right_data = timetable_data[half_idx:]
    
    rows_in_column = max(len(left_data), len(right_data))
    if rows_in_column == 0: rows_in_column = 1
    total_height = rows_in_column * (ROW_HEIGHT + ROW_MARGIN)
    
    # キャンバス作成
    canvas = Image.new('RGBA', (WIDTH, total_height), COLOR_BG_ALL)
    draw = ImageDraw.Draw(canvas)

    # 左列を描画
    y = 0
    for row in left_data:
        draw_one_row(draw, canvas, 0, y, row, font_path)
        y += (ROW_HEIGHT + ROW_MARGIN)

    # 右列を描画
    right_col_start_x = SINGLE_COL_WIDTH + COLUMN_GAP
    y = 0 
    for row in right_data:
        draw_one_row(draw, canvas, right_col_start_x, y, row, font_path)
        y += (ROW_HEIGHT + ROW_MARGIN)

    return canvas
