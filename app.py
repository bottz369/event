import streamlit as st
import os
import pandas as pd
import json
import io
import time
import uuid
from datetime import datetime, timedelta, date

# database.pyから関数をインポート
from database import (
    init_db, get_db, SessionLocal, Artist, TimetableProject, FavoriteFont, 
    IMAGE_DIR, upload_image_to_supabase, get_image_url
)

# PDF/画像処理ライブラリ
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from PIL import Image, ImageDraw, ImageFont

# ドラッグ&ドロップ用ライブラリ
try:
    from streamlit_sortables import sort_items
except ImportError:
    sort_items = None

# ロジックファイルのインポート
try:
    from logic_timetable import generate_timetable_image
except ImportError:
    generate_timetable_image = None

try:
    from logic_grid import generate_grid_image
except ImportError:
    generate_grid_image = None

# --- 設定 ---
st.set_page_config(page_title="イベント画像生成アプリ", layout="wide")
init_db()

# --- 定数定義 ---
FONT_DIR = "fonts"
os.makedirs(FONT_DIR, exist_ok=True)

def get_time_options_1min():
    times = []
    for h in range(24):
        for m in range(60):
            times.append(f"{h:02d}:{m:02d}")
    return times

TIME_OPTIONS = get_time_options_1min()
DURATION_OPTIONS = list(range(0, 241))
ADJUSTMENT_OPTIONS = list(range(0, 61))
GOODS_DURATION_OPTIONS = list(range(5, 301, 5))
PLACE_OPTIONS = [chr(i) for i in range(65, 91)]

# --- ユーティリティ関数 ---
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
                "TIME_DISPLAY": "", 
                "ARTIST": artist_name,
                "DURATION": 0, "ADJUSTMENT": 0,
                "GOODS_DISPLAY": main_goods_str,
                "PLACE": "", 
                "GOODS_START_MANUAL": goods_start,
                "GOODS_DURATION": goods_dur,
                "PLACE_RAW": "",
                "ADD_GOODS_START": "", "ADD_GOODS_DURATION": 0, "ADD_GOODS_PLACE": "",
                "RAW_START": "", "RAW_END": ""        
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
                "TIME_DISPLAY": "", 
                "ARTIST": artist_name,
                "DURATION": 0, "ADJUSTMENT": 0,
                "GOODS_DISPLAY": main_goods_str,
                "PLACE": "", 
                "GOODS_START_MANUAL": goods_start,
                "GOODS_DURATION": goods_dur,
                "PLACE_RAW": "",
                "ADD_GOODS_START": "", "ADD_GOODS_DURATION": 0, "ADD_GOODS_PLACE": "",
                "RAW_START": "", "RAW_END": ""        
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
            "ARTIST": row["ARTIST"],
            "DURATION": duration, "ADJUSTMENT": adjustment,
            "GOODS_DISPLAY": final_goods_display,
            "PLACE": final_place_display,
            
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
            row["TIME_DISPLAY"],
            row["ARTIST"],
            dur_str,
            adj_str,
            goods_str,
            place_str
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

def get_default_row_settings():
    return {
        "ADJUSTMENT": 0,
        "GOODS_START_MANUAL": "",
        "GOODS_DURATION": 60,
        "PLACE": "A",
        "ADD_GOODS_START": "",
        "ADD_GOODS_DURATION": None,
        "ADD_GOODS_PLACE": "",
        "IS_POST_GOODS": False
    }

# ==========================================
# サイドバー & ナビゲーションガード
# ==========================================
st.sidebar.title("メニュー")

if "tt_unsaved_changes" not in st.session_state: st.session_state.tt_unsaved_changes = False
if "last_menu" not in st.session_state: st.session_state.last_menu = "プロジェクト"

# メニュー選択
menu_selection = st.sidebar.radio("機能を選択", ["プロジェクト", "タイムテーブル作成", "アー写グリッド作成", "アーティスト管理"], key="sb_menu")

# ナビゲーション戻し用コールバック
def revert_nav():
    st.session_state.sb_menu = st.session_state.last_menu

# ガードロジック
current_page = menu_selection

if st.session_state.tt_unsaved_changes and menu_selection != st.session_state.last_menu:
    st.warning("⚠️ タイムテーブル作成に未保存の変更があります！")
    
    col_nav1, col_nav2 = st.columns(2)
    with col_nav1:
        if st.button("変更を破棄して移動する"):
            st.session_state.tt_unsaved_changes = False
            st.session_state.last_menu = menu_selection
            st.rerun()
    with col_nav2:
        if st.button("キャンセル（元の画面に戻る）", on_click=revert_nav):
            st.rerun()
    
    current_page = st.session_state.last_menu
else:
    st.session_state.last_menu = menu_selection
    current_page = menu_selection


# ==========================================
# 1. プロジェクト管理機能 (新規追加)
# ==========================================
if current_page == "プロジェクト":
    st.title("📂 プロジェクト管理")
    db = next(get_db())
    
    tab_new, tab_list = st.tabs(["新規作成", "プロジェクト一覧"])
    
    # --- タブ1: 新規作成 ---
    with tab_new:
        st.subheader("新規プロジェクト作成")
        
        with st.form("new_project_form"):
            col_basic1, col_basic2 = st.columns(2)
            with col_basic1:
                p_date = st.date_input("開催日 (必須)", value=date.today())
                p_title = st.text_input("イベント名 (必須)")
            with col_basic2:
                p_venue = st.text_input("会場名 (必須)")
                p_url = st.text_input("会場URL")

            st.divider()
            st.markdown("##### 🎟️ チケット設定")
            # セッションステートで動的リスト管理
            if "new_tickets" not in st.session_state:
                st.session_state.new_tickets = [{"name": "", "price": "", "note": ""}]
            
            # チケット行のレンダリング
            for i, ticket in enumerate(st.session_state.new_tickets):
                c1, c2, c3 = st.columns([2, 1, 2])
                with c1: ticket["name"] = st.text_input(f"チケット名 {i+1}", value=ticket["name"], key=f"t_name_{i}")
                with c2: ticket["price"] = st.text_input(f"代金 {i+1}", value=ticket["price"], key=f"t_price_{i}")
                with c3: ticket["note"] = st.text_input(f"備考 {i+1}", value=ticket["note"], key=f"t_note_{i}")
            
            if st.form_submit_button("＋ チケット行を追加"):
                st.session_state.new_tickets.append({"name": "", "price": "", "note": ""})
                st.rerun()

            st.divider()
            st.markdown("##### 📝 自由入力情報")
            if "new_free_texts" not in st.session_state:
                st.session_state.new_free_texts = [{"title": "", "content": ""}]
            
            for i, ft in enumerate(st.session_state.new_free_texts):
                ft["title"] = st.text_input(f"タイトル {i+1}", value=ft["title"], key=f"ft_title_{i}")
                ft["content"] = st.text_area(f"内容 {i+1}", value=ft["content"], key=f"ft_content_{i}")
            
            if st.form_submit_button("＋ 自由入力セットを追加"):
                st.session_state.new_free_texts.append({"title": "", "content": ""})
                st.rerun()

            st.divider()
            # 保存ボタン
            if st.form_submit_button("保存して作成", type="primary"):
                if not p_title or not p_venue:
                    st.error("開催日、イベント名、会場名は必須です")
                else:
                    new_proj = TimetableProject(
                        title=p_title,
                        event_date=p_date.strftime("%Y-%m-%d"),
                        venue_name=p_venue,
                        venue_url=p_url,
                        tickets_json=json.dumps(st.session_state.new_tickets, ensure_ascii=False),
                        free_text_json=json.dumps(st.session_state.new_free_texts, ensure_ascii=False),
                        open_time="10:00", start_time="10:30" # デフォルト値
                    )
                    db.add(new_proj)
                    db.commit()
                    # フォームリセット
                    st.session_state.new_tickets = [{"name": "", "price": "", "note": ""}]
                    st.session_state.new_free_texts = [{"title": "", "content": ""}]
                    st.success("プロジェクトを作成しました！一覧タブで確認してください。")

    # --- タブ2: プロジェクト一覧 ---
    with tab_list:
        if "edit_proj_id" not in st.session_state: st.session_state.edit_proj_id = None

        projects = db.query(TimetableProject).all()
        # 日付順（新しい順）にソート
        projects.sort(key=lambda x: x.event_date or "0000-00-00", reverse=True)

        if not projects:
            st.info("プロジェクトがありません。「新規作成」タブから作成してください。")
        
        for proj in projects:
            # カード型レイアウト
            with st.container(border=True):
                # === 編集モード ===
                if st.session_state.edit_proj_id == proj.id:
                    st.caption(f"編集中: ID {proj.id}")
                    
                    # 基本情報
                    e_date = st.date_input("開催日", value=datetime.strptime(proj.event_date, "%Y-%m-%d").date() if proj.event_date else date.today(), key=f"e_date_{proj.id}")
                    e_title = st.text_input("イベント名", value=proj.title, key=f"e_title_{proj.id}")
                    e_venue = st.text_input("会場名", value=proj.venue_name, key=f"e_venue_{proj.id}")
                    e_url = st.text_input("会場URL", value=proj.venue_url or "", key=f"e_url_{proj.id}")
                    
                    st.divider()
                    
                    # --- チケット情報編集 ---
                    st.markdown("🎟️ **チケット情報**")
                    tickets_list = []
                    try:
                        if proj.tickets_json:
                            tickets_list = json.loads(proj.tickets_json)
                    except: tickets_list = []
                    
                    if not tickets_list:
                         tickets_list = [{"name":"", "price":"", "note":""}]

                    # データエディタで編集可能にする
                    tickets_df = pd.DataFrame(tickets_list)
                    edited_tickets = st.data_editor(
                        tickets_df, 
                        key=f"edit_tickets_{proj.id}", 
                        num_rows="dynamic", # 行の追加削除を許可
                        column_config={
                            "name": st.column_config.TextColumn("チケット名"),
                            "price": st.column_config.TextColumn("代金"),
                            "note": st.column_config.TextColumn("備考")
                        },
                        use_container_width=True
                    )

                    st.divider()

                    # --- 自由入力情報編集 ---
                    st.markdown("📝 **自由入力情報**")
                    free_list = []
                    try:
                        if proj.free_text_json:
                            free_list = json.loads(proj.free_text_json)
                    except: free_list = []
                    
                    if not free_list:
                        free_list = [{"title":"", "content":""}]

                    free_df = pd.DataFrame(free_list)
                    edited_free = st.data_editor(
                        free_df,
                        key=f"edit_free_{proj.id}",
                        num_rows="dynamic",
                        column_config={
                            "title": st.column_config.TextColumn("タイトル"),
                            "content": st.column_config.TextColumn("内容")
                        },
                        use_container_width=True
                    )
                    
                    st.divider()

                    col_save, col_can = st.columns(2)
                    with col_save:
                        if st.button("変更を保存", key=f"save_{proj.id}", type="primary"):
                            proj.event_date = e_date.strftime("%Y-%m-%d")
                            proj.title = e_title
                            proj.venue_name = e_venue
                            proj.venue_url = e_url
                            # データフレームを辞書リストに戻してJSON化
                            proj.tickets_json = json.dumps(edited_tickets.to_dict(orient="records"), ensure_ascii=False)
                            proj.free_text_json = json.dumps(edited_free.to_dict(orient="records"), ensure_ascii=False)
                            
                            db.commit()
                            st.session_state.edit_proj_id = None
                            st.success("更新しました")
                            st.rerun()
                    with col_can:
                        if st.button("キャンセル", key=f"cancel_{proj.id}"):
                            st.session_state.edit_proj_id = None
                            st.rerun()

                # === 通常表示モード ===
                else:
                    c1, c2 = st.columns([4, 1])
                    with c1:
                        st.subheader(f"{proj.event_date} : {proj.title}")
                        st.text(f"📍 {proj.venue_name}")
                        if proj.venue_url: st.markdown(f"[会場URL]({proj.venue_url})")
                        
                        # チケット情報の簡易表示
                        if proj.tickets_json:
                            try:
                                t_data = json.loads(proj.tickets_json)
                                if t_data:
                                    st.caption(f"チケット: {len(t_data)}種 設定あり")
                            except: pass
                    with c2:
                        if st.button("編集", key=f"edit_{proj.id}"):
                            st.session_state.edit_proj_id = proj.id
                            st.rerun()
                        if st.button("削除", key=f"del_{proj.id}"):
                            db.delete(proj)
                            db.commit()
                            st.rerun()
    db.close()

# ==========================================
# 2. タイムテーブル作成画面
# ==========================================
elif current_page == "タイムテーブル作成":
    st.title("⏱️ タイムテーブル作成")
    db = next(get_db())
    
    # ★エラー回避: 初期化処理
    if "tt_artists_order" not in st.session_state: st.session_state.tt_artists_order = []
    if "tt_artist_settings" not in st.session_state: st.session_state.tt_artist_settings = {}
    if "tt_row_settings" not in st.session_state: st.session_state.tt_row_settings = []
    if "tt_has_pre_goods" not in st.session_state: st.session_state.tt_has_pre_goods = False
    if "tt_pre_goods_settings" not in st.session_state: st.session_state.tt_pre_goods_settings = get_default_row_settings()
    if "tt_post_goods_settings" not in st.session_state: st.session_state.tt_post_goods_settings = get_default_row_settings()
    if "tt_editor_key" not in st.session_state: st.session_state.tt_editor_key = 0
    if "binding_df" not in st.session_state: st.session_state.binding_df = pd.DataFrame()
    if "rebuild_table_flag" not in st.session_state: st.session_state.rebuild_table_flag = True
    if "tt_title" not in st.session_state: st.session_state.tt_title = ""
    if "tt_event_date" not in st.session_state: st.session_state.tt_event_date = date.today()
    if "tt_venue" not in st.session_state: st.session_state.tt_venue = ""
    if "tt_open_time" not in st.session_state: st.session_state.tt_open_time = "10:00"
    if "tt_start_time" not in st.session_state: st.session_state.tt_start_time = "10:30"
    if "tt_goods_offset" not in st.session_state: st.session_state.tt_goods_offset = 5
    if "request_calc" not in st.session_state: st.session_state.request_calc = False


    # --- プロジェクト選択 (即時反映) ---
    projects = db.query(TimetableProject).all()
    # 日付が新しい順
    projects.sort(key=lambda x: x.event_date or "0000-00-00", reverse=True)
    
    proj_map = {f"{p.event_date} {p.title}": p.id for p in projects}
    options = ["(選択してください)"] + list(proj_map.keys())
    
    if "tt_current_proj_id" not in st.session_state: st.session_state.tt_current_proj_id = None
    
    # メニュー遷移しても選択状態を維持するためのインデックス計算
    index = 0
    if st.session_state.tt_current_proj_id:
        current_label = next((k for k, v in proj_map.items() if v == st.session_state.tt_current_proj_id), None)
        if current_label and current_label in options:
            index = options.index(current_label)

    selected_label = st.selectbox("プロジェクトを選択", options, index=index)
    
    if selected_label != "(選択してください)":
        selected_id = proj_map[selected_label]
        
        # IDが変わった場合のみロード（または初回）
        if st.session_state.tt_current_proj_id != selected_id:
            proj = db.query(TimetableProject).filter(TimetableProject.id == selected_id).first()
            if proj:
                st.session_state.tt_title = proj.title
                st.session_state.tt_event_date = datetime.strptime(proj.event_date, "%Y-%m-%d").date() if proj.event_date else date.today()
                st.session_state.tt_venue = proj.venue_name
                st.session_state.tt_open_time = proj.open_time or "10:00"
                st.session_state.tt_start_time = proj.start_time or "10:30"
                st.session_state.tt_goods_offset = proj.goods_start_offset if proj.goods_start_offset is not None else 5
                
                # データ展開
                if proj.data_json:
                    data = json.loads(proj.data_json)
                    new_order = []
                    new_artist_settings = {}
                    new_row_settings = []
                    st.session_state.tt_has_pre_goods = False
                    
                    for item in data:
                        name = item["ARTIST"]
                        if name == "開演前物販":
                            st.session_state.tt_has_pre_goods = True
                            st.session_state.tt_pre_goods_settings = {
                                "GOODS_START_MANUAL": safe_str(item.get("GOODS_START_MANUAL")),
                                "GOODS_DURATION": safe_int(item.get("GOODS_DURATION"), 60),
                                "PLACE": safe_str(item.get("PLACE")),
                            }
                            continue
                        if name == "終演後物販":
                            st.session_state.tt_post_goods_settings = {
                                "GOODS_START_MANUAL": safe_str(item.get("GOODS_START_MANUAL")),
                                "GOODS_DURATION": safe_int(item.get("GOODS_DURATION"), 60),
                                "PLACE": safe_str(item.get("PLACE")),
                            }
                            continue
                        
                        new_order.append(name)
                        new_artist_settings[name] = {"DURATION": safe_int(item.get("DURATION"), 20)}
                        new_row_settings.append({
                            "ADJUSTMENT": safe_int(item.get("ADJUSTMENT"), 0),
                            "GOODS_START_MANUAL": safe_str(item.get("GOODS_START_MANUAL")),
                            "GOODS_DURATION": safe_int(item.get("GOODS_DURATION"), 60),
                            "PLACE": safe_str(item.get("PLACE")),
                            "ADD_GOODS_START": safe_str(item.get("ADD_GOODS_START")),
                            "ADD_GOODS_DURATION": safe_int(item.get("ADD_GOODS_DURATION"), None),
                            "ADD_GOODS_PLACE": safe_str(item.get("ADD_GOODS_PLACE")),
                            "IS_POST_GOODS": bool(item.get("IS_POST_GOODS", False))
                        })
                    
                    st.session_state.tt_artists_order = new_order
                    st.session_state.tt_artist_settings = new_artist_settings
                    st.session_state.tt_row_settings = new_row_settings
                    st.session_state.rebuild_table_flag = True
                
                st.session_state.tt_current_proj_id = selected_id
                st.rerun()

    # --- CSVインポート ---
    def import_csv_callback():
        uploaded = st.session_state.get("csv_upload_key")
        if not uploaded: return
        try:
            uploaded.seek(0)
            try:
                df_csv = pd.read_csv(uploaded)
            except UnicodeDecodeError:
                uploaded.seek(0)
                df_csv = pd.read_csv(uploaded, encoding="cp932")
            
            df_csv.columns = [c.strip() for c in df_csv.columns]
            
            # 自動登録ロジック
            temp_db = SessionLocal()
            try:
                artists_to_check = []
                if "グループ名" in df_csv.columns:
                    artists_to_check = [str(row.get("グループ名", "")).strip() for _, row in df_csv.iterrows()]
                else:
                    artist_col = next((c for c in df_csv.columns if c.lower() == "artist"), None)
                    if not artist_col: artist_col = df_csv.columns[0]
                    artists_to_check = [str(row[artist_col]).strip() for _, row in df_csv.iterrows()]
                
                artists_to_check = list(set([a for a in artists_to_check if a and a != "nan"]))

                for artist_name in artists_to_check:
                    existing = temp_db.query(Artist).filter(Artist.name == artist_name).first()
                    if not existing:
                        new_artist = Artist(name=artist_name, image_filename=None)
                        temp_db.add(new_artist)
                temp_db.commit()
            except Exception as e:
                print(f"Auto reg error: {e}")
            finally:
                temp_db.close()
            
            # 読み込み処理
            new_order = []
            new_artist_settings = {}
            new_row_settings = []
            
            if "グループ名" in df_csv.columns:
                for i, row in df_csv.iterrows():
                    name = str(row.get("グループ名", ""))
                    if name == "nan" or not name: continue 
                    duration = safe_int(row.get("持ち時間"), 20)
                    adjustment = 0
                    if i < len(df_csv) - 1:
                        current_end = str(row.get("END", "")).strip()
                        next_start = str(df_csv.iloc[i+1].get("START", "")).strip()
                        if current_end and next_start:
                            adjustment = get_duration_minutes(current_end, next_start)
                            if adjustment < 0: adjustment = 0
                    
                    new_order.append(name)
                    new_artist_settings[name] = {"DURATION": duration}
                    new_row_settings.append({
                        "ADJUSTMENT": adjustment,
                        "GOODS_START_MANUAL": safe_str(row.get("物販開始")),
                        "GOODS_DURATION": safe_int(row.get("物販時間"), 60),
                        "PLACE": safe_str(row.get("物販場所", "A")),
                        "ADD_GOODS_START": "", "ADD_GOODS_DURATION": None, "ADD_GOODS_PLACE": "",
                        "IS_POST_GOODS": False
                    })
            else:
                for _, row in df_csv.iterrows():
                    artist_col = next((c for c in df_csv.columns if c.lower() == "artist"), None)
                    if not artist_col: artist_col = df_csv.columns[0]
                    name = str(row[artist_col])
                    if name == "nan": continue
                    new_order.append(name)
                    new_artist_settings[name] = {"DURATION": safe_int(row.get('Duration'), 20)}
                    new_row_settings.append({
                        "ADJUSTMENT": safe_int(row.get('Adjustment'), 0),
                        "GOODS_START_MANUAL": safe_str(row.get('GoodsStart')),
                        "GOODS_DURATION": safe_int(row.get('GoodsDuration'), 60),
                        "PLACE": safe_str(row.get('Place', "A")),
                        "ADD_GOODS_START": safe_str(row.get('AddGoodsStart')),
                        "ADD_GOODS_DURATION": safe_int(row.get('AddGoodsDuration'), None),
                        "ADD_GOODS_PLACE": safe_str(row.get('AddGoodsPlace')),
                        "IS_POST_GOODS": bool(row.get('IS_POST_GOODS', False))
                    })

            st.session_state.tt_artists_order = new_order
            st.session_state.tt_artist_settings = new_artist_settings
            st.session_state.tt_row_settings = new_row_settings
            st.session_state.rebuild_table_flag = True 
            st.session_state.tt_unsaved_changes = True
            
            st.success("CSVを読み込み、未登録アーティストを自動登録しました")
        except Exception as e:
            st.error(f"エラー: {e}")

    def force_sync():
        st.session_state.tt_unsaved_changes = True 
    def mark_dirty():
        st.session_state.tt_unsaved_changes = True

    # --- UI描画 ---
    if st.session_state.tt_current_proj_id:
        st.divider()
        col_b1, col_b2, col_b3 = st.columns(3)
        with col_b1:
            st.text_input("イベント名", key="tt_title", on_change=mark_dirty)
            st.date_input("開催日", key="tt_event_date", on_change=mark_dirty)
            
            c_off1, c_off2 = st.columns([2, 1])
            with c_off1:
                st.number_input("物販開始タイミング（出番終了後〇〇分）", min_value=0, key="tt_goods_offset", on_change=mark_dirty)
            with c_off2:
                st.write("")
                st.write("")
                if st.button("🔄 反映"):
                    st.session_state.request_calc = True
                    mark_dirty()

        with col_b2:
            st.text_input("会場名", key="tt_venue", on_change=mark_dirty)
        with col_b3:
            st.selectbox("開場時間", TIME_OPTIONS, key="tt_open_time", on_change=mark_dirty)
            st.selectbox("開演時間", TIME_OPTIONS, key="tt_start_time", on_change=mark_dirty)
        
        with st.expander("📂 CSV読込"):
            st.file_uploader("CSV", key="csv_upload_key")
            st.button("反映", on_click=import_csv_callback)

        st.divider()

        # --- エディタとロジック (既存コードを移植) ---
        col_ui_left, col_ui_right = st.columns([1, 2.5])
        
        with col_ui_left:
            st.subheader("出演順")
            all_artists = db.query(Artist).filter(Artist.is_deleted == False).all()
            all_artists.sort(key=lambda x: x.name)
            available_to_add = [a.name for a in all_artists if a.name not in st.session_state.tt_artists_order]
            
            c_add1, c_add2 = st.columns([3, 1])
            with c_add1:
                new_artist = st.selectbox("追加", [""] + available_to_add, label_visibility="collapsed")
            with c_add2:
                if st.button("＋"):
                    if new_artist:
                        st.session_state.tt_artists_order.append(new_artist)
                        st.session_state.tt_artist_settings[new_artist] = {"DURATION": 20}
                        st.session_state.tt_row_settings.append(get_default_row_settings())
                        st.session_state.rebuild_table_flag = True 
                        mark_dirty()
                        st.rerun()

            st.caption("ドラッグ&ドロップ")
            if sort_items:
                sorted_items = sort_items(st.session_state.tt_artists_order, direction="vertical")
                if sorted_items != st.session_state.tt_artists_order:
                    st.session_state.tt_artists_order = sorted_items
                    st.session_state.rebuild_table_flag = True
                    mark_dirty()
                    st.rerun()
            
            st.caption("削除")
            del_target = st.selectbox("削除対象", ["(選択なし)"] + st.session_state.tt_artists_order)
            if del_target != "(選択なし)":
                if st.button("削除実行"):
                    idx = st.session_state.tt_artists_order.index(del_target)
                    st.session_state.tt_artists_order.pop(idx)
                    del st.session_state.tt_artist_settings[del_target]
                    st.session_state.tt_row_settings.pop(idx)
                    st.session_state.rebuild_table_flag = True
                    mark_dirty()
                    st.rerun()

        with col_ui_right:
            st.subheader("詳細設定")
            if st.checkbox("開演前物販", value=st.session_state.tt_has_pre_goods, on_change=mark_dirty):
                if not st.session_state.tt_has_pre_goods:
                    st.session_state.tt_has_pre_goods = True; st.session_state.rebuild_table_flag = True; st.rerun()
            else:
                if st.session_state.tt_has_pre_goods:
                    st.session_state.tt_has_pre_goods = False; st.session_state.rebuild_table_flag = True; st.rerun()

            # --- テーブル再構築ロジック ---
            column_order = ["ARTIST", "DURATION", "IS_POST_GOODS", "ADJUSTMENT", "GOODS_START_MANUAL", "GOODS_DURATION", "PLACE", "ADD_GOODS_START", "ADD_GOODS_DURATION", "ADD_GOODS_PLACE"]
            
            if st.session_state.rebuild_table_flag:
                rows = []
                if st.session_state.tt_has_pre_goods:
                    p = st.session_state.tt_pre_goods_settings
                    rows.append({"ARTIST": "開演前物販", "DURATION":0, "ADJUSTMENT":0, "IS_POST_GOODS":False, 
                                 "GOODS_START_MANUAL": safe_str(p.get("GOODS_START_MANUAL")), 
                                 "GOODS_DURATION": safe_int(p.get("GOODS_DURATION"), 60), "PLACE": "", 
                                 "ADD_GOODS_START":"", "ADD_GOODS_DURATION":None, "ADD_GOODS_PLACE":""})
                
                while len(st.session_state.tt_row_settings) < len(st.session_state.tt_artists_order):
                    st.session_state.tt_row_settings.append(get_default_row_settings())

                has_post = False
                for i, name in enumerate(st.session_state.tt_artists_order):
                    ad = st.session_state.tt_artist_settings.get(name, {"DURATION": 20})
                    rd = st.session_state.tt_row_settings[i]
                    is_p = bool(rd.get("IS_POST_GOODS", False))
                    if is_p: has_post = True
                    rows.append({
                        "ARTIST": name, "DURATION": safe_int(ad.get("DURATION"), 20), "IS_POST_GOODS": is_p,
                        "ADJUSTMENT": safe_int(rd.get("ADJUSTMENT"), 0),
                        "GOODS_START_MANUAL": safe_str(rd.get("GOODS_START_MANUAL")),
                        "GOODS_DURATION": safe_int(rd.get("GOODS_DURATION"), 60), "PLACE": safe_str(rd.get("PLACE")),
                        "ADD_GOODS_START": safe_str(rd.get("ADD_GOODS_START")), 
                        "ADD_GOODS_DURATION": safe_int(rd.get("ADD_GOODS_DURATION"), None), 
                        "ADD_GOODS_PLACE": safe_str(rd.get("ADD_GOODS_PLACE"))
                    })
                
                if has_post:
                    p = st.session_state.tt_post_goods_settings
                    rows.append({"ARTIST": "終演後物販", "DURATION":0, "ADJUSTMENT":0, "IS_POST_GOODS":False,
                                 "GOODS_START_MANUAL": safe_str(p.get("GOODS_START_MANUAL")), 
                                 "GOODS_DURATION": safe_int(p.get("GOODS_DURATION"), 60), "PLACE": "",
                                 "ADD_GOODS_START":"", "ADD_GOODS_DURATION":None, "ADD_GOODS_PLACE":""})

                st.session_state.binding_df = pd.DataFrame(rows, columns=column_order)
                st.session_state.tt_editor_key = st.session_state.get("tt_editor_key", 0) + 1
                st.session_state.rebuild_table_flag = False

            # --- Data Editor ---
            edited_df = pd.DataFrame(columns=column_order)
            if not st.session_state.binding_df.empty:
                current_key = f"tt_editor_{st.session_state.tt_editor_key}"
                # セッションからデータフレームを復元（リロード対策）
                if current_key in st.session_state:
                    if isinstance(st.session_state[current_key], pd.DataFrame):
                        st.session_state.binding_df = st.session_state[current_key]

                edited_df = st.data_editor(
                    st.session_state.binding_df, key=current_key, num_rows="fixed", use_container_width=True,
                    column_config={
                        "ARTIST": st.column_config.TextColumn("アーティスト", disabled=True),
                        "DURATION": st.column_config.SelectboxColumn("出演", options=DURATION_OPTIONS, width="small"),
                        "IS_POST_GOODS": st.column_config.CheckboxColumn("終演後", width="small"),
                        "ADJUSTMENT": st.column_config.SelectboxColumn("転換", options=ADJUSTMENT_OPTIONS, width="small"),
                        "GOODS_START_MANUAL": st.column_config.SelectboxColumn("物販開始", options=[""]+TIME_OPTIONS, width="small"),
                        "GOODS_DURATION": st.column_config.SelectboxColumn("物販分", options=GOODS_DURATION_OPTIONS, width="small"),
                        "PLACE": st.column_config.SelectboxColumn("場所", options=[""]+PLACE_OPTIONS, width="small"),
                        "ADD_GOODS_START": st.column_config.SelectboxColumn("追加開始", options=[""]+TIME_OPTIONS, width="small"),
                        "ADD_GOODS_DURATION": st.column_config.SelectboxColumn("追加分", options=GOODS_DURATION_OPTIONS, width="small"),
                        "ADD_GOODS_PLACE": st.column_config.SelectboxColumn("追加場所", options=[""]+PLACE_OPTIONS, width="small"),
                    },
                    hide_index=True, on_change=force_sync
                )

                # --- 編集結果の反映 ---
                new_row_settings_from_edit = []
                current_has_post_check = False
                for i, row in edited_df.iterrows():
                    name = row["ARTIST"]
                    is_post = bool(row.get("IS_POST_GOODS", False))
                    
                    if name == "開演前物販":
                        dur = get_duration_minutes(st.session_state.tt_open_time, st.session_state.tt_start_time)
                        st.session_state.tt_pre_goods_settings = {"GOODS_START_MANUAL": st.session_state.tt_open_time, "GOODS_DURATION": dur, "PLACE": ""}
                        continue
                    if name == "終演後物販":
                        st.session_state.tt_post_goods_settings = {"GOODS_START_MANUAL": safe_str(row["GOODS_START_MANUAL"]), "GOODS_DURATION": safe_int(row["GOODS_DURATION"], 60), "PLACE": ""}
                        continue
                    
                    if is_post: current_has_post_check = True
                    st.session_state.tt_artist_settings[name] = {"DURATION": safe_int(row["DURATION"], 20)}
                    
                    g_start = safe_str(row["GOODS_START_MANUAL"])
                    g_dur = safe_int(row["GOODS_DURATION"], 60)
                    add_start = safe_str(row["ADD_GOODS_START"])
                    add_dur = safe_int(row["ADD_GOODS_DURATION"], None)
                    add_place = safe_str(row["ADD_GOODS_PLACE"])
                    
                    if is_post: # 終演後物販モードなら個別設定はクリア
                        g_start = ""; g_dur = 60; add_start = ""; add_dur = None; add_place = ""

                    new_row_settings_from_edit.append({
                        "ADJUSTMENT": safe_int(row["ADJUSTMENT"], 0),
                        "GOODS_START_MANUAL": g_start, "GOODS_DURATION": g_dur, "PLACE": safe_str(row["PLACE"]),
                        "ADD_GOODS_START": add_start, "ADD_GOODS_DURATION": add_dur, "ADD_GOODS_PLACE": add_place,
                        "IS_POST_GOODS": is_post
                    })
                
                if len(new_row_settings_from_edit) == len(st.session_state.tt_artists_order):
                    st.session_state.tt_row_settings = new_row_settings_from_edit
                
                # 終演後物販行の有無チェック
                row_exists = any(r["ARTIST"] == "終演後物販" for r in st.session_state.binding_df.to_dict("records"))
                if (current_has_post_check and not row_exists) or (not current_has_post_check and row_exists):
                    st.session_state.rebuild_table_flag = True; mark_dirty(); st.rerun()

                # 自動計算ロジック
                if st.session_state.request_calc:
                    curr = datetime.strptime(st.session_state.tt_start_time, "%H:%M")
                    for i, name in enumerate(st.session_state.tt_artists_order):
                        if i >= len(st.session_state.tt_row_settings): break
                        rd = st.session_state.tt_row_settings[i]
                        dur = st.session_state.tt_artist_settings[name].get("DURATION", 20)
                        
                        end_obj = curr + timedelta(minutes=dur)
                        if not rd.get("IS_POST_GOODS", False):
                            g_start_obj = end_obj + timedelta(minutes=st.session_state.tt_goods_offset)
                            rd["GOODS_START_MANUAL"] = g_start_obj.strftime("%H:%M")
                            st.session_state.tt_row_settings[i] = rd
                        
                        curr = end_obj + timedelta(minutes=rd.get("ADJUSTMENT", 0))
                    
                    if current_has_post_check:
                        st.session_state.tt_post_goods_settings["GOODS_START_MANUAL"] = curr.strftime("%H:%M")
                    
                    st.session_state.rebuild_table_flag = True; st.session_state.tt_editor_key += 1
                    st.session_state.request_calc = False; st.success("計算完了"); st.rerun()

        # --- 計算結果表示 ---
        calculated_df = calculate_timetable_flow(edited_df, st.session_state.tt_open_time, st.session_state.tt_start_time)
        st.dataframe(calculated_df[["TIME_DISPLAY", "ARTIST", "GOODS_DISPLAY", "PLACE"]], use_container_width=True, hide_index=True)

        st.divider()
        
        # --- アクションボタン ---
        col_a1, col_a2, col_a3 = st.columns(3)
        with col_a1:
            if st.button("💾 プロジェクトを上書き保存", type="primary"):
                proj = db.query(TimetableProject).filter(TimetableProject.id == st.session_state.tt_current_proj_id).first()
                if proj:
                    save_data = edited_df.to_dict(orient="records")
                    proj.title = st.session_state.tt_title
                    proj.event_date = st.session_state.tt_event_date.strftime("%Y-%m-%d")
                    proj.venue_name = st.session_state.tt_venue
                    proj.open_time = st.session_state.tt_open_time
                    proj.start_time = st.session_state.tt_start_time
                    proj.goods_start_offset = st.session_state.tt_goods_offset
                    proj.data_json = json.dumps(save_data, ensure_ascii=False)
                    # grid_order_json も必要なら更新
                    
                    db.commit()
                    st.session_state.tt_unsaved_changes = False
                    st.success("保存しました")

        with col_a2:
            st.caption("DL")
            csv_d = calculated_df.to_csv(index=False).encode('utf-8_sig')
            st.download_button("CSV", csv_d, "timetable.csv", 'text/csv')
            pdf_b = create_business_pdf(calculated_df, st.session_state.tt_title, st.session_state.tt_event_date.strftime("%Y-%m-%d"), st.session_state.tt_venue)
            st.download_button("PDF", pdf_b, "timetable.pdf", "application/pdf")

        with col_a3:
            all_fonts = [f for f in os.listdir(FONT_DIR) if f.lower().endswith(".ttf")]
            if not all_fonts: all_fonts = ["keifont.ttf"]
            selected_font = st.selectbox("画像フォント", all_fonts)
            
            if st.button("🚀 画像生成"):
                if generate_timetable_image:
                    gen_list = []
                    for _, row in calculated_df.iterrows():
                        if row["ARTIST"] == "OPEN / START": continue
                        gen_list.append([row["TIME_DISPLAY"], row["ARTIST"], row["GOODS_DISPLAY"], row["PLACE"]])
                    
                    if gen_list:
                        img = generate_timetable_image(gen_list, font_path=os.path.join(FONT_DIR, selected_font))
                        st.image(img, caption="プレビュー", use_container_width=True)
                        buf = io.BytesIO(); img.save(buf, format="PNG")
                        st.download_button("画像DL", buf.getvalue(), "timetable.png", "image/png")
                    else:
                        st.warning("データなし")
                else:
                    st.error("ロジックエラー")

    else:
        st.info("👈 メニューまたは上のボックスからプロジェクトを選択してください")
    
    db.close()

# ==========================================
# 3. アー写グリッド作成画面
# ==========================================
elif current_page == "アー写グリッド作成":
    st.title("🖼️ アー写グリッド作成")
    db = next(get_db())
    
    try:
        projects = db.query(TimetableProject).all()
        projects.sort(key=lambda x: x.event_date or "0000-00-00", reverse=True)
        
        col_g1, col_g2 = st.columns([3, 1])
        with col_g1:
            # プロジェクト選択肢
            p_map = {f"{p.event_date} {p.title}": p.id for p in projects}
            sel_label = st.selectbox("プロジェクト選択", ["(選択)"] + list(p_map.keys()))
        
        if "grid_order" not in st.session_state: st.session_state.grid_order = []
        if "grid_cols" not in st.session_state: st.session_state.grid_cols = 5
        if "grid_rows" not in st.session_state: st.session_state.grid_rows = 5
        
        if sel_label != "(選択)":
            proj_id = p_map[sel_label]
            proj = db.query(TimetableProject).filter(TimetableProject.id == proj_id).first()
            
            # 初回ロードまたはプロジェクト変更時のみ読み込み
            if "current_grid_proj_id" not in st.session_state or st.session_state.current_grid_proj_id != proj_id:
                # タイムテーブルデータからアーティスト抽出
                tt_artists = []
                if proj.data_json:
                    d = json.loads(proj.data_json)
                    tt_artists = [i["ARTIST"] for i in d if i["ARTIST"] not in ["開演前物販", "終演後物販"]]
                
                # 保存済みグリッド順序があれば復元、なければタイムテーブル順
                saved_order = []
                if proj.grid_order_json:
                    try:
                        loaded = json.loads(proj.grid_order_json)
                        if isinstance(loaded, dict):
                            saved_order = loaded.get("order", [])
                            st.session_state.grid_cols = loaded.get("cols", 5)
                            st.session_state.grid_rows = loaded.get("rows", 5)
                        else:
                            saved_order = loaded
                    except: pass
                
                if saved_order:
                    # マージ（保存済み順序 + 新しく追加されたアーティスト）
                    merged = [n for n in saved_order if n in tt_artists]
                    for n in tt_artists:
                        if n not in merged: merged.append(n)
                    st.session_state.grid_order = merged
                else:
                    st.session_state.grid_order = list(reversed(tt_artists)) # デフォルトは逆順(トリ)から
                
                st.session_state.current_grid_proj_id = proj_id

            st.divider()
            
            c_set1, c_set2, c_set3 = st.columns(3)
            with c_set1: st.session_state.grid_rows = st.number_input("行数", min_value=1, value=st.session_state.grid_rows)
            with c_set2: st.session_state.grid_cols = st.number_input("列数", min_value=1, value=st.session_state.grid_cols)
            with c_set3: 
                if st.button("リセット"):
                    if proj.data_json:
                        d = json.loads(proj.data_json)
                        st.session_state.grid_order = list(reversed([i["ARTIST"] for i in d if i["ARTIST"] not in ["開演前物販", "終演後物販"]]))
                        st.rerun()

            st.caption("ドラッグ&ドロップで並び替え")
            if sort_items:
                # グリッド状にアイテムを配置してソートUIを作る
                grid_ui = []
                curr = 0
                for r in range(st.session_state.grid_rows):
                    items = []
                    for c in range(st.session_state.grid_cols):
                        if curr < len(st.session_state.grid_order):
                            items.append(st.session_state.grid_order[curr])
                            curr += 1
                    grid_ui.append({"header": f"行{r+1}", "items": items})
                
                # 余り
                while curr < len(st.session_state.grid_order):
                    grid_ui.append({"header": "予備", "items": [st.session_state.grid_order[curr]]})
                    curr += 1
                
                res = sort_items(grid_ui, multi_containers=True)
                # フラットに戻す
                new_flat = []
                for g in res: new_flat.extend(g["items"])
                
                if new_flat != st.session_state.grid_order:
                    st.session_state.grid_order = new_flat
                    st.rerun()

            if st.button("💾 配置を保存"):
                save_d = {"cols": st.session_state.grid_cols, "rows": st.session_state.grid_rows, "order": st.session_state.grid_order}
                proj.grid_order_json = json.dumps(save_d, ensure_ascii=False)
                db.commit()
                st.success("保存しました")

            st.divider()
            
            c_gen1, c_gen2 = st.columns(2)
            with c_gen1:
                af = [f for f in os.listdir(FONT_DIR) if f.lower().endswith(".ttf")]
                if not af: af = ["keifont.ttf"]
                sf = st.selectbox("フォント", af, key="grid_font")
            
            with c_gen2:
                if st.button("🚀 グリッド生成", type="primary"):
                    if generate_grid_image:
                        # アーティストオブジェクトのリストを作成
                        target_artists = []
                        for n in st.session_state.grid_order:
                            a = db.query(Artist).filter(Artist.name == n).first()
                            if a: target_artists.append(a)
                        
                        with st.spinner("生成中..."):
                            try:
                                img = generate_grid_image(target_artists, IMAGE_DIR, font_path=os.path.join(FONT_DIR, sf), cols=st.session_state.grid_cols)
                                st.image(img, use_container_width=True)
                                b = io.BytesIO(); img.save(b, format="PNG")
                                st.download_button("画像DL", b.getvalue(), "grid.png", "image/png")
                            except Exception as e:
                                st.error(f"生成エラー: {e}")
    finally:
        db.close()

# ==========================================
# 4. アーティスト管理
# ==========================================
elif current_page == "アーティスト管理":
    st.title("🎤 アーティスト管理")
    db = next(get_db())
    if "editing_artist_id" not in st.session_state: st.session_state.editing_artist_id = None

    try:
        with st.expander("➕ 新規登録", expanded=False):
            with st.form("new_artist"):
                n = st.text_input("名前")
                f = st.file_uploader("画像", type=['jpg','png'])
                if st.form_submit_button("登録"):
                    if n:
                        fname = None
                        if f:
                            ext = os.path.splitext(f.name)[1]
                            fname = f"{uuid.uuid4()}{ext}"
                            upload_image_to_supabase(f, fname)
                        
                        exists = db.query(Artist).filter(Artist.name==n).first()
                        if exists:
                            if exists.is_deleted: exists.is_deleted=False; exists.image_filename=fname; st.success("復元しました")
                            else: st.error("登録済み")
                        else:
                            db.add(Artist(name=n, image_filename=fname)); st.success("登録しました")
                        db.commit(); st.rerun()
                    else: st.error("名前必須")

        st.divider()
        artists = db.query(Artist).filter(Artist.is_deleted==False).order_by(Artist.name).all()
        if not artists: st.info("なし")
        
        cols = st.columns(3)
        for i, a in enumerate(artists):
            with cols[i%3]:
                with st.container(border=True):
                    if st.session_state.editing_artist_id == a.id:
                        en = st.text_input("名前", a.name, key=f"en_{a.id}")
                        ef = st.file_uploader("画像変更", type=['jpg','png'], key=f"ef_{a.id}")
                        c1, c2 = st.columns(2)
                        with c1:
                            if st.button("保存", key=f"sv_{a.id}"):
                                if en:
                                    fn = a.image_filename
                                    if ef:
                                        ext = os.path.splitext(ef.name)[1]
                                        fn = f"{uuid.uuid4()}{ext}"
                                        upload_image_to_supabase(ef, fn)
                                    a.name = en; a.image_filename = fn; db.commit()
                                    st.session_state.editing_artist_id = None; st.rerun()
                        with c2:
                            if st.button("中止", key=f"cn_{a.id}"):
                                st.session_state.editing_artist_id = None; st.rerun()
                    else:
                        if a.image_filename:
                            u = get_image_url(a.image_filename)
                            if u: st.image(u, use_container_width=True)
                        st.subheader(a.name)
                        c1, c2 = st.columns(2)
                        with c1:
                            if st.button("編集", key=f"ed_{a.id}"):
                                st.session_state.editing_artist_id = a.id; st.rerun()
                        with c2:
                            if st.button("削除", key=f"dl_{a.id}"):
                                a.is_deleted = True; a.name = f"{a.name}_del_{int(time.time())}"
                                db.commit(); st.rerun()
    finally:
        db.close()
