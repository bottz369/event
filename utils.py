import pandas as pd
import io
from datetime import datetime, timedelta
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from PIL import Image, ImageDraw, ImageFont

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
    # 元のコードにある calculate_timetable_flow の中身をすべてここに移動
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
    # 元のコードにある create_business_pdf の中身をすべてここに移動
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
