import io
import os
import requests
import json
import pandas as pd
from datetime import datetime, date
from PIL import Image
from constants import FONT_DIR
from database import Asset, get_image_url

# ==========================================
# 1. 画像・ファイルロード系ヘルパー
# ==========================================

def load_image_from_source(source):
    """URL、パス、またはPILオブジェクトから画像を読み込みRGBAに変換する"""
    if source is None: return None
    try:
        if isinstance(source, Image.Image): return source.convert("RGBA")
        if isinstance(source, str):
            if source.startswith("http"):
                response = requests.get(source, timeout=10)
                response.raise_for_status()
                return Image.open(io.BytesIO(response.content)).convert("RGBA")
            else:
                return Image.open(source).convert("RGBA")
        return Image.open(source).convert("RGBA")
    except Exception as e:
        print(f"Image Load Error: {e}")
        return None

def ensure_font_file_exists(db, filename):
    """ローカルにフォントがない場合、DBのAsset情報を参照してダウンロードする"""
    if not filename: return None
    local_path = os.path.join(FONT_DIR, filename)
    if os.path.exists(local_path):
        return local_path
    
    try:
        asset = db.query(Asset).filter(Asset.image_filename == filename).first()
        if asset:
            url = get_image_url(asset.image_filename)
            if url:
                response = requests.get(url, timeout=10)
                if response.status_code == 200:
                    # ディレクトリがない場合は作成
                    os.makedirs(FONT_DIR, exist_ok=True)
                    with open(local_path, "wb") as f:
                        f.write(response.content)
                    return local_path
    except Exception as e:
        print(f"Font download error: {e}")
    return None

def crop_center_to_a4(img):
    """画像をA4比率に合わせて中央でクロップする"""
    if not img: return None
    A4_RATIO = 1.4142
    img_w, img_h = img.size
    current_ratio = img_h / img_w
    if current_ratio > A4_RATIO:
        new_h = int(img_w * A4_RATIO)
        top = (img_h - new_h) // 2
        img = img.crop((0, top, img_w, top + new_h))
    else:
        new_w = int(img_h / A4_RATIO)
        left = (img_w - new_w) // 2
        img = img.crop((left, 0, left + new_w, img_h))
    return img

def resize_image_contain(img, max_w, max_h):
    """アスペクト比を維持して指定サイズ内に収める"""
    if not img: return None
    ratio = min(max_w / img.width, max_h / img.height)
    new_w = int(img.width * ratio)
    new_h = int(img.height * ratio)
    return img.resize((new_w, new_h), Image.LANCZOS)

def resize_image_to_width(img, target_width):
    """幅を指定してリサイズ"""
    if not img: return None
    w_percent = (target_width / float(img.size[0]))
    h_size = int((float(img.size[1]) * float(w_percent)))
    return img.resize((target_width, h_size), Image.LANCZOS)

# ==========================================
# 2. テキスト・データフォーマット系ヘルパー
# ==========================================

def format_event_date(dt_obj, mode="EN"):
    """日付をフライヤー用の文字列にフォーマット"""
    if not dt_obj: return ""
    target_date = dt_obj
    if isinstance(dt_obj, str):
        try:
            for fmt in ["%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"]:
                try:
                    target_date = datetime.strptime(dt_obj, fmt).date()
                    break
                except ValueError:
                    continue
        except:
            return str(dt_obj)
    try:
        if mode == "JP":
            weekdays_jp = ["月", "火", "水", "木", "金", "土", "日"]
            wd = weekdays_jp[target_date.weekday()]
            return f"{target_date.year}年{target_date.month}月{target_date.day}日 ({wd})"
        else:
            weekdays_en = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
            wd = weekdays_en[target_date.weekday()]
            return f"{target_date.year}.{target_date.month}.{target_date.day}.{wd}"
    except Exception:
        return str(dt_obj)

def format_time_str(t_val):
    if not t_val or t_val == 0 or t_val == "0": return ""
    if isinstance(t_val, str): return t_val[:5]
    try: return t_val.strftime("%H:%M")
    except: return str(t_val)

def get_day_of_week_jp(dt):
    if not dt: return ""
    w_list = ['(月)', '(火)', '(水)', '(木)', '(金)', '(土)', '(日)']
    try: return w_list[dt.weekday()]
    except: return ""

def get_circled_number(n):
    if 1 <= n <= 20: return chr(0x2460 + (n - 1))
    elif 21 <= n <= 35: return chr(0x3251 + (n - 21))
    elif 36 <= n <= 50: return chr(0x32B1 + (n - 36))
    else: return f"({n})"

def generate_event_summary_text_from_proj(proj, tickets, notes):
    """告知用の概要テキストを生成"""
    try:
        title = proj.title or ""
        date_val = proj.event_date
        venue = getattr(proj, "venue_name", "") or getattr(proj, "venue", "") or ""
        url = getattr(proj, "url", "") or "" 
        
        date_str = ""
        if date_val:
            if isinstance(date_val, str):
                try: date_val = datetime.strptime(date_val, "%Y-%m-%d").date()
                except: pass
            if isinstance(date_val, (date, datetime)):
                date_str = date_val.strftime("%Y年%m月%d日") + get_day_of_week_jp(date_val)
            else:
                date_str = str(date_val)

        open_t = format_time_str(proj.open_time) or "※調整中"
        start_t = format_time_str(proj.start_time) or "※調整中"

        text = f"【公演概要】\n{date_str}\n『{title}』\n\n■会場: {venue}"
        if url: text += f"\n {url}"
        text += f"\n\nOPEN▶{open_t}\nSTART▶{start_t}"

        text += "\n\n■チケット"
        if tickets:
            for t in tickets:
                name = t.get("name", "")
                price = t.get("price", "")
                note = t.get("note", "")
                line = f"- {name}: {price}"
                if note: line += f" ({note})"
                if name or price: text += "\n" + line
        else:
            text += "\n(情報なし)"

        if notes:
            text += "\n\n<備考>"
            for n in notes:
                if n and str(n).strip():
                    text += f"\n※{str(n).strip()}"

        # タイムテーブルデータ
        if proj.data_json:
            try:
                data = json.loads(proj.data_json)
                artists = []
                for d in data:
                    a = d.get("ARTIST", "")
                    if a and a not in ["開演前物販", "終演後物販", "調整中", ""] and a not in artists:
                        artists.append(a)
                if artists:
                    text += f"\n\n■出演者（{len(artists)}組予定）"
                    for i, a_name in enumerate(artists, 1):
                        c_num = get_circled_number(i)
                        text += f"\n{c_num}{a_name}"
            except: pass

        if getattr(proj, "free_text_json", None):
            try:
                free_list = json.loads(proj.free_text_json)
                for f in free_list:
                    ft = f.get("title", "")
                    fc = f.get("content", "")
                    if ft or fc:
                        text += f"\n\n■{ft}\n{fc}"
            except: pass

        return text
    except Exception as e:
        return f"テキスト生成エラー: {e}"

def generate_timetable_csv_string(proj):
    if not proj.data_json: return ""
    try:
        data = json.loads(proj.data_json)
        rows = []
        for d in data:
            row = {
                "START ": d.get("START", ""),
                "END": d.get("END", ""),
                "グループ名": d.get("ARTIST", ""),
                "持ち時間": d.get("DURATION", ""),
                "物販開始": d.get("GOODS_START", ""),
                "物販終了": d.get("GOODS_END", ""),
                "物販時間": d.get("GOODS_DURATION", ""),
                "物販場所": d.get("GOODS_LOC", "")
            }
            rows.append(row)
        
        df = pd.DataFrame(rows)
        cols = ["START ", "END", "グループ名", "持ち時間", "物販開始", "物販終了", "物販時間", "物販場所"]
        for c in cols:
            if c not in df.columns: df[c] = ""
            
        return df[cols].to_csv(index=False, encoding='utf-8_sig')
    except Exception as e:
        return f"CSV Error: {e}"
