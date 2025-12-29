import streamlit as st
import os
import json
import io
from database import get_db, TimetableProject, Artist, IMAGE_DIR
from constants import FONT_DIR

try:
    from streamlit_sortables import sort_items
except ImportError:
    sort_items = None

try:
    from logic_grid import generate_grid_image
except ImportError:
    generate_grid_image = None

def render_grid_page():
    st.title("🖼️ アー写グリッド作成")
    db = next(get_db())
    
    if generate_grid_image is None:
        st.error("⚠️ `logic_grid.py` の読み込みに失敗しています。")

    try:
        projects = db.query(TimetableProject).all()
        projects.sort(key=lambda x: x.event_date or "0000-00-00", reverse=True)
        
        col_g1, col_g2 = st.columns([3, 1])
        with col_g1:
            p_map = {f"{p.event_date} {p.title}": p.id for p in projects}
            sel_label = st.selectbox("プロジェクト選択", ["(選択)"] + list(p_map.keys()))
        
        # セッション初期化
        if "grid_order" not in st.session_state: st.session_state.grid_order = []
        if "grid_cols" not in st.session_state: st.session_state.grid_cols = 5
        if "grid_rows" not in st.session_state: st.session_state.grid_rows = 5
        
        if sel_label != "(選択)":
            proj_id = p_map[sel_label]
            proj = db.query(TimetableProject).filter(TimetableProject.id == proj_id).first()
            
            # プロジェクト変更時にデータをロード (中略: 元のコードのロードロジック)
            if "current_grid_proj_id" not in st.session_state or st.session_state.current_grid_proj_id != proj_id:
                # ... データロード処理 ...
                # (元のコードの if "current_grid_proj_id" ... ブロックの中身を入れてください)
                pass # ここに元のコードを入れてください

            st.divider()
            
            # --- 設定エリア ---
            c_set1, c_set2, c_set3 = st.columns(3)
            with c_set1: st.session_state.grid_rows = st.number_input("行数", min_value=1, value=st.session_state.grid_rows)
            with c_set2: st.session_state.grid_cols = st.number_input("列数", min_value=1, value=st.session_state.grid_cols)
            # ... (中略: 並び替えUI、画像生成UI) ...
            
            # 元のコードのUI描画部分をすべて記述
            
    except Exception as main_e:
        st.error(f"予期せぬエラー: {main_e}")
    finally:
        db.close()
