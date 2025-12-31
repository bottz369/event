import pandas as pd
import io
import os
import json
import zipfile
from datetime import datetime, timedelta
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from PIL import Image, ImageDraw, ImageFont

# 定数とDBモデルのインポート
from constants import FONT_DIR
from database import get_db, Asset, FavoriteFont, SystemFontConfig

# =========================================================
# ユーティリティ関数群
# =========================================================

def safe_int(val, default=0):
    try:
        if pd.isna(val) or str(val).strip() == "" or str(val).lower() in ["nan", "none"]:
            return default
        return int(float(val))
    except:
        return default

def safe_str(val):
    if pd.isna(val) or val is None or str(val).lower() == "nan":
        return ""
    return str(val)

def add_minutes(time_str, minutes):
    try:
        t = datetime.strptime(str(time_str), "%H:%M")
        t += timedelta(minutes=int(minutes))
        return t.strftime("%H:%M")
    except:
        return str(time_str)

def get_duration_minutes(start_str, end_str):
    try:
        s = datetime.strptime(str(start_str), "%H:%M")
        e = datetime.strptime(str(end_str), "%H:%M")
        diff = e - s
        return int(diff.total_seconds() / 60)
    except:
        return 0

# =========================================================
# フォントプレビュー・画像生成関連
# =========================================================

def create_font_preview(text, font_path, size=50):
    """単一のフォントプレビュー画像を生成（素材管理ページ等のカード用）"""
    try:
        dummy_img = Image.new("RGBA", (10, 10), (0,0,0,0))
        dummy_draw = ImageDraw.Draw(dummy_img)
        try: font = ImageFont.truetype(font_path, size)
        except: font = ImageFont.load_default()
        
        bbox = dummy_draw.textbbox((0, 0), text, font=font)
        width = bbox[2] - bbox[0] + 40
        height = bbox[3] - bbox[1] + 40
        
        img = Image.new("RGBA", (width, height), (255, 255, 255, 0))
        draw = ImageDraw.Draw(img)
        x, y = 20, 10
        text_color = (255,255,255,255)
        for off_x in [-2, 0, 2]:
            for off_y in [-2, 0, 2]:
                draw.text((x+off_x, y+off_y), text, font=font, fill=(0,0,0))
        draw.text((x, y), text, font=font, fill=text_color)
        return img
    except Exception as e:
        return None

def get_sorted_font_list(db):
    """
    DBからフォント情報を取得し、以下の順序で並べ替えたリスト(辞書形式)を返す
    1. 標準フォント
    2. お気に入りフォント (登録順)
    3. その他のフォント (アルファベット -> 日本語順)
    
    Returns:
        [{"name": "表示名", "filename": "ファイル名", "type": "standard/fav/other"}, ...]
    """
    # 1. 全フォント取得
    all_fonts = db.query(Asset).filter(Asset.asset_type == "font", Asset.is_deleted == False).all()
    if not all_fonts: return []
    
    # 2. 設定情報の取得
    std_conf = db.query(SystemFontConfig).first()
    fav_fonts = db.query(FavoriteFont).all()
    
    std_filename = std_conf.filename if std_conf else None
    fav_filenames = [f.filename for f in fav_fonts]
    
    # 3. 分類
    std_item = None
    fav_items = []
    other_items = []
    
    # 重複防止用セット
    processed_files = set()
    
    # 標準フォントの特定
    if std_filename:
        found = next((f for f in all_fonts if f.image_filename == std_filename), None)
        if found:
            std_item = {"name": f"★ {found.name} (標準)", "filename": found.image_filename, "type": "standard"}
            processed_files.add(found.image_filename)
    
    # お気に入りフォントの特定 (標準と重複しないように)
    for fav_file in fav_filenames:
        if fav_file in processed_files: continue
        found = next((f for f in all_fonts if f.image_filename == fav_file), None)
        if found:
            fav_items.append({"name": f"⭐ {found.name}", "filename": found.image_filename, "type": "fav"})
            processed_files.add(found.image_filename)
            
    # その他のフォント
    temp_others = []
    for f in all_fonts:
        if f.image_filename not in processed_files:
            temp_others.append({"name": f.name, "filename": f.image_filename, "type": "other"})
            
    # その他のフォントをソート (Pythonの標準ソートで 英数字 -> 日本語 の順になる)
    temp_others.sort(key=lambda x: x["name"])
    
    # 結合
    result = []
    if std_item: result.append(std_item)
    result.extend(fav_items)
    result.extend(temp_others)
    
    return result

def create_font_specimen_img(session, font_assets):
    """
    フォント一覧見本画像を作成する関数
    
    Args:
        session: DBセッション (SystemFontConfig取得用)
        font_assets: Assetモデルのリスト、または辞書リスト({'name':..., 'filename':...})
                     ※ views/assets.py はモデルオブジェクト、grid/timetable は辞書を渡す可能性があるため両対応
    
    Returns:
        Imageオブジェクト
    """
    if not font_assets:
        # フォントがない場合は適当な空白画像を返す
        return Image.new("RGB", (800, 100), (255, 255, 255))

    # --- キャンバス設定 ---
    img_width = 800
    row_height = 80  # 1行の高さ
    margin = 20
    header_height = 40
    
    total_height = header_height + (len(font_assets) * row_height) + margin
    img = Image.new("RGB", (img_width, total_height), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    # --- ラベル描画用フォントの準備 ---
    # DBからシステムフォント設定を取得
    system_font_config = session.query(SystemFontConfig).first()
    label_font_path = os.path.join(FONT_DIR, "keifont.ttf") # デフォルト
    
    if system_font_config and system_font_config.filename:
        check_path = os.path.join(FONT_DIR, system_font_config.filename)
        if os.path.exists(check_path):
            label_font_path = check_path

    try:
        label_font_large = ImageFont.truetype(label_font_path, 20)
        label_font_small = ImageFont.truetype(label_font_path, 14)
    except OSError:
        label_font_large = ImageFont.load_default()
        label_font_small = ImageFont.load_default()

    # --- ヘッダー描画 ---
    draw.text((margin, 10), "Font List Specimen", fill=(50, 50, 50), font=label_font_large)
    draw.line((margin, header_height - 5, img_width - margin, header_height - 5), fill=(200, 200, 200), width=1)

    # --- 各フォントの描画 ---
    current_y = header_height

    for asset in font_assets:
        # ★重要: 入力が「辞書」か「DBモデル」かで値の取り方を変える
        if isinstance(asset, dict):
            # get_sorted_font_list から来た場合
            name = asset.get("name", "No Name")
            filename = asset.get("filename", "")
        else:
            # Assetモデルオブジェクトの場合
            name = asset.name if asset.name else "No Name"
            filename = asset.image_filename if asset.image_filename else ""

        # 1. 表示名 (黒)
        draw.text((margin, current_y + 15), str(name), fill="black", font=label_font_large)

        # 2. ファイル名 (グレー / 表示名の下)
        draw.text((margin, current_y + 45), str(filename), fill="gray", font=label_font_small)

        # 3. 見本テキスト (右側)
        preview_text = "ABC 123 あいう イベント"
        font_file_path = os.path.join(FONT_DIR, filename)
        
        preview_font_size = 32
        preview_font = None
        
        if os.path.exists(font_file_path):
            try:
                preview_font = ImageFont.truetype(font_file_path, preview_font_size)
            except Exception:
                preview_font = None
        
        # 見本描画エリア
        preview_x = 300
        preview_y = current_y + 20
        
        if preview_font:
            draw.text((preview_x, preview_y), preview_text, fill="black", font=preview_font)
        else:
            draw.text((preview_x, preview_y + 5), "Preview Not Available", fill="red", font=label_font_small)

        # 区切り線
        draw.line((margin, current_y + row_height - 1, img_width - margin, current_y + row_height - 1), fill=(230, 230, 230), width=1)
        
        current_y += row_height

    return img

# =========================================================
# タイムテーブル計算・PDF生成関連
# =========================================================

def calculate_timetable_flow(df, open_time, start_time):
    calculated_rows = []
    
    if open_time and start_time:
        calculated_rows.append({
            "TIME_DISPLAY": f"{open_time} - {start_time}",
            "ARTIST": "OPEN / START",
            "DURATION": 0, "ADJUSTMENT": 0,
            "GOODS_DISPLAY": "", "GOODS_START_MANUAL": "", "GOODS_DURATION": 0, "PLACE": "",
            "ADD_GOODS_START": "", "ADD_GOODS_DURATION": 0, "ADD_GOODS_PLACE": "",
            "RAW_START": open_time, "RAW_END": start_time,
        })

    current_time = start_time
    
    for _, row in df.iterrows():
        artist_name = row["ARTIST"]
        duration = safe_int(row["DURATION"], 0)
        adjustment = safe_int(row["ADJUSTMENT"], 0)
        
        if artist_name == "開演前物販":
            goods_start = safe_str(row["GOODS_START_MANUAL"])
            goods_dur = safe_int(row["GOODS_DURATION"], 0)
            goods_end = ""
            if goods_start and goods_dur > 0:
                goods_end = add_minutes(goods_start, goods_dur)
            main_goods_str = f"{goods_start} - {goods_end}" if goods_start else ""
            calculated_rows.append({
                "TIME_DISPLAY": "", "ARTIST": artist_name, "DURATION": 0, "ADJUSTMENT": 0,
                "GOODS_DISPLAY": main_goods_str, "PLACE": "", "GOODS_START_MANUAL": goods_start,
                "GOODS_DURATION": goods_dur, "PLACE_RAW": "", "ADD_GOODS_START": "", 
                "ADD_GOODS_DURATION": 0, "ADD_GOODS_PLACE": "", "RAW_START": "", "RAW_END": ""        
            })
            continue

        if artist_name == "終演後物販":
            goods_start = safe_str(row["GOODS_START_MANUAL"])
            goods_dur = safe_int(row["GOODS_DURATION"], 60)
            goods_end = ""
            if goods_start and goods_dur > 0:
                goods_end = add_minutes(goods_start, goods_dur)
            main_goods_str = f"{goods_start} - {goods_end}" if goods_start else ""
            calculated_rows.append({
                "TIME_DISPLAY": "", "ARTIST": artist_name, "DURATION": 0, "ADJUSTMENT": 0,
                "GOODS_DISPLAY": main_goods_str, "PLACE": "", "GOODS_START_MANUAL": goods_start,
                "GOODS_DURATION": goods_dur, "PLACE_RAW": "", "ADD_GOODS_START": "", 
                "ADD_GOODS_DURATION": 0, "ADD_GOODS_PLACE": "", "RAW_START": "", "RAW_END": ""        
            })
            continue

        end_time = add_minutes(current_time, duration)
        next_start_time = add_minutes(end_time, adjustment)
        
        is_post_goods = row.get("IS_POST_GOODS", False)
        
        final_goods_display = ""
        final_place_display = ""
        
        if is_post_goods:
            place = safe_str(row["PLACE"])
            final_goods_display = f"終演後物販 {place}" if place else "終演後物販"
            final_place_display = "" 
        else:
            goods_start = safe_str(row["GOODS_START_MANUAL"])
            goods_end = ""
            goods_dur = safe_int(row["GOODS_DURATION"], 60)
            if goods_start and goods_dur > 0:
                goods_end = add_minutes(goods_start, goods_dur)
            
            main_goods_str = f"{goods_start} - {goods_end}" if goods_start else ""
            main_place = safe_str(row["PLACE"])

            add_goods_start = safe_str(row.get("ADD_GOODS_START", ""))
            add_goods_dur = safe_int(row.get("ADD_GOODS_DURATION"), 60)
            add_goods_place = safe_str(row.get("ADD_GOODS_PLACE", ""))
            
            add_goods_str = ""
            if add_goods_start:
                add_goods_end = add_minutes(add_goods_start, add_goods_dur)
                add_goods_str = f"{add_goods_start} - {add_goods_end}"

            if main_goods_str and add_goods_str:
                final_goods_display = f"{main_goods_str} / {add_goods_str}"
                p1 = main_place if main_place else "-"
                p2 = add_goods_place if add_goods_place else "-"
                final_place_display = f"{p1} / {p2}"
            elif main_goods_str:
                final_goods_display = main_goods_str
                final_place_display = main_place
            elif add_goods_str:
                final_goods_display = add_goods_str
                final_place_display = add_goods_place

        calculated_rows.append({
            "TIME_DISPLAY": f"{current_time} - {end_time}", 
            "ARTIST": row["ARTIST"], "DURATION": duration, "ADJUSTMENT": adjustment,
            "GOODS_DISPLAY": final_goods_display, "PLACE": final_place_display,
            "GOODS_START_MANUAL": safe_str(row["GOODS_START_MANUAL"]),
            "GOODS_DURATION": safe_int(row["GOODS_DURATION"], 60),
            "PLACE_RAW": safe_str(row["PLACE"]), 
            "ADD_GOODS_START": safe_str(row.get("ADD_GOODS_START", "")),
            "ADD_GOODS_DURATION": safe_int(row.get("ADD_GOODS_DURATION"), 60),
            "ADD_GOODS_PLACE": safe_str(row.get("ADD_GOODS_PLACE", "")),
            "RAW_START": current_time, "RAW_END": end_time        
        })
        current_time = next_start_time

    return pd.DataFrame(calculated_rows)

def create_business_pdf(df, title, event_date, venue):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, title="Timetable")
    elements = []
    font_name = 'HeiseiKakuGo-W5'
    try: pdfmetrics.registerFont(UnicodeCIDFont(font_name))
    except: font_name = 'Helvetica'

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('Title', parent=styles['Title'], fontName=font_name, fontSize=18, spaceAfter=20)
    normal_style = ParagraphStyle('Normal', parent=styles['Normal'], fontName=font_name, fontSize=10)

    elements.append(Paragraph(f"イベント名: {title}", title_style))
    elements.append(Paragraph(f"日付: {event_date} / 会場: {venue}", normal_style))
    elements.append(Spacer(1, 20))

    table_data = [["時間", "出演アーティスト", "時間", "転換", "物販情報", "場所"]]
    for _, row in df.iterrows():
        goods_str = safe_str(row["GOODS_DISPLAY"]).replace(" / ", "\n")
        place_str = safe_str(row["PLACE"]).replace(" / ", "\n")
        dur = safe_int(row["DURATION"])
        adj = safe_int(row["ADJUSTMENT"])
        
        dur_str = str(dur) if dur > 0 else "-"
        adj_str = f"+{adj}" if adj > 0 else "-"
        if row["ARTIST"] in ["開演前物販", "終演後物販"]:
            dur_str = "-"
            adj_str = "-"

        table_data.append([
            row["TIME_DISPLAY"], row["ARTIST"], dur_str, adj_str, goods_str, place_str
        ])

    table = Table(table_data, colWidths=[90, 180, 40, 40, 90, 60])
    table.setStyle(TableStyle([
        ('FONT', (0, 0), (-1, -1), font_name),
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('PADDING', (0, 0), (-1, -1), 6),
    ]))
    elements.append(table)
    doc.build(elements)
    buffer.seek(0)
    return buffer

def create_event_summary_pdf(project):
    """プロジェクトのイベント概要PDFを作成する"""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, title="Event Summary")
    elements = []
    
    # フォント設定
    font_name = 'HeiseiKakuGo-W5'
    try: pdfmetrics.registerFont(UnicodeCIDFont(font_name))
    except: font_name = 'Helvetica'
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('Title', parent=styles['Title'], fontName=font_name, fontSize=20, spaceAfter=20)
    h2_style = ParagraphStyle('H2', parent=styles['Heading2'], fontName=font_name, fontSize=14, spaceAfter=10, spaceBefore=10)
    normal_style = ParagraphStyle('Normal', parent=styles['Normal'], fontName=font_name, fontSize=10, leading=14)

    # タイトル
    elements.append(Paragraph(f"【イベント概要】{safe_str(project.title)}", title_style))
    elements.append(Paragraph(f"日付: {safe_str(project.event_date)}", normal_style))
    elements.append(Paragraph(f"会場: {safe_str(project.venue_name)}", normal_style))
    if project.venue_url:
        elements.append(Paragraph(f"URL: {safe_str(project.venue_url)}", normal_style))
    elements.append(Spacer(1, 20))

    # チケット情報
    elements.append(Paragraph("■ チケット情報", h2_style))
    if project.tickets_json:
        tickets = json.loads(project.tickets_json)
        t_data = [["チケット名", "価格", "備考"]]
        for t in tickets:
            t_data.append([t.get("name",""), t.get("price",""), t.get("note","")])
        t_table = Table(t_data, colWidths=[150, 100, 200])
        t_table.setStyle(TableStyle([
            ('FONT', (0,0), (-1,-1), font_name),
            ('GRID', (0,0), (-1,-1), 0.5, colors.black),
            ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
            ('PADDING', (0,0), (-1,-1), 6),
        ]))
        elements.append(t_table)
    else:
        elements.append(Paragraph("なし", normal_style))
    
    elements.append(Spacer(1, 20))

    # 自由記述
    elements.append(Paragraph("■ その他情報", h2_style))
    if project.free_text_json:
        free_texts = json.loads(project.free_text_json)
        for ft in free_texts:
            elements.append(Paragraph(f"<b>{ft.get('title','')}</b>", normal_style))
            elements.append(Paragraph(ft.get('content',''), normal_style))
            elements.append(Spacer(1, 10))
    else:
        elements.append(Paragraph("なし", normal_style))

    doc.build(elements)
    buffer.seek(0)
    return buffer

def create_project_assets_zip(project, db, Asset):
    """プロジェクトに関連する素材（フライヤー設定で使用した画像）をZIPにする"""
    zip_buffer = io.BytesIO()
    
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        # 1. イベント概要PDF
        summary_pdf = create_event_summary_pdf(project)
        zf.writestr(f"event_summary_{project.id}.pdf", summary_pdf.getvalue())
        
        # 2. フライヤーで使用した素材画像 (簡易実装)
        if project.flyer_json:
            try:
                settings = json.loads(project.flyer_json)
                logo_id = settings.get("logo_id")
                bg_id = settings.get("bg_id")
                
                info_txt = f"Logo ID: {logo_id}\nBackground ID: {bg_id}"
                zf.writestr("flyer_assets_info.txt", info_txt)
            except:
                pass
        
        # 3. データJSON
        if project.data_json:
             zf.writestr("timetable_data.json", project.data_json)

    zip_buffer.seek(0)
    return zip_buffer
