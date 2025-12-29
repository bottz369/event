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
    # ★変更: タイトルはワークスペースで出してるので、単独起動時のみ表示
    if "ws_active_project_id" not in st.session_state or st.session_state.ws_active_project_id is None:
        st.title("🖼️ アー写グリッド作成")

    db = next(get_db())
    
    if generate_grid_image is None:
        st.error("⚠️ `logic_grid.py` の読み込みに失敗しています。`requirements.txt` に `opencv-python-headless` が含まれているか、またはコードにエラーがないか確認してください。")

    try:
        # --- プロジェクト選択ロジック ---
        selected_id = None
        
        # パターンA: ワークスペースからIDが渡されている場合
        if "ws_active_project_id" in st.session_state and st.session_state.ws_active_project_id:
            selected_id = st.session_state.ws_active_project_id
            
        # パターンB: 単独起動で、ユーザーがセレクトボックスから選ぶ場合
        else:
            projects = db.query(TimetableProject).all()
            projects.sort(key=lambda x: x.event_date or "0000-00-00", reverse=True)
            
            col_g1, col_g2 = st.columns([3, 1])
            with col_g1:
                p_map = {f"{p.event_date} {p.title}": p.id for p in projects}
                sel_label = st.selectbox("プロジェクト選択", ["(選択)"] + list(p_map.keys()))
            
            if sel_label != "(選択)":
                selected_id = p_map[sel_label]

        # セッション初期化
        if "grid_order" not in st.session_state: st.session_state.grid_order = []
        if "grid_cols" not in st.session_state: st.session_state.grid_cols = 5
        if "grid_rows" not in st.session_state: st.session_state.grid_rows = 5
        
        # --- データロード & メイン処理 ---
        if selected_id:
            proj = db.query(TimetableProject).filter(TimetableProject.id == selected_id).first()
            
            # プロジェクト変更時にデータをロード
            if "current_grid_proj_id" not in st.session_state or st.session_state.current_grid_proj_id != selected_id:
                # タイムテーブルからアーティスト名を抽出
                tt_artists = []
                if proj.data_json:
                    try:
                        d = json.loads(proj.data_json)
                        tt_artists = [i["ARTIST"] for i in d if i["ARTIST"] not in ["開演前物販", "終演後物販"]]
                    except: pass
                
                # 保存済みグリッド設定があればロード
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
                
                # リストのマージ（保存済み + 新規追加分）
                if saved_order:
                    merged = [n for n in saved_order if n in tt_artists]
                    for n in tt_artists:
                        if n not in merged: merged.append(n)
                    st.session_state.grid_order = merged
                else:
                    st.session_state.grid_order = list(reversed(tt_artists))
                
                st.session_state.current_grid_proj_id = selected_id
                
                # ワークスペース以外で選択変更があった場合のみrerun
                if "ws_active_project_id" not in st.session_state:
                    st.rerun()

            st.divider()
            
            # --- 設定エリア ---
            c_set1, c_set2, c_set3 = st.columns(3)
            with c_set1: st.session_state.grid_rows = st.number_input("行数", min_value=1, value=st.session_state.grid_rows)
            with c_set2: st.session_state.grid_cols = st.number_input("列数", min_value=1, value=st.session_state.grid_cols)
            with c_set3: 
                if st.button("リセット"):
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

            if st.button("💾 配置を保存"):
                save_d = {"cols": st.session_state.grid_cols, "rows": st.session_state.grid_rows, "order": st.session_state.grid_order}
                proj.grid_order_json = json.dumps(save_d, ensure_ascii=False)
                db.commit()
                st.success("保存しました")

            st.divider()
            
            # --- 画像生成エリア ---
            c_gen1, c_gen2 = st.columns(2)
            with c_gen1:
                af = [f for f in os.listdir(FONT_DIR) if f.lower().endswith(".ttf")]
                if not af: af = ["keifont.ttf"]
                sf = st.selectbox("フォント", af, key="grid_font")
            
            with c_gen2:
                if st.button("🚀 グリッド画像を生成", type="primary"):
                    if generate_grid_image:
                        # 対象アーティストのデータ収集
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
                                        font_path=os.path.join(FONT_DIR, sf), 
                                        cols=st.session_state.grid_cols
                                    )
                                    
                                    if img:
                                        st.image(img, caption="プレビュー", use_container_width=True)
                                        b = io.BytesIO()
                                        img.save(b, format="PNG")
                                        st.download_button("画像をダウンロード", b.getvalue(), "grid.png", "image/png")
                                    else:
                                        st.error("画像の生成に失敗しました（結果がNoneでした）。コンソールログを確認してください。")
                                        
                                except Exception as e:
                                    st.error(f"生成中にエラーが発生しました: {e}")
                                    st.exception(e)
                    else:
                        st.error("ロジックファイル (logic_grid.py) が読み込まれていないため実行できません。")
    
    except Exception as main_e:
        st.error(f"予期せぬエラー: {main_e}")
    
    finally:
        db.close()
