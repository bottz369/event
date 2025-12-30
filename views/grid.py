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
        
        # --- (プロジェクト選択ロジック) ---
        if not selected_id:
            projects = db.query(TimetableProject).all()
            if projects:
                p_map = {f"{p.event_date} {p.title}": p.id for p in projects}
                sel_label = st.selectbox("プロジェクト選択", ["(選択)"] + list(p_map.keys()))
                if sel_label != "(選択)":
                    selected_id = p_map[sel_label]

        # セッション初期化
        if "grid_order" not in st.session_state: st.session_state.grid_order = []
        if "grid_rows" not in st.session_state: st.session_state.grid_rows = 5
        if "grid_base_cols" not in st.session_state: st.session_state.grid_base_cols = 5
        if "grid_row_counts_str" not in st.session_state: st.session_state.grid_row_counts_str = "5,5,5,5,5"
        if "grid_alignment" not in st.session_state: st.session_state.grid_alignment = "中央揃え"
        if "grid_layout_mode" not in st.session_state: st.session_state.grid_layout_mode = "レンガ (サイズ統一)"
        
        # ★追加: 生成時の設定を保存する変数を初期化
        if "grid_last_generated_params" not in st.session_state: st.session_state.grid_last_generated_params = None
        
        if selected_id:
            proj = db.query(TimetableProject).filter(TimetableProject.id == selected_id).first()
            
            # 初回ロード
            if not st.session_state.grid_order and proj and proj.data_json:
                try:
                    d = json.loads(proj.data_json)
                    tt_artists = [i["ARTIST"] for i in d if i["ARTIST"] not in ["開演前物販", "終演後物販"]]
                    st.session_state.grid_order = list(reversed(tt_artists))
                except: pass

            st.divider()
            
            # --- 設定エリア ---
            c_set1, c_set2 = st.columns([1, 2])
            
            with c_set1: 
                new_rows = st.number_input("行数", min_value=1, key="grid_rows")
                
            with c_set2:
                if st.button("リセット (タイムテーブルから再読込)", key="btn_grid_reset"):
                    if proj.data_json:
                        d = json.loads(proj.data_json)
                        st.session_state.grid_order = list(reversed([i["ARTIST"] for i in d if i["ARTIST"] not in ["開演前物販", "終演後物販"]]))
                        st.rerun()

            # --- 行ごとの枚数設定 ---
            current_counts = []
            try:
                current_counts = [int(x.strip()) for x in st.session_state.grid_row_counts_str.split(",") if x.strip()]
            except:
                current_counts = [5] * new_rows

            if len(current_counts) < new_rows:
                current_counts += [5] * (new_rows - len(current_counts))
            elif len(current_counts) > new_rows:
                current_counts = current_counts[:new_rows]
            
            st.session_state.grid_row_counts_str = ",".join(map(str, current_counts))

            st.text_input(
                "各行の枚数設定 (カンマ区切り)", 
                key="grid_row_counts_str_input", 
                value=st.session_state.grid_row_counts_str,
                help="例: 3,4,6 と入力すると、1行目3枚、2行目4枚、3行目6枚になります。"
            )
            
            st.session_state.grid_row_counts_str = st.session_state.grid_row_counts_str_input

            try:
                parsed_counts = [int(x.strip()) for x in st.session_state.grid_row_counts_str.split(",") if x.strip()]
            except:
                st.error("数値とカンマで入力してください")
                parsed_counts = [5] * new_rows

            # --- レイアウト詳細設定 ---
            with st.expander("📐 レイアウト調整 (揃え・モード)", expanded=True):
                c_lay1, c_lay2 = st.columns(2)
                with c_lay1:
                    st.radio(
                        "配置モード", 
                        ["レンガ (サイズ統一)", "両端揃え (拡大縮小)"], 
                        key="grid_layout_mode",
                        horizontal=True
                    )
                with c_lay2:
                    disabled = (st.session_state.grid_layout_mode == "両端揃え (拡大縮小)")
                    st.radio(
                        "行の配置 (レンガモード時)", 
                        ["左揃え", "中央揃え", "右揃え"], 
                        key="grid_alignment",
                        horizontal=True,
                        disabled=disabled
                    )

            # --- 並び替えエリア ---
            st.caption("ドラッグ&ドロップで配置調整")
            
            order_changed = False
            
            if sort_items:
                grid_ui = []
                curr = 0
                
                for r_idx, count in enumerate(parsed_counts):
                    items = []
                    for c in range(count):
                        if curr < len(st.session_state.grid_order):
                            items.append(st.session_state.grid_order[curr])
                            curr += 1
                    grid_ui.append({"header": f"行{r_idx+1} ({len(items)}/{count})", "items": items})
                
                while curr < len(st.session_state.grid_order):
                    grid_ui.append({"header": "予備", "items": [st.session_state.grid_order[curr]]})
                    curr += 1
                
                res = sort_items(grid_ui, multi_containers=True)
                new_flat = []
                for g in res: new_flat.extend(g["items"])
                
                if new_flat != st.session_state.grid_order:
                    st.session_state.grid_order = new_flat
                    order_changed = True

            if order_changed:
                st.rerun()

            st.divider()
            
            # --- 画像生成・プレビューエリア ---
            all_fonts = [f for f in os.listdir(FONT_DIR) if f.lower().endswith(".ttf")]
            if not all_fonts: all_fonts = ["keifont.ttf"]
            
            if "grid_font" not in st.session_state: st.session_state.grid_font = all_fonts[0]
            st.selectbox("プレビュー用フォント", all_fonts, key="grid_font")
            
            # =================================================================
            # ★現在の設定値をまとめる（変更検知用）
            # =================================================================
            current_params = {
                "order": st.session_state.grid_order,
                "row_counts": st.session_state.grid_row_counts_str,
                "layout_mode": st.session_state.grid_layout_mode,
                "alignment": st.session_state.grid_alignment,
                "font": st.session_state.grid_font,
                "rows": st.session_state.grid_rows
            }
            # =================================================================

            if st.button("🔄 設定反映 (プレビュー生成)", type="primary", use_container_width=True, key="btn_grid_generate"):
                if generate_grid_image:
                    target_artists = []
                    for n in st.session_state.grid_order:
                        a = db.query(Artist).filter(Artist.name == n).first()
                        if a: target_artists.append(a)
                    
                    if not target_artists:
                        st.warning("表示するアーティストデータがありません。")
                    else:
                        with st.spinner("画像を生成中..."):
                            try:
                                is_brick = (st.session_state.grid_layout_mode == "レンガ (サイズ統一)")
                                align_map = {"左揃え": "left", "中央揃え": "center", "右揃え": "right"}
                                align_val = align_map.get(st.session_state.grid_alignment, "center")

                                img = generate_grid_image(
                                    target_artists, 
                                    IMAGE_DIR, 
                                    font_path=os.path.join(FONT_DIR, st.session_state.grid_font), 
                                    row_counts=parsed_counts, 
                                    is_brick_mode=is_brick,
                                    alignment=align_val
                                )
                                
                                if img:
                                    st.session_state.last_generated_grid_image = img
                                    # ★生成成功時に、現在の設定を「最終生成設定」として保存
                                    st.session_state.grid_last_generated_params = current_params
                                    st.toast("プレビューを更新しました！", icon="✅")
                                else:
                                    st.error("生成失敗")
                            except Exception as e:
                                st.error(f"プレビュー生成エラー: {e}")
                else:
                    st.error("ロジックエラー")

            # =================================================================
            # ★判定ロジック: 現在の設定と、最後に生成した時の設定が一致するか？
            # =================================================================
            is_outdated = False
            
            # まだ一度も生成していない場合
            if st.session_state.get("grid_last_generated_params") is None:
                is_outdated = True
            # 生成後に何か変更があった場合
            elif st.session_state.grid_last_generated_params != current_params:
                is_outdated = True
            
            # --- 表示切り替え ---
            if is_outdated:
                # 変更がある場合: 画像を隠して赤字で警告
                st.markdown("""
                    <div style="background-color: #ffebee; border: 1px solid #ef5350; padding: 10px; border-radius: 5px; text-align: center; color: #c62828; font-weight: bold;">
                        ⚠️ 設定が変更されています。<br>
                        プレビューを更新するには、上の「設定反映」ボタンを押してください。
                    </div>
                """, unsafe_allow_html=True)
            elif st.session_state.get("last_generated_grid_image"):
                # 最新の場合: 画像を表示
                st.caption("👇 現在のプレビュー")
                st.image(st.session_state.last_generated_grid_image, use_container_width=True)

    except Exception as main_e:
        st.error(f"予期せぬエラー: {main_e}")
    finally:
        db.close()
