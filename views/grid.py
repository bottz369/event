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
        st.error("⚠️ `logic_grid.py` の読み込みに失敗しています。`requirements.txt` に `opencv-python-headless` が含まれているか、またはコードにエラーがないか確認してください。")

    try:
        # プロジェクトIDの取得 (基本的にはワークスペースから渡される)
        selected_id = st.session_state.get("ws_active_project_id")
        
        # 単独起動時のフォールバック (念のため)
        if not selected_id:
            projects = db.query(TimetableProject).all()
            if projects:
                p_map = {f"{p.event_date} {p.title}": p.id for p in projects}
                sel_label = st.selectbox("プロジェクト選択", ["(選択)"] + list(p_map.keys()))
                if sel_label != "(選択)":
                    selected_id = p_map[sel_label]

        # セッション初期化 (リセットされないようにチェック)
        if "grid_order" not in st.session_state: st.session_state.grid_order = []
        if "grid_cols" not in st.session_state: st.session_state.grid_cols = 5
        if "grid_rows" not in st.session_state: st.session_state.grid_rows = 5
        
        # --- メイン処理 ---
        if selected_id:
            proj = db.query(TimetableProject).filter(TimetableProject.id == selected_id).first()
            
            # データの同期確認 (まだロードされていない、または空の場合)
            if not st.session_state.grid_order and proj.data_json:
                # タイムテーブルデータから初期化を試みる
                try:
                    d = json.loads(proj.data_json)
                    tt_artists = [i["ARTIST"] for i in d if i["ARTIST"] not in ["開演前物販", "終演後物販"]]
                    st.session_state.grid_order = list(reversed(tt_artists))
                except: pass

            st.divider()
            
            # --- 設定エリア ---
            c_set1, c_set2, c_set3 = st.columns(3)
            with c_set1: st.number_input("行数", min_value=1, value=st.session_state.grid_rows, key="grid_rows")
            with c_set2: st.number_input("列数", min_value=1, value=st.session_state.grid_cols, key="grid_cols")
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
                for r in range(st.session_state.grid_rows):
                    items = []
                    for c in range(st.session_state.grid_cols):
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
                
                # 初期値設定
                f_idx = 0
                if "grid_font" in st.session_state and st.session_state.grid_font in all_fonts:
                    f_idx = all_fonts.index(st.session_state.grid_font)
                
                st.selectbox("フォント", all_fonts, index=f_idx, key="grid_font")
            
            with c_gen2:
                if st.button("🚀 グリッド画像を生成", type="primary"):
                    if generate_grid_image:
                        target_artists = []
                        missing_artists = []
                        
                        for n in st.session_state.grid_order:
                            a = db.query(Artist).filter(Artist.name == n).first()
                            if a: 
                                target_artists.append(a)
                            else:
                                missing_artists.append(n)
                        
                        if not target_artists:
                            st.warning("表示するアーティストデータがありません。")
                        else:
                            with st.spinner("生成中..."):
                                try:
                                    img = generate_grid_image(
                                        target_artists, 
                                        IMAGE_DIR, 
                                        font_path=os.path.join(FONT_DIR, st.session_state.grid_font), 
                                        cols=st.session_state.grid_cols
                                    )
                                    
                                    if img:
                                        st.image(img, caption="プレビュー", use_container_width=True)
                                        b = io.BytesIO()
                                        img.save(b, format="PNG")
                                        st.download_button("画像をダウンロード", b.getvalue(), "grid.png", "image/png")
                                    else:
                                        st.error("画像の生成に失敗しました（結果がNoneでした）。")
                                        
                                except Exception as e:
                                    st.error(f"生成中にエラーが発生しました: {e}")
                                    st.exception(e)
                    else:
                        st.error("ロジックファイル (logic_grid.py) が読み込まれていないため実行できません。")
    
    except Exception as main_e:
        st.error(f"予期せぬエラー: {main_e}")
    
    finally:
        db.close()
