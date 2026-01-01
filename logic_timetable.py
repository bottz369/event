import streamlit as st
import json
import datetime
import math  # ★追加: nan判定に必須
from datetime import date
from database import TimetableProject, TimetableRow
from utils import safe_int, safe_str
from constants import get_default_row_settings

# --- ヘルパー関数: 安全なJSON読み込み ---
def parse_json_safe(data, default_val):
    if data is None:
        return default_val
    if isinstance(data, (list, dict)):
        return data
    if isinstance(data, str):
        try:
            return json.loads(data)
        except:
            return default_val
    return default_val

# --- ヘルパー関数: 安全な時間変換 ---
def format_time_safe(t_val, default="10:00"):
    if not t_val:
        return default
    if isinstance(t_val, str):
        if len(t_val) >= 5:
            return t_val[:5]
        return t_val
    if isinstance(t_val, (datetime.time, datetime.datetime)):
        return t_val.strftime("%H:%M")
    return default

# --- ★新規追加: 数値クリーニング関数 ---
def sanitize_int(value):
    """
    PandasのNaNやfloat、文字列などを安全にDB保存用のintまたはNoneに変換する
    """
    if value is None:
        return None
    try:
        # 文字列の場合の処理
        if isinstance(value, str):
            if value.lower() == 'nan' or not value.strip():
                return None
            # "45.0" のような文字列対策
            return int(float(value))
        
        # float (nan含む) の場合の処理
        if isinstance(value, float):
            if math.isnan(value):
                return None
            return int(value)
            
        # 既にintならそのまま
        return int(value)
    except:
        return None

# --- 新規追加: タイムテーブル行データの保存・読込 ---

def save_timetable_rows(db, project_id, rows_data):
    """
    タイムテーブルの行データをDBテーブル(timetable_rows)に保存する。
    """
    try:
        # 1. 既存行の削除
        db.query(TimetableRow).filter(TimetableRow.project_id == project_id).delete()
        
        # 2. 新規行の作成
        new_rows = []
        for idx, item in enumerate(rows_data):
            # ★ここで全ての数値項目を sanitize_int で綺麗にする
            row = TimetableRow(
                project_id=project_id,
                sort_order=idx,
                artist_name=item.get("ARTIST"),
                
                duration=sanitize_int(item.get("DURATION")),
                is_post_goods=bool(item.get("IS_POST_GOODS", False)),
                adjustment=sanitize_int(item.get("ADJUSTMENT")),
                
                goods_start_time=item.get("GOODS_START_MANUAL"),
                goods_duration=sanitize_int(item.get("GOODS_DURATION")),
                place=item.get("PLACE"),
                
                add_goods_start_time=item.get("ADD_GOODS_START"),
                add_goods_duration=sanitize_int(item.get("ADD_GOODS_DURATION")),
                add_goods_place=item.get("ADD_GOODS_PLACE")
            )
            new_rows.append(row)
        
        db.add_all(new_rows)
        db.commit()
        return True
    except Exception as e:
        # エラー詳細を画面に出す
        st.error(f"詳細データの保存エラー: {e}")
        print(f"Error saving timetable rows: {e}")
        db.rollback()
        return False

def load_timetable_rows(db, project_id):
    """
    DBテーブルから行データを読み込み、アプリで使用する辞書リスト形式に変換する。
    """
    try:
        rows = db.query(TimetableRow).filter(TimetableRow.project_id == project_id).order_by(TimetableRow.sort_order).all()
        if not rows:
            return []
            
        data_export = []
        for r in rows:
            item = {
                "ARTIST": r.artist_name,
                "DURATION": r.duration,
                "IS_POST_GOODS": r.is_post_goods,
                "ADJUSTMENT": r.adjustment,
                "GOODS_START_MANUAL": r.goods_start_time,
                "GOODS_DURATION": r.goods_duration,
                "PLACE": r.place,
                "ADD_GOODS_START": r.add_goods_start_time,
                "ADD_GOODS_DURATION": r.add_goods_duration,
                "ADD_GOODS_PLACE": r.add_goods_place
            }
            data_export.append(item)
        return data_export
    except Exception as e:
        print(f"Error loading timetable rows: {e}")
        return []


# --- 読み込み処理 (既存) ---
def load_project_data(db, project_id):
    proj = db.query(TimetableProject).filter(TimetableProject.id == project_id).first()
    if not proj: return False
    
    st.session_state.proj_title = proj.title or ""
    st.session_state.proj_venue = proj.venue_name or ""
    st.session_state.proj_url = proj.venue_url or ""
    
    if proj.event_date:
        try:
            if isinstance(proj.event_date, (datetime.date, datetime.datetime)):
                st.session_state.proj_date = proj.event_date
            else:
                st.session_state.proj_date = datetime.datetime.strptime(str(proj.event_date), "%Y-%m-%d").date()
        except:
            st.session_state.proj_date = None
    else:
        st.session_state.proj_date = None

    st.session_state.tt_open_time = format_time_safe(proj.open_time, "10:00")
    st.session_state.tt_start_time = format_time_safe(proj.start_time, "10:30")
    st.session_state.tt_goods_offset = proj.goods_start_offset or 0

    # DBテーブル優先読み込み
    tt_data_from_db = load_timetable_rows(db, project_id)
    if tt_data_from_db:
        st.session_state.tt_data = tt_data_from_db
    else:
        st.session_state.tt_data = parse_json_safe(proj.data_json, [])

    grid_data = parse_json_safe(proj.grid_order_json, {})
    if isinstance(grid_data, dict):
        st.session_state.grid_order = grid_data.get("order", [])
        st.session_state.grid_row_counts_str = grid_data.get("row_counts_str", "5,5,5,5,5")
        st.session_state.grid_alignment = grid_data.get("alignment", "中央揃え")
        st.session_state.grid_layout_mode = grid_data.get("layout_mode", "レンガ (サイズ統一)")
    else:
        st.session_state.grid_order = grid_data if isinstance(grid_data, list) else []

    st.session_state.proj_tickets = parse_json_safe(proj.tickets_json, [])
    st.session_state.proj_free_text = parse_json_safe(proj.free_text_json, [])

    try:
        raw_notes = proj.ticket_notes_json
    except AttributeError:
        raw_notes = getattr(proj, "ticket_notes_json", None)

    st.session_state.proj_ticket_notes = parse_json_safe(raw_notes, [])
    
    flyer_conf = parse_json_safe(proj.flyer_json, {})
    if flyer_conf:
        st.session_state.flyer_bg_id = int(flyer_conf.get("bg_id", 0))
        st.session_state.flyer_logo_id = int(flyer_conf.get("logo_id", 0))
        st.session_state.flyer_basic_font = flyer_conf.get("font", "keifont.ttf")
        st.session_state.flyer_text_color = flyer_conf.get("text_color", "#FFFFFF")
        st.session_state.flyer_stroke_color = flyer_conf.get("stroke_color", "#000000")

    return True

# --- 保存処理 (既存) ---
def save_current_project(db, project_id):
    """
    現在のセッションステートの内容をデータベースに保存する
    ※行データも同時に保存するように変更しました
    """
    proj = db.query(TimetableProject).filter(TimetableProject.id == project_id).first()
    if not proj: return False
    
    # 基本情報
    if "proj_title" in st.session_state: proj.title = st.session_state.proj_title
    if "proj_date" in st.session_state: 
        if st.session_state.proj_date:
            proj.event_date = st.session_state.proj_date.strftime("%Y-%m-%d")
        else:
            proj.event_date = None
            
    if "proj_venue" in st.session_state: proj.venue_name = st.session_state.proj_venue
    if "proj_url" in st.session_state: proj.venue_url = st.session_state.proj_url
    
    # JSONデータ
    if "proj_tickets" in st.session_state:
        proj.tickets_json = json.dumps(st.session_state.proj_tickets, ensure_ascii=False)
    if "proj_free_text" in st.session_state:
        proj.free_text_json = json.dumps(st.session_state.proj_free_text, ensure_ascii=False)
    
    if "proj_ticket_notes" in st.session_state:
        proj.ticket_notes_json = json.dumps(st.session_state.proj_ticket_notes, ensure_ascii=False)

    # タイムテーブルデータ構築
    save_data = []
    if "binding_df" in st.session_state and not st.session_state.binding_df.empty:
        save_data = st.session_state.binding_df.to_dict(orient="records")
    
    elif "tt_artists_order" in st.session_state and st.session_state.tt_artists_order:
        if st.session_state.get("tt_has_pre_goods"):
            p = st.session_state.get("tt_pre_goods_settings", {})
            save_data.append({
                "ARTIST": "開演前物販", "DURATION": 0, "ADJUSTMENT": 0, "IS_POST_GOODS": False,
                "GOODS_START_MANUAL": safe_str(p.get("GOODS_START_MANUAL")), "GOODS_DURATION": safe_int(p.get("GOODS_DURATION"), 60), "PLACE": "",
                "ADD_GOODS_START": "", "ADD_GOODS_DURATION": None, "ADD_GOODS_PLACE": ""
            })
        
        for i, name in enumerate(st.session_state.tt_artists_order):
            ad = st.session_state.tt_artist_settings.get(name, {"DURATION": 20})
            if i < len(st.session_state.tt_row_settings):
                rd = st.session_state.tt_row_settings[i]
            else:
                rd = {}
            
            save_data.append({
                "ARTIST": name, "DURATION": safe_int(ad.get("DURATION"), 20),
                "IS_POST_GOODS": bool(rd.get("IS_POST_GOODS", False)), "ADJUSTMENT": safe_int(rd.get("ADJUSTMENT"), 0),
                "GOODS_START_MANUAL": safe_str(rd.get("GOODS_START_MANUAL")), "GOODS_DURATION": safe_int(rd.get("GOODS_DURATION"), 60), "PLACE": safe_str(rd.get("PLACE")),
                "ADD_GOODS_START": safe_str(rd.get("ADD_GOODS_START")), "ADD_GOODS_DURATION": safe_int(rd.get("ADD_GOODS_DURATION"), None), "ADD_GOODS_PLACE": safe_str(rd.get("ADD_GOODS_PLACE"))
            })
            
        has_post = any(x.get("IS_POST_GOODS") for x in save_data)
        if has_post:
            p = st.session_state.get("tt_post_goods_settings", {})
            save_data.append({
                "ARTIST": "終演後物販", "DURATION": 0, "ADJUSTMENT": 0, "IS_POST_GOODS": False,
                "GOODS_START_MANUAL": safe_str(p.get("GOODS_START_MANUAL")), "GOODS_DURATION": safe_int(p.get("GOODS_DURATION"), 60), "PLACE": "",
                "ADD_GOODS_START": "", "ADD_GOODS_DURATION": None, "ADD_GOODS_PLACE": ""
            })

    if save_data:
        proj.data_json = json.dumps(save_data, ensure_ascii=False)
        # ★重要: ここで同時にテーブルへの保存も行う
        save_timetable_rows(db, project_id, save_data)
    
    if "tt_open_time" in st.session_state: proj.open_time = st.session_state.tt_open_time
    if "tt_start_time" in st.session_state: proj.start_time = st.session_state.tt_start_time
    if "tt_goods_offset" in st.session_state: proj.goods_start_offset = st.session_state.tt_goods_offset

    if "grid_order" in st.session_state:
        grid_data = {
            "cols": st.session_state.get("grid_cols", 5),
            "rows": st.session_state.get("grid_rows", 5),
            "order": st.session_state.grid_order,
            "row_counts_str": st.session_state.get("grid_row_counts_str", "5,5,5,5,5"),
            "alignment": st.session_state.get("grid_alignment", "中央揃え"),
            "layout_mode": st.session_state.get("grid_layout_mode", "レンガ (サイズ統一)")
        }
        proj.grid_order_json = json.dumps(grid_data, ensure_ascii=False)

    settings = {
        "tt_font": st.session_state.get("tt_font", "keifont.ttf"),
        "grid_font": st.session_state.get("grid_font", "keifont.ttf")
    }
    proj.settings_json = json.dumps(settings, ensure_ascii=False)

    flyer_data = {}
    keys = ["flyer_bg_id", "flyer_logo_id", "flyer_basic_font", "flyer_text_color", "flyer_stroke_color"]
    for k in keys:
        if k in st.session_state:
            short_key = k.replace("flyer_", "").replace("basic_", "")
            flyer_data[short_key] = st.session_state[k]
    
    if proj.flyer_json:
        try:
            existing_flyer = proj.flyer_json
            if isinstance(existing_flyer, str):
                existing_flyer = json.loads(existing_flyer)
            elif not isinstance(existing_flyer, dict):
                existing_flyer = {}
            existing_flyer.update(flyer_data)
            flyer_data = existing_flyer
        except:
            pass

    proj.flyer_json = json.dumps(flyer_data, ensure_ascii=False)
    
    db.commit()
    return True

# --- 複製処理 (既存) ---
def duplicate_project(db, project_id):
    src = db.query(TimetableProject).filter(TimetableProject.id == project_id).first()
    if not src: return None
    new_proj = TimetableProject(
        title=f"{src.title} (コピー)",
        event_date=src.event_date,
        venue_name=src.venue_name,
        venue_url=src.venue_url,
        open_time=src.open_time,
        start_time=src.start_time,
        goods_start_offset=src.goods_start_offset,
        data_json=src.data_json,
        grid_order_json=src.grid_order_json,
        tickets_json=src.tickets_json,
        free_text_json=src.free_text_json,
        ticket_notes_json=src.ticket_notes_json, 
        flyer_json=src.flyer_json,
        settings_json=src.settings_json
    )
    db.add(new_proj)
    db.commit()
    
    # 行データも複製
    src_rows = load_timetable_rows(db, src.id)
    save_timetable_rows(db, new_proj.id, src_rows)
    
    return new_proj
