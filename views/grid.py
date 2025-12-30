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
        # 基本の列数（最大幅の基準として使用）
        if "grid_base_cols" not in st.session_state: st.session_state.grid_base_cols = 5
        
        # ★追加: 行ごとの枚数設定（文字列で管理）
        if "grid_row_counts_str" not in st.session_state: st.session_state.grid_row_counts_str = "5,5,5,5,5"
        # ★追加: 配置・揃え設定
        if "grid_alignment" not in st.session_state: st.session_state.grid_alignment = "中央揃え"
        if "grid_layout_mode" not in st.session_state: st.session_state.grid_layout_mode = "レンガ (サイズ統一)"
        
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
                # 行数を変えたら、設定文字列も連動して増減させる
                new_rows = st.number_input("行数", min_value=1, key="grid_rows")
                
            with c_set2:
                # リセットボタン
                if st.button("リセット (タイムテーブルから再読込)"):
                    if proj.data_json:
                        d = json.loads(proj.data_json)
                        st.session_state.grid_order = list(reversed([i["ARTIST"] for i in d if i["ARTIST"] not in ["開演前物販", "終演後物販"]]))
                        st.rerun()

            # --- ★重要: 行ごとの枚数設定 ---
            # 行数が変わった場合、input文字列のデフォルト値を調整するロジック
            current_counts = []
            try:
                current_counts = [int(x.strip()) for x in st.session_state.grid_row_counts_str.split(",") if x.strip()]
            except:
                current_counts = [5] * new_rows

            # 行数が足りない場合は足し、多い場合は切る
            if len(current_counts) < new_rows:
                current_counts += [5] * (new_rows - len(current_counts))
            elif len(current_counts) > new_rows:
                current_counts = current_counts[:new_rows]
            
            # UIに反映させる値を更新
            st.session_state.grid_row_counts_str = ",".join(map(str, current_counts))

            st.text_input(
                "各行の枚数設定 (カンマ区切り)", 
                key="grid_row_counts_str", 
                help="例: 3,4,6 と入力すると、1行目3枚、2行目4枚、3行目6枚になります。"
            )

            # パースしてリスト化（ロジックに渡す用）
            try:
                parsed_counts = [int(x.strip()) for x in st.session_state.grid_row_counts_str.split(",") if x.strip()]
            except:
                st.error("数値とカンマで入力してください")
                parsed_counts = [5] * new_rows

            # 最大列数を計算（キャンバス幅の基準）
            max_col_in_config = max(parsed_counts) if parsed_counts else 5

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
                    # レンガモードの時だけ意味がある
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
                
                # 指定された枚数に従ってバケツ（行）を作る
                for r_idx, count in enumerate(parsed_counts):
                    items = []
                    for c in range(count):
                        if curr < len(st.session_state.grid_order):
                            items.append(st.session_state.grid_order[curr])
                            curr += 1
                    grid_ui.append({"header": f"行{r_idx+1} ({len(items)}/{count})", "items": items})
                
                # 余ったアーティストがいれば予備へ
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
            
            if generate_grid_image:
                target_artists = []
                for n in st.session_state.grid_order:
                    a = db.query(Artist).filter(Artist.name == n).first()
                    if a: target_artists.append(a)
                
                if not target_artists:
                    st.warning("表示するアーティストデータがありません。")
                else:
                    try:
                        is_brick = (st.session_state.grid_layout_mode == "レンガ (サイズ統一)")
                        
                        # 揃え位置を英語に変換
                        align_map = {"左揃え": "left", "中央揃え": "center", "右揃え": "right"}
                        align_val = align_map.get(st.session_state.grid_alignment, "center")

                        img = generate_grid_image(
                            target_artists, 
                            IMAGE_DIR, 
                            font_path=os.path.join(FONT_DIR, st.session_state.grid_font), 
                            row_counts=parsed_counts, # ★リストを渡す
                            is_brick_mode=is_brick,
                            alignment=align_val       # ★揃え指定を渡す
                        )
                        
                        if img:
                            st.session_state.last_generated_grid_image = img
                            st.caption("👇 現在のプレビュー")
                            st.image(img, use_container_width=True)
                        else:
                            st.error("生成失敗")
                    except Exception as e:
                        st.error(f"プレビュー生成エラー: {e}")

    except Exception as main_e:
        st.error(f"予期せぬエラー: {main_e}")
    finally:
        db.close()
