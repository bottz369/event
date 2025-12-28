import streamlit as st
import os
import pandas as pd
import json
import io
import time
import uuid  # ★追加: ランダムな英数字を作るためのライブラリ
from datetime import datetime, timedelta, date

# database.pyから関数をインポート
from database import (
    init_db, get_db, Artist, TimetableProject, FavoriteFont, 
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
if "last_menu" not in st.session_state: st.session_state.last_menu = "アーティスト管理"

# メニュー選択
menu_selection = st.sidebar.radio("機能を選択", ["アーティスト管理", "タイムテーブル作成", "アー写グリッド作成"], key="sb_menu")

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
# 1. アーティスト管理画面
# ==========================================
if current_page == "アーティスト管理":
    st.title("🎤 アーティスト管理")
    # next()を使ってジェネレータからセッションを取り出す
    db = next(get_db())
    
    try:
        with st.expander("➕ アーティストを登録・編集する", expanded=False):
            active_artists = db.query(Artist).filter(Artist.is_deleted == False).all()
            active_artists.sort(key=lambda x: x.name)
            artist_names = [a.name for a in active_artists]
            
            edit_target_name = st.selectbox("編集対象（新規は空欄）", [""] + artist_names)
            
            with st.form("artist_form", clear_on_submit=True):
                input_name = st.text_input("アーティスト名", value=edit_target_name)
                uploaded_file = st.file_uploader("アー写 (jpg, png)", type=['jpg', 'png', 'jpeg'])
                submitted = st.form_submit_button("保存")
                
                if submitted:
                    if not input_name:
                        st.error("名前を入力してください")
                    else:
                        filename = None
                        # 画像アップロード処理
                        if uploaded_file:
                            # ★修正点: ファイル名をランダムな英数字(UUID)に変更して日本語問題を回避
                            ext = os.path.splitext(uploaded_file.name)[1]
                            filename = f"{uuid.uuid4()}{ext}"
                            
                            # Supabaseにアップロード
                            res = upload_image_to_supabase(uploaded_file, filename)
                            if not res:
                                st.error("画像のアップロードに失敗しました")
                                filename = None

                        if edit_target_name:
                            artist = db.query(Artist).filter(Artist.name == edit_target_name).first()
                            artist.name = input_name
                            if filename: artist.image_filename = filename
                            st.success("更新しました")
                        else:
                            existing = db.query(Artist).filter(Artist.name == input_name).first()
                            if existing:
                                if existing.is_deleted:
                                    existing.is_deleted = False
                                    if filename: existing.image_filename = filename
                                    st.success("復元・更新しました")
                                else:
                                    st.error("登録済みです")
                            else:
                                db.add(Artist(name=input_name, image_filename=filename))
                                st.success("登録しました")
                        db.commit()
                        st.rerun()

        st.divider()
        st.subheader(f"登録済み一覧 ({len(active_artists)})")
        
        if active_artists:
            cols = st.columns(3)
            for idx, artist in enumerate(active_artists):
                with cols[idx % 3]:
                    # 画像表示をSupabaseのURL取得に変更
                    if artist.image_filename:
                        image_url = get_image_url(artist.image_filename)
                        if image_url:
                            st.image(image_url, use_container_width=True)
                        else:
                            st.caption("No Image")
                    else:
                        st.caption("No Image Registered")
                    
                    col_sub1, col_sub2 = st.columns([3, 1])
                    with col_sub1:
                        st.markdown(f"**{artist.name}**")
                    with col_sub2:
                        if st.button("削除", key=f"del_btn_{artist.id}"):
                            st.session_state[f"confirm_del_{artist.id}"] = True
                            st.rerun()
                        
                        if st.session_state.get(f"confirm_del_{artist.id}"):
                            st.warning("本当に？")
                            col_conf1, col_conf2 = st.columns(2)
                            with col_conf1:
                                if st.button("Yes", key=f"yes_{artist.id}"):
                                    artist.is_deleted = True
                                    artist.name = f"{artist.name}_deleted_{int(time.time())}"
                                    db.commit()
                                    del st.session_state[f"confirm_del_{artist.id}"]
                                    st.rerun()
                            with col_conf2:
                                if st.button("No", key=f"no_{artist.id}"):
                                    del st.session_state[f"confirm_del_{artist.id}"]
                                    st.rerun()
                    st.divider()
    finally:
        db.close()

# ==========================================
# 2. タイムテーブル作成画面 (変更なし)
# ==========================================
elif current_page == "タイムテーブル作成":
    st.title("⏱️ タイムテーブル作成")
    # next()を使ってジェネレータからセッションを取り出す
    db = next(get_db())
    
    def import_csv_callback():
        uploaded_csv = st.session_state.get("csv_upload_key")
        if not uploaded_csv:
            st.session_state.import_error = "ファイルが選択されていません"
            return

        try:
            uploaded_csv.seek(0)
            try:
                df_csv = pd.read_csv(uploaded_csv)
            except UnicodeDecodeError:
                uploaded_csv.seek(0)
                df_csv = pd.read_csv(uploaded_csv, encoding="cp932")
            
            df_csv.columns = [c.strip() for c in df_csv.columns]
            
            new_order = []
            new_artist_settings = {}
            new_row_settings = []
            event_date_found = None

            if "グループ名" in df_csv.columns:
                try:
                    for col in df_csv.columns:
                        val = str(df_csv.iloc[0][col])
                        if "/" in val or "-" in val:
                            try:
                                temp_date = pd.to_datetime(val).date()
                                event_date_found = temp_date
                                break
                            except: pass
                except: pass

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
            
            if event_date_found:
                st.session_state.tt_event_date = event_date_found
            
            st.session_state.rebuild_table_flag = True 
            st.session_state.tt_unsaved_changes = True
            st.session_state.import_success = f"✅ 読み込み完了！ ({len(new_order)}組)"

        except Exception as e:
            st.session_state.import_error = f"読み込みエラー: {e}"

    try:
        projects = db.query(TimetableProject).all()
        projects.sort(key=lambda x: x.event_date or "0000-00-00", reverse=True)
        
        project_options = {}
        for p in projects:
            date_str = p.event_date if p.event_date else "日付未定"
            label = f"{date_str} {p.title}"
            project_options[label] = p.id

        col_p1, col_p2, col_p3 = st.columns([3, 1, 1])
        with col_p1:
            if "last_project_selection" not in st.session_state:
                st.session_state.last_project_selection = "(新規作成)"
            if "tt_project_select" not in st.session_state:
                st.session_state.tt_project_select = "(新規作成)"

            user_selected_project_label = st.selectbox(
                "プロジェクトを選択", 
                ["(新規作成)"] + list(project_options.keys()), 
                key="tt_project_select"
            )
            
            active_project_label = user_selected_project_label

        def revert_project_selection():
            st.session_state.tt_project_select = st.session_state.last_project_selection

        if st.session_state.tt_unsaved_changes and user_selected_project_label != st.session_state.last_project_selection:
            st.warning("⚠️ 別のプロジェクトに切り替えようとしています。未保存の変更は破棄されます。")
            col_prj1, col_prj2 = st.columns(2)
            with col_prj1:
                if st.button("変更を破棄して切り替える"):
                    st.session_state.tt_unsaved_changes = False
                    st.session_state.last_project_selection = user_selected_project_label 
                    st.rerun()
            with col_prj2:
                if st.button("キャンセル", on_click=revert_project_selection):
                    st.rerun()
            
            active_project_label = st.session_state.last_project_selection
        else:
            st.session_state.last_project_selection = active_project_label

        if "tt_artists_order" not in st.session_state: st.session_state.tt_artists_order = [] 
        if "tt_artist_settings" not in st.session_state: st.session_state.tt_artist_settings = {}
        if "tt_row_settings" not in st.session_state: st.session_state.tt_row_settings = []
        
        if "tt_has_pre_goods" not in st.session_state: st.session_state.tt_has_pre_goods = False
        if "tt_pre_goods_settings" not in st.session_state: st.session_state.tt_pre_goods_settings = get_default_row_settings()
        if "tt_post_goods_settings" not in st.session_state: st.session_state.tt_post_goods_settings = get_default_row_settings()
        
        if "tt_editor_key" not in st.session_state: st.session_state.tt_editor_key = 0 
        if "binding_df" not in st.session_state: st.session_state.binding_df = pd.DataFrame()
        if "rebuild_table_flag" not in st.session_state: st.session_state.rebuild_table_flag = True

        if "tt_title" not in st.session_state: st.session_state.tt_title = "新規イベント"
        if "tt_event_date" not in st.session_state: st.session_state.tt_event_date = date.today()
        if "tt_venue" not in st.session_state: st.session_state.tt_venue = ""
        if "tt_open_time" not in st.session_state: st.session_state.tt_open_time = "10:00"
        if "tt_start_time" not in st.session_state: st.session_state.tt_start_time = "10:30"
        if "tt_goods_offset" not in st.session_state: st.session_state.tt_goods_offset = 5
        
        if "request_calc" not in st.session_state: st.session_state.request_calc = False

        def force_sync():
            st.session_state.tt_unsaved_changes = True 
            if "tt_start_time" in st.session_state:
                st.session_state.tt_start_time = st.session_state.tt_start_time

        def mark_dirty():
            st.session_state.tt_unsaved_changes = True

        if "last_loaded_project" not in st.session_state: st.session_state.last_loaded_project = None

        if active_project_label == "(新規作成)" and st.session_state.last_loaded_project != "(新規作成)":
            st.session_state.tt_artists_order = []
            st.session_state.tt_artist_settings = {}
            st.session_state.tt_row_settings = []
            st.session_state.tt_has_pre_goods = False
            st.session_state.tt_pre_goods_settings = get_default_row_settings()
            st.session_state.tt_post_goods_settings = get_default_row_settings()
            
            st.session_state.tt_title = "新規イベント"
            st.session_state.tt_event_date = date.today()
            st.session_state.tt_venue = ""
            st.session_state.tt_open_time = "10:00"
            st.session_state.tt_start_time = "10:30"
            st.session_state.tt_goods_offset = 5
            st.session_state.rebuild_table_flag = True
            st.session_state.last_loaded_project = "(新規作成)"
            st.session_state.tt_unsaved_changes = False
            st.rerun()
        
        if active_project_label != "(新規作成)":
            project_id = project_options[active_project_label]
            with col_p2:
                if st.button("ロード", type="primary"):
                    proj = db.query(TimetableProject).filter(TimetableProject.id == project_id).first()
                    if proj:
                        data = json.loads(proj.data_json)
                        st.session_state.tt_title = proj.title
                        st.session_state.tt_venue = proj.venue_name or ""
                        st.session_state.tt_open_time = proj.open_time or "10:00"
                        st.session_state.tt_start_time = proj.start_time or "10:30"
                        st.session_state.tt_goods_offset = proj.goods_start_offset if proj.goods_start_offset is not None else 5
                        
                        if proj.event_date:
                            try: st.session_state.tt_event_date = datetime.strptime(proj.event_date, "%Y-%m-%d").date()
                            except: st.session_state.tt_event_date = date.today()
                        
                        new_order = []
                        new_artist_settings = {}
                        new_row_settings = []
                        
                        st.session_state.tt_has_pre_goods = False
                        
                        for item in data:
                            name = item["ARTIST"]
                            if name == "開演前物販":
                                st.session_state.tt_has_pre_goods = True
                                st.session_state.tt_pre_goods_settings = {
                                    "ADJUSTMENT": 0,
                                    "GOODS_START_MANUAL": safe_str(item.get("GOODS_START_MANUAL")),
                                    "GOODS_DURATION": safe_int(item.get("GOODS_DURATION"), 60),
                                    "PLACE": safe_str(item.get("PLACE")),
                                    "ADD_GOODS_START": "", "ADD_GOODS_DURATION": None, "ADD_GOODS_PLACE": "",
                                    "IS_POST_GOODS": False
                                }
                                continue
                            if name == "終演後物販":
                                st.session_state.tt_post_goods_settings = {
                                    "ADJUSTMENT": 0,
                                    "GOODS_START_MANUAL": safe_str(item.get("GOODS_START_MANUAL")),
                                    "GOODS_DURATION": safe_int(item.get("GOODS_DURATION"), 60),
                                    "PLACE": safe_str(item.get("PLACE")),
                                    "ADD_GOODS_START": "", "ADD_GOODS_DURATION": None, "ADD_GOODS_PLACE": "",
                                    "IS_POST_GOODS": False
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
                        st.session_state.tt_unsaved_changes = False
                        st.session_state.last_loaded_project = active_project_label 
                        st.success("ロードしました")
                        st.rerun()
            with col_p3:
                if st.button("削除", type="secondary", key="btn_del_project"):
                    if "confirm_del_proj" not in st.session_state:
                        st.session_state.confirm_del_proj = False
                    
                    if not st.session_state.confirm_del_proj:
                        if st.button("削除確認", key="btn_del_confirm"):
                            st.session_state.confirm_del_proj = True
                            st.rerun()
                    else:
                        st.warning("本当に削除しますか？")
                        if st.button("はい、削除します", key="btn_del_execute"):
                            proj = db.query(TimetableProject).filter(TimetableProject.id == project_id).first()
                            if proj:
                                db.delete(proj)
                                db.commit()
                                st.session_state.confirm_del_proj = False
                                st.success("削除しました")
                                st.rerun()

        st.divider()
        
        col_base1, col_base2, col_base3 = st.columns(3)
        with col_base1:
            st.text_input("イベント名", key="tt_title", on_change=mark_dirty)
            st.date_input("開催日", key="tt_event_date", on_change=mark_dirty)
            
            col_offset1, col_offset2 = st.columns([2, 1])
            with col_offset1:
                st.number_input("物販開始タイミング（出番終了後〇〇分）", min_value=0, key="tt_goods_offset", on_change=mark_dirty)
            with col_offset2:
                st.write("")
                st.write("")
                if st.button("🔄 反映", help="計算ロジックを実行します"):
                    st.session_state.request_calc = True
                    mark_dirty()

        with col_base2:
            st.text_input("会場名", key="tt_venue", on_change=mark_dirty)
        with col_base3:
            st.selectbox("開場時間", TIME_OPTIONS, key="tt_open_time", on_change=mark_dirty)
            st.selectbox("開演時間", TIME_OPTIONS, key="tt_start_time", on_change=mark_dirty)

        with st.expander("📂 CSVからタイムテーブルを読み込む"):
            st.info("対応CSV: 既存形式 / 新形式(START, END, グループ名, 持ち時間...) 自動判定")
            st.file_uploader("CSVファイルをアップロード", type=["csv"], key="csv_upload_key")
            st.button("CSVデータを反映", on_click=import_csv_callback)
            
            if "import_success" in st.session_state:
                st.success(st.session_state.import_success)
                del st.session_state.import_success
            if "import_error" in st.session_state:
                st.error(st.session_state.import_error)
                del st.session_state.import_error

        st.divider()

        col_ui_left, col_ui_right = st.columns([1, 2.5])
        
        with col_ui_left:
            st.subheader("出演順")
            
            all_artists = db.query(Artist).filter(Artist.is_deleted == False).all()
            all_artists.sort(key=lambda x: x.name)
            available_to_add = [a.name for a in all_artists if a.name not in st.session_state.tt_artists_order]
            
            col_add1, col_add2 = st.columns([3, 1])
            with col_add1:
                new_artist = st.selectbox("追加", [""] + available_to_add, label_visibility="collapsed")
            with col_add2:
                if st.button("＋"):
                    if new_artist:
                        st.session_state.tt_artists_order.append(new_artist)
                        st.session_state.tt_artist_settings[new_artist] = {"DURATION": 20}
                        st.session_state.tt_row_settings.append(get_default_row_settings())
                        st.session_state.rebuild_table_flag = True 
                        mark_dirty()
                        st.rerun()

            st.markdown("---")
            st.caption("ドラッグ&ドロップで並び替えできます（出演(分)のみ連動して移動します）")
            
            if not st.session_state.tt_artists_order:
                st.info("アーティストが追加されていません")
            else:
                if sort_items:
                    sorted_items = sort_items(st.session_state.tt_artists_order, direction="vertical")
                    if sorted_items != st.session_state.tt_artists_order:
                        st.session_state.tt_artists_order = sorted_items
                        st.session_state.rebuild_table_flag = True
                        mark_dirty()
                        st.rerun()
                else:
                    st.warning("`pip install streamlit-sortables` を実行するとドラッグ移動が可能です")
                    for i, artist_name in enumerate(st.session_state.tt_artists_order):
                        c1, c2, c3 = st.columns([4, 1, 1])
                        with c1: st.text(f"{i+1}. {artist_name}")
                        with c2:
                            if i > 0 and st.button("⬆️", key=f"up_{i}"):
                                st.session_state.tt_artists_order[i], st.session_state.tt_artists_order[i-1] = st.session_state.tt_artists_order[i-1], st.session_state.tt_artists_order[i]
                                st.session_state.rebuild_table_flag = True
                                mark_dirty()
                                st.rerun()
                        with c3:
                            if i < len(st.session_state.tt_artists_order) - 1 and st.button("⬇️", key=f"down_{i}"):
                                st.session_state.tt_artists_order[i], st.session_state.tt_artists_order[i+1] = st.session_state.tt_artists_order[i+1], st.session_state.tt_artists_order[i]
                                st.session_state.rebuild_table_flag = True
                                mark_dirty()
                                st.rerun()

                st.markdown("---")
                st.caption("リストから削除")
                delete_target = st.selectbox("削除するアーティスト", ["(選択なし)"] + st.session_state.tt_artists_order)
                if delete_target != "(選択なし)":
                    if st.button("🗑️ 削除実行"):
                        try:
                            idx = st.session_state.tt_artists_order.index(delete_target)
                            st.session_state.tt_artists_order.pop(idx)
                            if delete_target in st.session_state.tt_artist_settings:
                                del st.session_state.tt_artist_settings[delete_target]
                            if idx < len(st.session_state.tt_row_settings):
                                st.session_state.tt_row_settings.pop(idx)
                            st.session_state.rebuild_table_flag = True
                            mark_dirty()
                            st.rerun()
                        except ValueError:
                            pass

        with col_ui_right:
            st.subheader("詳細設定 & プレビュー")
            
            if st.checkbox("開演前物販を追加する", value=st.session_state.tt_has_pre_goods, on_change=mark_dirty):
                if not st.session_state.tt_has_pre_goods:
                    st.session_state.tt_has_pre_goods = True
                    st.session_state.rebuild_table_flag = True
                    st.rerun()
            else:
                if st.session_state.tt_has_pre_goods:
                    st.session_state.tt_has_pre_goods = False
                    st.session_state.rebuild_table_flag = True
                    st.rerun()

            column_order = [
                "ARTIST", "DURATION", "IS_POST_GOODS", 
                "ADJUSTMENT", 
                "GOODS_START_MANUAL", "GOODS_DURATION", "PLACE",
                "ADD_GOODS_START", "ADD_GOODS_DURATION", "ADD_GOODS_PLACE"
            ]
            
            if st.session_state.rebuild_table_flag:
                rows = []
                # ... (行データ作成ロジックはそのまま)
                if st.session_state.tt_has_pre_goods:
                    dur_minutes = get_duration_minutes(st.session_state.tt_open_time, st.session_state.tt_start_time)
                    st.session_state.tt_pre_goods_settings["GOODS_START_MANUAL"] = st.session_state.tt_open_time
                    st.session_state.tt_pre_goods_settings["GOODS_DURATION"] = dur_minutes
                    
                    p_set = st.session_state.tt_pre_goods_settings
                    rows.append({
                        "ARTIST": "開演前物販",
                        "DURATION": 0, "ADJUSTMENT": 0,
                        "IS_POST_GOODS": False,
                        "GOODS_START_MANUAL": safe_str(p_set.get("GOODS_START_MANUAL")),
                        "GOODS_DURATION": safe_int(p_set.get("GOODS_DURATION"), 60),
                        "PLACE": "", 
                        "ADD_GOODS_START": "", "ADD_GOODS_DURATION": None, "ADD_GOODS_PLACE": ""
                    })

                while len(st.session_state.tt_row_settings) < len(st.session_state.tt_artists_order):
                    st.session_state.tt_row_settings.append(get_default_row_settings())

                has_post_goods_check = False 

                for i, name in enumerate(st.session_state.tt_artists_order):
                    artist_data = st.session_state.tt_artist_settings.get(name, {"DURATION": 20})
                    row_data = st.session_state.tt_row_settings[i]
                    
                    is_post = bool(row_data.get("IS_POST_GOODS", False))
                    if is_post: has_post_goods_check = True
                    
                    rows.append({
                        "ARTIST": name,
                        "DURATION": safe_int(artist_data.get("DURATION"), 20),
                        "IS_POST_GOODS": is_post,
                        "ADJUSTMENT": safe_int(row_data.get("ADJUSTMENT"), 0),
                        "GOODS_START_MANUAL": safe_str(row_data.get("GOODS_START_MANUAL")),
                        "GOODS_DURATION": safe_int(row_data.get("GOODS_DURATION"), 60),
                        "PLACE": safe_str(row_data.get("PLACE")),
                        "ADD_GOODS_START": safe_str(row.get("ADD_GOODS_START")),
                        "ADD_GOODS_DURATION": safe_int(row.get("ADD_GOODS_DURATION"), None),
                        "ADD_GOODS_PLACE": safe_str(row.get("ADD_GOODS_PLACE"))
                    })
                
                if has_post_goods_check:
                    post_set = st.session_state.tt_post_goods_settings
                    rows.append({
                        "ARTIST": "終演後物販",
                        "DURATION": 0, "ADJUSTMENT": 0,
                        "IS_POST_GOODS": False, 
                        "GOODS_START_MANUAL": safe_str(post_set.get("GOODS_START_MANUAL")),
                        "GOODS_DURATION": safe_int(post_set.get("GOODS_DURATION"), 60),
                        "PLACE": "", 
                        "ADD_GOODS_START": "", "ADD_GOODS_DURATION": None, "ADD_GOODS_PLACE": ""
                    })

                st.session_state.binding_df = pd.DataFrame(rows, columns=column_order)
                st.session_state.tt_editor_key += 1
                st.session_state.rebuild_table_flag = False

            if not st.session_state.binding_df.empty:
                current_editor_key = f"tt_editor_{st.session_state.tt_editor_key}"
                if current_editor_key in st.session_state:
                    if isinstance(st.session_state[current_editor_key], pd.DataFrame):
                        st.session_state.binding_df = st.session_state[current_editor_key]

            # デフォルトのデータフレーム作成
            edited_df = pd.DataFrame(columns=column_order)

            if not st.session_state.binding_df.empty:
                edited_df = st.data_editor(
                    st.session_state.binding_df, 
                    key=current_editor_key,
                    num_rows="fixed",
                    use_container_width=True,
                    column_config={
                        "ARTIST": st.column_config.TextColumn("アーティスト", disabled=True),
                        "DURATION": st.column_config.SelectboxColumn("出演(分)", options=DURATION_OPTIONS, width="small"),
                        "IS_POST_GOODS": st.column_config.CheckboxColumn("終演後物販", width="small"),
                        "ADJUSTMENT": st.column_config.SelectboxColumn("転換(分)", options=ADJUSTMENT_OPTIONS, width="small"),
                        "GOODS_START_MANUAL": st.column_config.SelectboxColumn("物販開始", options=[""] + TIME_OPTIONS, width="small"),
                        "GOODS_DURATION": st.column_config.SelectboxColumn("物販(分)", options=GOODS_DURATION_OPTIONS, width="small"),
                        "PLACE": st.column_config.SelectboxColumn("場所", options=[""] + PLACE_OPTIONS, width="small"),
                        "ADD_GOODS_START": st.column_config.SelectboxColumn("追加物販開始", options=[""] + TIME_OPTIONS, width="small"),
                        "ADD_GOODS_DURATION": st.column_config.SelectboxColumn("追加物販(分)", options=GOODS_DURATION_OPTIONS, width="small"),
                        "ADD_GOODS_PLACE": st.column_config.SelectboxColumn("追加場所", options=[""] + PLACE_OPTIONS, width="small"),
                    },
                    hide_index=True,
                    on_change=force_sync
                )
                
                new_row_settings_from_edit = []
                current_has_post_check = False

                for i, row in edited_df.iterrows():
                    name = row["ARTIST"]
                    is_post = bool(row.get("IS_POST_GOODS", False))
                    
                    if name == "開演前物販":
                        dur_minutes = get_duration_minutes(st.session_state.tt_open_time, st.session_state.tt_start_time)
                        st.session_state.tt_pre_goods_settings = {
                            "GOODS_START_MANUAL": st.session_state.tt_open_time,
                            "GOODS_DURATION": dur_minutes,
                            "PLACE": ""
                        }
                        continue
                    if name == "終演後物販":
                        st.session_state.tt_post_goods_settings = {
                            "GOODS_START_MANUAL": safe_str(row["GOODS_START_MANUAL"]),
                            "GOODS_DURATION": safe_int(row["GOODS_DURATION"], 60),
                            "PLACE": ""
                        }
                        continue

                    if is_post: current_has_post_check = True

                    st.session_state.tt_artist_settings[name] = {"DURATION": safe_int(row["DURATION"], 20)}
                    
                    g_start = safe_str(row["GOODS_START_MANUAL"])
                    g_dur = safe_int(row["GOODS_DURATION"], 60)
                    add_start = safe_str(row["ADD_GOODS_START"])
                    add_dur = safe_int(row["ADD_GOODS_DURATION"], None)
                    add_place = safe_str(row["ADD_GOODS_PLACE"])
                    
                    if is_post:
                        g_start = ""
                        g_dur = 60
                        add_start = ""
                        add_dur = None
                        add_place = ""

                    new_row_settings_from_edit.append({
                        "ADJUSTMENT": safe_int(row["ADJUSTMENT"], 0),
                        "GOODS_START_MANUAL": g_start,
                        "GOODS_DURATION": g_dur,
                        "PLACE": safe_str(row["PLACE"]), 
                        "ADD_GOODS_START": add_start,
                        "ADD_GOODS_DURATION": add_dur,
                        "ADD_GOODS_PLACE": add_place,
                        "IS_POST_GOODS": is_post
                    })
                
                if len(new_row_settings_from_edit) == len(st.session_state.tt_artists_order):
                    st.session_state.tt_row_settings = new_row_settings_from_edit
                
                row_exists = any(r["ARTIST"] == "終演後物販" for r in st.session_state.binding_df.to_dict("records"))
                if (current_has_post_check and not row_exists) or (not current_has_post_check and row_exists):
                    st.session_state.rebuild_table_flag = True
                    mark_dirty()
                    st.rerun()

                if st.session_state.request_calc:
                    current_time_obj = datetime.strptime(st.session_state.tt_start_time, "%H:%M")
                    
                    for i, name in enumerate(st.session_state.tt_artists_order):
                        if i >= len(st.session_state.tt_row_settings): break
                        
                        row_data = st.session_state.tt_row_settings[i]
                        
                        if row_data.get("IS_POST_GOODS", False):
                            artist_dur = st.session_state.tt_artist_settings[name].get("DURATION", 20)
                            adj = row_data.get("ADJUSTMENT", 0)
                            end_time_obj = current_time_obj + timedelta(minutes=artist_dur)
                            current_time_obj = end_time_obj + timedelta(minutes=adj)
                            continue

                        artist_dur = st.session_state.tt_artist_settings[name].get("DURATION", 20)
                        end_time_obj = current_time_obj + timedelta(minutes=artist_dur)
                        goods_start_obj = end_time_obj + timedelta(minutes=st.session_state.tt_goods_offset)
                        
                        row_data["GOODS_START_MANUAL"] = goods_start_obj.strftime("%H:%M")
                        st.session_state.tt_row_settings[i] = row_data
                        
                        adj = row_data.get("ADJUSTMENT", 0)
                        current_time_obj = end_time_obj + timedelta(minutes=adj)
                    
                    if current_has_post_check:
                        st.session_state.tt_post_goods_settings["GOODS_START_MANUAL"] = current_time_obj.strftime("%H:%M")

                    st.session_state.rebuild_table_flag = True
                    st.session_state.tt_editor_key += 1
                    st.session_state.request_calc = False
                    st.success("時間を計算して反映しました")
                    st.rerun()

        calculated_df = calculate_timetable_flow(edited_df, st.session_state.tt_open_time, st.session_state.tt_start_time)
        
        st.dataframe(
            calculated_df[["TIME_DISPLAY", "ARTIST", "GOODS_DISPLAY", "PLACE"]],
            use_container_width=True,
            hide_index=True
        )

        st.divider()

        col_act1, col_act2, col_act3 = st.columns(3)
        
        with col_act1:
            save_data = edited_df.to_dict(orient="records")
            tt_json_str = json.dumps(save_data, ensure_ascii=False)
            event_date_str = st.session_state.tt_event_date.strftime("%Y-%m-%d")

            if st.button("💾 プロジェクトを保存"):
                target_grid_rows = 5
                target_grid_cols = 5
                
                if active_project_label != "(新規作成)":
                    current_proj = db.query(TimetableProject).filter(TimetableProject.id == project_id).first()
                    if current_proj and current_proj.grid_order_json:
                        try:
                            loaded = json.loads(current_proj.grid_order_json)
                            if isinstance(loaded, dict):
                                target_grid_rows = loaded.get("rows", 5)
                                target_grid_cols = loaded.get("cols", 5)
                        except: pass
                
                new_grid_order = list(reversed(st.session_state.tt_artists_order))
                
                updated_grid_json = json.dumps({
                    "cols": target_grid_cols,
                    "rows": target_grid_rows,
                    "order": new_grid_order
                }, ensure_ascii=False)

                if active_project_label == "(新規作成)":
                    new_proj = TimetableProject(
                        title=st.session_state.tt_title, 
                        event_date=event_date_str,
                        venue_name=st.session_state.tt_venue,
                        open_time=st.session_state.tt_open_time,
                        start_time=st.session_state.tt_start_time,
                        goods_start_offset=st.session_state.tt_goods_offset,
                        data_json=tt_json_str,
                        grid_order_json=updated_grid_json
                    )
                    db.add(new_proj)
                    st.success("新規保存しました")
                else:
                    proj = db.query(TimetableProject).filter(TimetableProject.id == project_id).first()
                    proj.title = st.session_state.tt_title
                    proj.event_date = event_date_str
                    proj.venue_name = st.session_state.tt_venue
                    proj.open_time = st.session_state.tt_open_time
                    proj.start_time = st.session_state.tt_start_time
                    proj.goods_start_offset = st.session_state.tt_goods_offset
                    proj.data_json = tt_json_str
                    proj.grid_order_json = updated_grid_json 
                    st.success("上書き保存しました")
                
                db.commit()
                st.session_state.tt_unsaved_changes = False
                
                if "current_grid_proj_id" in st.session_state:
                    del st.session_state.current_grid_proj_id

            if active_project_label != "(新規作成)":
                if st.button("📑 複製して保存"):
                    new_grid_order = list(reversed(st.session_state.tt_artists_order))
                    default_grid_json = json.dumps({"cols": 5, "rows": 5, "order": new_grid_order}, ensure_ascii=False)
                    
                    copy_proj = TimetableProject(
                        title=f"{st.session_state.tt_title} のコピー", 
                        event_date=event_date_str,
                        venue_name=st.session_state.tt_venue,
                        open_time=st.session_state.tt_open_time,
                        start_time=st.session_state.tt_start_time, 
                        goods_start_offset=st.session_state.tt_goods_offset,
                        data_json=tt_json_str,
                        grid_order_json=default_grid_json
                    )
                    db.add(copy_proj)
                    db.commit()
                    st.session_state.tt_unsaved_changes = False
                    st.success("複製しました")

        with col_act2:
            st.caption("データ書き出し")
            csv_data = calculated_df.to_csv(index=False).encode('utf-8_sig')
            st.download_button("📄 CSVDL", csv_data, f"timetable.csv", 'text/csv')
            
            pdf_buffer = create_business_pdf(calculated_df, st.session_state.tt_title, event_date_str, st.session_state.tt_venue)
            st.download_button("📄 PDF(表)DL", pdf_buffer, "timetable_business.pdf", "application/pdf")

        with col_act3:
            if st.button("🚀 画像生成", type="primary"):
                if generate_timetable_image:
                    gen_list = []
                    for _, row in calculated_df.iterrows():
                        if row["ARTIST"] == "OPEN / START":
                            continue
                        gen_list.append([row["TIME_DISPLAY"], row["ARTIST"], row["GOODS_DISPLAY"], row["PLACE"]])
                    
                    if gen_list:
                        img = generate_timetable_image(gen_list)
                        st.image(img, caption="プレビュー", use_container_width=True)
                        buf_png = io.BytesIO()
                        img.save(buf_png, format="PNG")
                        st.download_button("⬇️ 画像DL", buf_png.getvalue(), "timetable.png", "image/png")
                    else:
                        st.warning("データなし")
                else:
                    st.error("ロジックエラー")
    finally:
        db.close()

# ==========================================
# 3. アー写グリッド作成画面 (変更なし)
# ==========================================
elif current_page == "アー写グリッド作成":
    st.title("🖼️ アー写グリッド作成")
    # next()を使ってジェネレータからセッションを取り出す
    db = next(get_db())
    
    try:
        projects = db.query(TimetableProject).all()
        projects.sort(key=lambda x: x.event_date or "0000-00-00", reverse=True)
        
        project_options = {}
        for p in projects:
            date_str = p.event_date if p.event_date else "日付未定"
            label = f"{date_str} {p.title}"
            project_options[label] = p.id
        
        col_g1, col_g2 = st.columns([3, 1])
        with col_g1:
            sel_proj_label = st.selectbox("タイムテーブルプロジェクトを選択", ["(選択してください)"] + list(project_options.keys()))
        
        if "grid_order" not in st.session_state: st.session_state.grid_order = []
        if "grid_cols" not in st.session_state: st.session_state.grid_cols = 5
        if "grid_rows" not in st.session_state: st.session_state.grid_rows = 5
        
        if sel_proj_label != "(選択してください)":
            proj_id = project_options[sel_proj_label]
            proj = db.query(TimetableProject).filter(TimetableProject.id == proj_id).first()
            
            if "current_grid_proj_id" not in st.session_state or st.session_state.current_grid_proj_id != proj_id:
                tt_data = []
                current_tt_artists = []
                if proj and proj.data_json:
                    tt_data = json.loads(proj.data_json)
                    current_tt_artists = [item["ARTIST"] for item in tt_data if item["ARTIST"] not in ["開演前物販", "終演後物販"]]

                saved_grid_order = []
                if proj and proj.grid_order_json:
                    loaded_data = json.loads(proj.grid_order_json)
                    if isinstance(loaded_data, dict):
                         saved_grid_order = loaded_data.get("order", [])
                         st.session_state.grid_cols = loaded_data.get("cols", 5)
                         st.session_state.grid_rows = loaded_data.get("rows", 5)
                    else:
                         saved_grid_order = loaded_data
                         st.session_state.grid_cols = 5
                         st.session_state.grid_rows = 5
                
                if saved_grid_order:
                    merged_order = [name for name in saved_grid_order if name in current_tt_artists]
                    existing_set = set(merged_order)
                    for name in current_tt_artists:
                        if name not in existing_set:
                            merged_order.append(name)
                    st.session_state.grid_order = merged_order
                else:
                    st.session_state.grid_order = list(reversed(current_tt_artists))
                    st.session_state.grid_cols = 5
                    st.session_state.grid_rows = 5

                st.session_state.current_grid_proj_id = proj_id
            
            st.divider()
            st.subheader(f"プロジェクト: {proj.title}")
            
            col_set1, col_set2, col_set3 = st.columns(3)
            with col_set1:
                 st.session_state.grid_rows = st.number_input("行数 (Rows)", min_value=1, value=st.session_state.grid_rows)
            with col_set2:
                 st.session_state.grid_cols = st.number_input("列数 (Columns)", min_value=1, value=st.session_state.grid_cols)
            with col_set3:
                if st.button("↺ デフォルト配置に戻す"):
                    tt_data = json.loads(proj.data_json)
                    artist_names = [item["ARTIST"] for item in tt_data if item["ARTIST"] not in ["開演前物販", "終演後物販"]]
                    st.session_state.grid_order = list(reversed(artist_names))
                    st.rerun()

            st.markdown("---")
            st.caption("ドラッグ&ドロップで配置を調整 (左上から右へ、順に並びます)")

            if sort_items:
                grid_structure = []
                current_idx = 0
                cols = st.session_state.grid_cols
                
                for row_idx in range(st.session_state.grid_rows):
                    row_items = []
                    for _ in range(cols):
                        if current_idx < len(st.session_state.grid_order):
                            row_items.append(st.session_state.grid_order[current_idx])
                            current_idx += 1
                    
                    grid_structure.append({
                        "header": f"行 {row_idx + 1}",
                        "items": row_items
                    })
                
                while current_idx < len(st.session_state.grid_order):
                     if grid_structure:
                         grid_structure[-1]["items"].append(st.session_state.grid_order[current_idx])
                     else:
                         grid_structure.append({"header": "余剰", "items": [st.session_state.grid_order[current_idx]]})
                     current_idx += 1

                updated_grid_raw = sort_items(grid_structure, multi_containers=True)
                
                current_flat_check = []
                for b in grid_structure: current_flat_check.extend(b["items"])
                
                new_flat_order = []
                for b in updated_grid_raw: new_flat_order.extend(b["items"])

                if current_flat_check != new_flat_order:
                     st.session_state.grid_order = new_flat_order
                     st.rerun()
            else:
                 st.warning("`pip install streamlit-sortables` を実行してください")
                 for i, artist_name in enumerate(st.session_state.grid_order):
                    st.text(f"{i+1}. {artist_name}")
            
            if st.button("💾 配置設定を保存"):
                save_data = {
                    "cols": st.session_state.grid_cols,
                    "rows": st.session_state.grid_rows,
                    "order": st.session_state.grid_order
                }
                proj.grid_order_json = json.dumps(save_data, ensure_ascii=False)
                db.commit()
                st.success("配置設定を保存しました")

            st.divider()

            all_fonts = [f for f in os.listdir(FONT_DIR) if f.lower().endswith((".ttf", ".otf"))]
            if not all_fonts: all_fonts = ["keifont.ttf"]
            
            fav_fonts = [f.filename for f in db.query(FavoriteFont).all()]
            sorted_fonts = sorted(all_fonts, key=lambda x: (x not in fav_fonts, x))
            
            col_gen1, col_gen2 = st.columns([1, 1])
            with col_gen1:
                font_options = []
                for f in sorted_fonts:
                    mark = "★ " if f in fav_fonts else ""
                    font_options.append(f"{mark}{f}")
                    
                selected_font_label = st.selectbox("フォント選択", font_options)
                selected_font = selected_font_label.replace("★ ", "")
                
                if selected_font in fav_fonts:
                    if st.button("★ お気に入り解除", key="fav_rem"):
                        target = db.query(FavoriteFont).filter(FavoriteFont.filename == selected_font).first()
                        db.delete(target)
                        db.commit()
                        st.rerun()
                else:
                    if st.button("☆ お気に入り登録", key="fav_add"):
                        db.add(FavoriteFont(filename=selected_font))
                        db.commit()
                        st.rerun()

                preview_text = f"{proj.event_date} {proj.title} {proj.venue_name}"
                font_path = os.path.join(FONT_DIR, selected_font)
                preview_img = create_font_preview(preview_text, font_path)
                if preview_img:
                    st.caption("▼ フォントプレビュー")
                    st.image(preview_img)

            with col_gen2:
                st.write("")
                st.write("")
                # ボタンが押されたときの処理
                if st.button("🚀 グリッド画像を生成", type="primary"):
                    if generate_grid_image and st.session_state.grid_order:
                        ordered_artists = []
                        for name in st.session_state.grid_order:
                            a_obj = db.query(Artist).filter(Artist.name == name, Artist.is_deleted == False).first()
                            if a_obj:
                                ordered_artists.append(a_obj)
                        
                        with st.spinner("生成中..."):
                            img = None
                            try:
                                # 生成実行
                                img = generate_grid_image(
                                    ordered_artists, 
                                    IMAGE_DIR, 
                                    font_path=font_path, 
                                    cols=st.session_state.grid_cols
                                )
                            except Exception:
                                # エラー時の再トライ（引数なし版）
                                try:
                                    img = generate_grid_image(ordered_artists, IMAGE_DIR, font_path=font_path)
                                except Exception as e:
                                    st.error(f"生成エラー: {e}")

                            # 画像表示とダウンロード
                            if img:
                                st.image(img, caption="プレビュー", use_container_width=True)
                                buf = io.BytesIO()
                                img.save(buf, format="PNG")
                                st.download_button("⬇️ 画像DL", buf.getvalue(), "grid.png", "image/png")
                    else:
                        st.error("ロジックファイルが見つからないか、データがありません")
    finally:
        db.close()
