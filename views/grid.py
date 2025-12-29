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
    if "ws_active_project_id" not in st.session_state or st.session_state.ws_active_project_id is None:
        st.title("🖼️ アー写グリッド作成")

    db = next(get_db())
    
    if generate_grid_image is None:
        st.error("⚠️ `logic_grid.py` の読み込みに失敗しています。")

    try:
        selected_id = st.session_state.get("ws_active_project_id")
        
        # フォールバック
        if not selected_id:
            projects = db.query(TimetableProject).all()
            if projects:
                p_map = {f"{p.event_date} {p.title}": p.id for p in projects}
                sel_label = st.selectbox("プロジェクト選択", ["(選択)"] + list(p_map.keys()))
                if sel_label != "(選択)":
                    selected_id = p_map[sel_label]

        # セッション初期化
        if "grid_order" not in st.session_state: st.session_state.grid_order = []
        if "grid_cols" not in st.session_state: st.session_state.grid_cols = 5
        if "grid_rows" not in st.session_state: st.session_state.grid_rows = 5
        
        if selected_id:
            proj = db.query(TimetableProject).filter(TimetableProject.id == selected_id).first()
            
            # データ同期 (ロード済みでない場合)
            if not st.session_state.grid_order and proj and proj.data_json:
                try:
                    d = json.loads(proj.data_json)
                    tt_artists = [i["ARTIST"] for i in d if i["ARTIST"] not in ["開演前物販", "終演後物販"]]
                    st.session_state.grid_order = list(reversed(tt_artists))
                except: pass

            st.divider()
            
            # --- 設定エリア ---
            c_set1, c_set2, c_set3 = st.columns(3)
            
            # ★修正: value引数を削除し、keyだけで管理 (エラー回避)
            with c_set1: st.number_input("行数", min_value=1, key="grid_rows")
            with c_set2: st.number_input("列数", min_value=1, key="grid_cols")
            
            with c_set3: 
                if st.button("リセット (タイムテーブルから再読込)"):
                    if proj.data_json:
                        d = json.loads(proj.data_json)
                        st.session_state.grid_order = list(reversed([i["ARTIST"] for i in d if i["ARTIST"] not in ["開演前物販", "終演後物販"]]))
                        st.rerun()

            # --- 並び替えエリア ---
            st.caption("ドラッグ&ドロップで配置調整")
            if sort_items:
                grid_ui = []
                curr = 0
                rows = st.session_state.grid_rows
                cols = st.session_state.grid_cols
                
                for r in range(rows):
                    items = []
                    for c in range(cols):
                        if curr < len(st.session_state.grid_order):
                            items.append(st.session_state.grid_order[curr])
                            curr += 1
                    grid_ui.append({"header": f"行{r+1}", "items": items})
                
                while curr < len(st.session_state.grid_order):
                    grid_ui.append({"header": "予備", "items": [st.session_state.grid_order[curr]]})
                    curr += 1
                
                res = sort_items(grid_ui, multi_containers=True)
                new_flat = []
                for g in res: new_flat.extend(g["items"])
                
                if new_flat != st.session_state.grid_order:
                    st.session_state.grid_order = new_flat
                    st.rerun()

            st.divider()
            
            # --- 画像生成エリア ---
            c_gen1, c_gen2 = st.columns(2)
            with c_gen1:
                all_fonts = [f for f in os.listdir(FONT_DIR) if f.lower().endswith(".ttf")]
                if not all_fonts: all_fonts = ["keifont.ttf"]
                
                if "grid_font" not in st.session_state:
                    st.session_state.grid_font = all_fonts[0]
                
                # ★修正: ここも value/index を削除し key のみに
                st.selectbox("フォント", all_fonts, key="grid_font")
            
            with c_gen2:
                if st.button("🚀 グリッド画像を生成", type="primary"):
                    if generate_grid_image:
                        target_artists = []
                        missing_artists = []
                        for n in st.session_state.grid_order:
                            a = db.query(Artist).filter(Artist.name == n).first()
                            if a: target_artists.append(a)
                            else: missing_artists.append(n)
                        
                        if not target_artists:
                            st.warning("表示するアーティストデータがありません。")
                        else:
                            with st.spinner("生成中..."):
                                try:
                                    img = generate_grid_image(
                                        target_artists, IMAGE_DIR, 
                                        font_path=os.path.join(FONT_DIR, st.session_state.grid_font), 
                                        cols=st.session_state.grid_cols
                                    )
                                    if img:
                                        st.image(img, caption="プレビュー", use_container_width=True)
                                        b = io.BytesIO()
                                        img.save(b, format="PNG")
                                        st.download_button("画像をダウンロード", b.getvalue(), "grid.png", "image/png")
                                    else: st.error("生成失敗")
                                except Exception as e: st.error(f"エラー: {e}")
                    else: st.error("ロジックエラー")
    except Exception as main_e:
        st.error(f"予期せぬエラー: {main_e}")
    finally:
        db.close()
