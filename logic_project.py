import streamlit as st
import pandas as pd
import json
from datetime import date
from database import TimetableProject
from utils import safe_int, safe_str
from constants import get_default_row_settings  # ★修正: ここからインポート

# --- 保存処理 (共通化) ---
def save_current_project(db, project_id):
    """
    現在のセッションステートの内容をデータベースに保存する
    """
    proj = db.query(TimetableProject).filter(TimetableProject.id == project_id).first()
    if not proj: return False
    
    # 基本情報
    if "proj_title" in st.session_state: proj.title = st.session_state.proj_title
    if "proj_date" in st.session_state: proj.event_date = st.session_state.proj_date.strftime("%Y-%m-%d")
    if "proj_venue" in st.session_state: proj.venue_name = st.session_state.proj_venue
    if "proj_url" in st.session_state: proj.venue_url = st.session_state.proj_url
    
    # JSONデータ
    if "proj_tickets" in st.session_state:
        proj.tickets_json = json.dumps(st.session_state.proj_tickets, ensure_ascii=False)
    if "proj_free_text" in st.session_state:
        proj.free_text_json = json.dumps(st.session_state.proj_free_text, ensure_ascii=False)

    # タイムテーブルデータ
    save_data = []
    # 優先: binding_df が存在して空でない場合
    if "binding_df" in st.session_state and not st.session_state.binding_df.empty:
        save_data = st.session_state.binding_df.to_dict(orient="records")
    
    # フォールバック: セッション変数から再構築
    elif "tt_artists_order" in st.session_state and st.session_state.tt_artists_order:
        # 開演前物販
        if st.session_state.get("tt_has_pre_goods"):
            p = st.session_state.get("tt_pre_goods_settings", {})
            save_data.append({
                "ARTIST": "開演前物販", "DURATION": 0, "ADJUSTMENT": 0, "IS_POST_GOODS": False,
                "GOODS_START_MANUAL": safe_str(p.get("GOODS_START_MANUAL")), "GOODS_DURATION": safe_int(p.get("GOODS_DURATION"), 60), "PLACE": "",
                "ADD_GOODS_START": "", "ADD_GOODS_DURATION": None, "ADD_GOODS_PLACE": ""
            })
        
        # アーティスト
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
            
        # 終演後物販
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
    
    if "tt_open_time" in st.session_state: proj.open_time = st.session_state.tt_open_time
    if "tt_start_time" in st.session_state: proj.start_time = st.session_state.tt_start_time
    if "tt_goods_offset" in st.session_state: proj.goods_start_offset = st.session_state.tt_goods_offset

    # グリッド情報
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

    # 設定関連
    settings = {
        "tt_font": st.session_state.get("tt_font", "keifont.ttf"),
        "grid_font": st.session_state.get("grid_font", "keifont.ttf")
    }
    proj.settings_json = json.dumps(settings, ensure_ascii=False)

    # フライヤー情報
    flyer_data = {}
    keys = ["flyer_logo_id", "flyer_bg_id", "flyer_sub_title", "flyer_input_1", 
            "flyer_bottom_left", "flyer_bottom_right", "flyer_font", "flyer_text_color", "flyer_stroke_color"]
    for k in keys:
        if k in st.session_state:
            flyer_data[k.replace("flyer_", "")] = st.session_state[k]
    
    proj.flyer_json = json.dumps(flyer_data, ensure_ascii=False)
    
    db.commit()
    return True

# --- 複製処理 ---
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
        flyer_json=src.flyer_json,
        settings_json=src.settings_json
    )
    db.add(new_proj)
    db.commit()
    return new_proj
