import streamlit as st
import pandas as pd
import json
import datetime
from datetime import date
from database import TimetableProject
from utils import safe_int, safe_str
from constants import get_default_row_settings

# --- ヘルパー関数: 安全なJSON読み込み ---
def parse_json_safe(data, default_val):
    """
    SQLAlchemyがJSON型を自動変換する場合(List/Dict)と、
    文字列で返してくる場合の両方に対応する
    """
    if data is None:
        return default_val
    
    # すでにリストや辞書になっている場合（Supabase/Postgresの自動変換）
    if isinstance(data, (list, dict)):
        return data
    
    # 文字列の場合（SQLiteや、自動変換が無効な場合）
    if isinstance(data, str):
        try:
            return json.loads(data)
        except:
            return default_val
            
    return default_val

# --- 読み込み処理 ---
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
    
    # 日付変換 (String -> date)
    if proj.event_date:
        try:
            # 文字列型で来てもDate型で来ても対応できるようにする
            if isinstance(proj.event_date, (datetime.date, datetime.datetime)):
                st.session_state.proj_date = proj.event_date
            else:
                st.session_state.proj_date = datetime.datetime.strptime(str(proj.event_date), "%Y-%m-%d").date()
        except:
            st.session_state.proj_date = None
    else:
        st.session_state.proj_date = None

    # 時間
    # Time型オブジェクトか文字列かを考慮してセット
    st.session_state.tt_open_time = proj.open_time or "10:00"
    st.session_state.tt_start_time = proj.start_time or "10:30"
    st.session_state.tt_goods_offset = proj.goods_start_offset or 0

    # 2. JSONデータ (リスト/辞書系) - ★修正: parse_json_safe を使用
    
    # タイムテーブルデータ
    st.session_state.tt_data = parse_json_safe(proj.data_json, [])

    # グリッド順序・設定
    grid_data = parse_json_safe(proj.grid_order_json, {})
    if isinstance(grid_data, dict):
        st.session_state.grid_order = grid_data.get("order", [])
        st.session_state.grid_row_counts_str = grid_data.get("row_counts_str", "5,5,5,5,5")
        st.session_state.grid_alignment = grid_data.get("alignment", "中央揃え")
        st.session_state.grid_layout_mode = grid_data.get("layout_mode", "レンガ (サイズ統一)")
    else:
        # 古いデータ形式(単なるリスト)の場合のフォールバック
        st.session_state.grid_order = grid_data if isinstance(grid_data, list) else []

    # チケット情報
    st.session_state.proj_tickets = parse_json_safe(proj.tickets_json, [])

    # 自由記述
    st.session_state.proj_free_text = parse_json_safe(proj.free_text_json, [])

    # ★追加: チケット共通備考の読み込み
    # ここでエラーが起きていた可能性が高い箇所です
    st.session_state.proj_ticket_notes = parse_json_safe(proj.ticket_notes_json, [])
    
    # フライヤー設定の読み込み
    flyer_conf = parse_json_safe(proj.flyer_json, {})
    if flyer_conf:
        st.session_state.flyer_bg_id = int(flyer_conf.get("bg_id", 0))
        st.session_state.flyer_logo_id = int(flyer_conf.get("logo_id", 0))
        st.session_state.flyer_basic_font = flyer_conf.get("font", "keifont.ttf")
        st.session_state.flyer_text_color = flyer_conf.get("text_color", "#FFFFFF")
        st.session_state.flyer_stroke_color = flyer_conf.get("stroke_color", "#000000")

    return True

# --- 保存処理 (共通化) ---
def save_current_project(db, project_id):
    """
    現在のセッションステートの内容をデータベースに保存する
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
    # Supabaseの場合、Dict/Listをそのまま代入しても自動でJSON化してくれることが多いですが、
    # 安全のため json.dumps で文字列化して保存するのが最も確実です。
    if "proj_tickets" in st.session_state:
        proj.tickets_json = json.dumps(st.session_state.proj_tickets, ensure_ascii=False)
    if "proj_free_text" in st.session_state:
        proj.free_text_json = json.dumps(st.session_state.proj_free_text, ensure_ascii=False)
    
    # ★追加: チケット共通備考の保存
    if "proj_ticket_notes" in st.session_state:
        proj.ticket_notes_json = json.dumps(st.session_state.proj_ticket_notes, ensure_ascii=False)

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

    # フライヤー情報 (NEWデザイン用)
    flyer_data = {}
    keys = ["flyer_bg_id", "flyer_logo_id", "flyer_basic_font", "flyer_text_color", "flyer_stroke_color"]
    for k in keys:
        if k in st.session_state:
            short_key = k.replace("flyer_", "").replace("basic_", "")
            flyer_data[short_key] = st.session_state[k]
    
    # 既存のJSONがあればマージする
    if proj.flyer_json:
        try:
            # ここも読み込み時は安全策をとる
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
        ticket_notes_json=src.ticket_notes_json, # ★追加済み
        flyer_json=src.flyer_json,
        settings_json=src.settings_json
    )
    db.add(new_proj)
    db.commit()
    return new_proj
