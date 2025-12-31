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
from constants import FONT_DIR

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

def create_font_preview(text, font_path, size=50):
    """単一のフォントプレビュー画像を生成（素材管理ページ用）"""
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
                
                # 画像処理ロジック（Supabaseからのダウンロード等は省略し、情報のみ含める）
                info_txt = f"Logo ID: {logo_id}\nBackground ID: {bg_id}"
                zf.writestr("flyer_assets_info.txt", info_txt)
            except:
                pass
        
        # 3. データJSON
        if project.data_json:
             zf.writestr("timetable_data.json", project.data_json)

    zip_buffer.seek(0)
    return zip_buffer

# =========================================================
# ★修正: 文字化けしないフォント一覧画像生成
# =========================================================
def create_font_specimen_img(font_dir, font_list):
    """
    指定されたフォントリストの見本画像を生成する
    左側にファイル名(標準フォント)、右側にサンプル(対象フォント)を描画
    """
    if not font_list:
        return None

    # 設定
    row_height = 60
    margin_left = 20
    img_width = 800
    img_height = (row_height * len(font_list)) + 20
    text_sample = "あいう ABC 123" # 見本テキスト
    
    # 画像作成
    img = Image.new("RGB", (img_width, img_height), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    
    # ★重要: ファイル名を描画するための「読めるフォント」をロード
    # keifont.ttf があれば使い、なければデフォルトを使用
    label_font = None
    try:
        # FONT_DIR内の keifont.ttf を指定
        label_font = ImageFont.truetype(os.path.join(font_dir, "keifont.ttf"), 24)
    except:
        # 失敗したらデフォルト（これが文字化けの原因だが、keifontがあれば回避できる）
        label_font = ImageFont.load_default()

    y = 10
    for fname in font_list:
        font_path = os.path.join(font_dir, fname)
        
        # 1. 左側: ファイル名を描画 (読めるフォントで)
        draw.text((margin_left, y + 15), fname, font=label_font, fill=(50, 50, 50))

        # 2. 右側: そのフォントでのサンプル描画
        try:
            target_font = ImageFont.truetype(font_path, 32)
            draw.text((400, y + 10), text_sample, font=target_font, fill=(0, 0, 0))
        except:
            draw.text((400, y + 15), "Load Error", font=label_font, fill=(255, 0, 0))
            
        y += row_height
        
        # 区切り線
        draw.line((0, y, img_width, y), fill=(220, 220, 220), width=1)

    return img
