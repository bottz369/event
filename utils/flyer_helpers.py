import io
import os
import requests
import json
import pandas as pd
from datetime import datetime, date
from PIL import Image
from constants import FONT_DIR
from database import Asset, get_image_url

# ★追加: 共通のテキスト生成ロジックとヘルパーをインポート
# (get_day_of_week_jp, get_circled_number はここで定義せず共通のものを使います)
from utils.text_generator import build_event_summary_text, get_day_of_week_jp, get_circled_number

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
    
    # ★修正: 絶対パス化して安全性を確保
    abs_font_dir = os.path.abspath(FONT_DIR)
    os.makedirs(abs_font_dir, exist_ok=True)
    local_path = os.path.join(abs_font_dir, filename)
    
    if os.path.exists(local_path) and os.path.getsize(local_path) > 0:
        return local_path
    
    try:
        # DB (Assetテーブル) から検索
        asset = db.query(Asset).filter(Asset.image_filename == filename).first()
        if asset:
            url = get_image_url(asset.image_filename)
            if url:
                response = requests.get(url, timeout=10)
                if response.status_code == 200:
                    with open(local_path, "wb") as f:
                        f.write(response.content)
                    return local_path
        
        # ★追加: AssetFileテーブル (バイナリ保存) からも検索 (互換性のため)
        from database import AssetFile
        asset_file = db.query(AssetFile).filter(AssetFile.filename == filename).first()
        if asset_file and asset_file.file_data:
            with open(local_path, "wb") as f:
                f.write(asset_file.file_data)
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

# (削除済み: get_day_of_week_jp, get_circled_number は utils.text_generator からインポートして使用)

def generate_event_summary_text_from_proj(proj, tickets, notes):
    """
    告知用の概要テキストを生成
    DBデータ(proj)を整理して、共通ロジック(build_event_summary_text)に渡します。
    """
    try:
        # 1. タイムテーブルJSONからアーティストリストを抽出
        artists = []
        if proj.data_json:
            try:
                data = json.loads(proj.data_json)
                # JSONからアーティスト名を抽出し、除外キーワードを弾く
                temp_artists = []
                for d in data:
                    a = d.get("ARTIST", "")
                    if a and a not in ["開演前物販", "終演後物販", "調整中", ""]:
                        temp_artists.append(a)
                # リスト化（重複排除は共通ロジックでも行われるが、念のためここでも整理して渡す）
                artists = list(dict.fromkeys(temp_artists))
            except: pass

        # 2. 自由記述JSONの抽出
        free_texts = []
        if getattr(proj, "free_text_json", None):
            try:
                free_texts = json.loads(proj.free_text_json)
            except: pass

        # 3. 共通ロジックを呼び出してテキストを生成
        # ここで引数を渡すだけで、テキストの結合処理などは build_event_summary_text が行います
        return build_event_summary_text(
            title=proj.title or "",
            subtitle=getattr(proj, "subtitle", ""),
            date_val=proj.event_date,
            venue=getattr(proj, "venue_name", "") or getattr(proj, "venue", "") or "",
            url=getattr(proj, "venue_url", "") or getattr(proj, "url", "") or "",
            open_time=format_time_str(proj.open_time),
            start_time=format_time_str(proj.start_time),
            tickets=tickets,
            ticket_notes=notes,
            artists=artists,
            free_texts=free_texts
        )

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
