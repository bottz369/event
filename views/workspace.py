import streamlit as st
from datetime import date
import json
from database import get_db, TimetableProject

# 各機能の読み込み
from views.timetable import render_timetable_page 
from views.grid import render_grid_page
from views.flyer import render_flyer_editor

def render_workspace_page():
    st.title("🚀 プロジェクト・ワークスペース")
    db = next(get_db())
    
    # 1. プロジェクト選択エリア
    projects = db.query(TimetableProject).all()
    projects.sort(key=lambda x: x.event_date or "0000-00-00", reverse=True)
    
    proj_map = {f"{p.event_date} {p.title}": p.id for p in projects}
    
    # 選択肢の作成
    options = ["(選択してください)", "➕ 新規プロジェクト作成"] + list(proj_map.keys())
    
    # セッションで選択中のプロジェクトを保持
    if "ws_active_project_id" not in st.session_state:
        st.session_state.ws_active_project_id = None

    # インデックス計算
    current_idx = 0
    if st.session_state.ws_active_project_id:
        current_val = next((k for k, v in proj_map.items() if v == st.session_state.ws_active_project_id), None)
        if current_val in options:
            current_idx = options.index(current_val)

    selected_label = st.selectbox("作業するプロジェクトを選択", options, index=current_idx)

    # --- A. 新規作成モード ---
    if selected_label == "➕ 新規プロジェクト作成":
        st.divider()
        st.subheader("✨ 新しいプロジェクトを作成")
        with st.form("ws_new_project"):
            c1, c2 = st.columns(2)
            with c1:
                p_date = st.date_input("開催日", value=date.today())
                p_title = st.text_input("イベント名")
            with c2:
                p_venue = st.text_input("会場名")
                p_url = st.text_input("会場URL")
            
            if st.form_submit_button("作成して開始", type="primary"):
                if p_title and p_venue:
                    new_proj = TimetableProject(
                        title=p_title,
                        event_date=p_date.strftime("%Y-%m-%d"),
                        venue_name=p_venue,
                        venue_url=p_url,
                        open_time="10:00", start_time="10:30"
                    )
                    db.add(new_proj)
                    db.commit()
                    # 作成したプロジェクトを選択状態にする
                    st.session_state.ws_active_project_id = new_proj.id
                    st.success("プロジェクトを作成しました！")
                    st.rerun()
                else:
                    st.error("イベント名と会場名は必須です")
        db.close()
        return

    # --- B. 未選択状態 ---
    if selected_label == "(選択してください)":
        st.info("👆 上のボックスからプロジェクトを選択するか、新規作成してください。")
        db.close()
        return

    # --- C. プロジェクト作業モード ---
    project_id = proj_map[selected_label]
    st.session_state.ws_active_project_id = project_id
    
    proj = db.query(TimetableProject).filter(TimetableProject.id == project_id).first()
    
    st.divider()
    st.markdown(f"### 📂 {proj.title} <small>({proj.event_date} @ {proj.venue_name})</small>", unsafe_allow_html=True)

    tab_tt, tab_grid, tab_flyer = st.tabs(["⏱️ タイムテーブル", "🖼️ アー写グリッド", "📑 フライヤーセット"])

    with tab_tt:
        st.session_state.tt_current_proj_id = project_id
        render_timetable_page()
    
    with tab_grid:
        st.session_state.current_grid_proj_id = project_id
        render_grid_page()

    with tab_flyer:
        render_flyer_editor(project_id)

    db.close()
