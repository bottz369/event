import streamlit as st
import json
import datetime
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
        except Exception:
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

# --- 新規追加: タイムテーブル行データの保存・読込 ---

def save_timetable_rows(db, project_id, rows_data):
    """
    タイムテーブルの行データをDBテーブル(timetable_rows)に保存する。
    ★修正: 数値データに safe_int を適用して nan エラーを防止
    ★修正: is_hidden (非表示フラグ) の保存を追加
    ★修正: 追加物販時間(ADD_GOODS_DURATION)のデフォルトを60ではなくNoneに変更
    """
    try:
        # 1. 既存行の削除
        db.query(TimetableRow).filter(TimetableRow.project_id == project_id).delete()
        
        # 2. 新規行の作成
        new_rows = []
        for idx, item in enumerate(rows_data):
            # 数値型カラムに入れる値は必ず safe_int を通す
            duration_val = safe_int(item.get("DURATION"), 0)
            adjustment_val = safe_int(item.get("ADJUSTMENT"), 0)
            goods_duration_val = safe_int(item.get("GOODS_DURATION"), 60)
            # ★修正: デフォルトを60からNoneに変更
            add_goods_duration_val = safe_int(item.get("ADD_GOODS_DURATION"), None) 

            row = TimetableRow(
                project_id=project_id,
                sort_order=idx,
                artist_name=safe_str(item.get("ARTIST")),
                
                duration=duration_val,
                is_post_goods=bool(item.get("IS_POST_GOODS", False)),
                adjustment=adjustment_val,
                
                goods_start_time=safe_str(item.get("GOODS_START_MANUAL")),
                goods_duration=goods_duration_val,
                place=safe_str(item.get("PLACE")),
                
                add_goods_start_time=safe_str(item.get("ADD_GOODS_START")),
                add_goods_duration=add_goods_duration_val,
                add_goods_place=safe_str(item.get("ADD_GOODS_PLACE")),

                # ★追加: 非表示フラグを保存
                is_hidden=bool(item.get("IS_HIDDEN", False))
            )
            new_rows.append(row)
        
        db.add_all(new_rows)
        db.commit()
        return True
    except Exception as e:
        # ★エラーの詳細を画面に表示
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
                "ADD_GOODS_PLACE": r.add_goods_place,
                
                # ★追加: 非表示フラグを読み込み
                "IS_HIDDEN": getattr(r, "is_hidden", False)
            }
            data_export.append(item)
        return data_export
    except Exception as e:
        print(f"Error loading timetable rows: {e}")
        return []


# --- 読み込み処理 (既存) ---
def load_project_data(db, project_id):
    """
    DBからプロジェクト情報を取得し、st.session_state に展開する
    """
    proj = db.query(TimetableProject).filter(TimetableProject.id == project_id).first()
    if not proj:
        return False
    
    # 1. 基本情報
    st.session_state.proj_title = proj.title or ""
    st.session_state.proj_venue = proj.venue_name or ""
    st.session_state.proj_url = proj.venue_url or ""
    
    if proj.event_date:
        try:
            if isinstance(proj.event_date, (datetime.date, datetime.datetime)):
                st.session_state.proj_date = proj.event_date
            else:
                st.session_state.proj_date = datetime.datetime.strptime(str(proj.event_date), "%Y-%m-%d").date()
        except Exception:
            st.session_state.proj_date = None
    else:
        st.session_state.proj_date = None

    st.session_state.tt_open_time = format_time_safe(proj.open_time, "10:00")
    st.session_state.tt_start_time = format_time_safe(proj.start_time, "10:30")
    st.session_state.tt_goods_offset = proj.goods_start_offset or 0

    # 2. タイムテーブルデータのロード (DBテーブル優先、なければJSON)
    tt_data_from_db = load_timetable_rows(db, project_id)
    if tt_data_from_db:
        st.session_state.tt_data = tt_data_from_db
    else:
        # DBになければ旧JSONから
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
