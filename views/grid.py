import streamlit as st
import os
import json
import io
import requests # ★追加: URLダウンロード用

# Asset, AssetFile, get_image_url をインポート
from database import get_db, TimetableProject, Artist, IMAGE_DIR, Asset, AssetFile, get_image_url
from constants import FONT_DIR
from logic_project import save_current_project
from utils import create_font_specimen_img, get_sorted_font_list

try:
    from streamlit_sortables import sort_items
except ImportError:
    sort_items = None

try:
    from logic_grid import generate_grid_image
except ImportError:
    generate_grid_image = None

# --- ★修正: フォント確保関数 (URL対応版) ---
def check_and_download_font(db, font_filename):
    """
    指定されたフォントファイルがローカルになければ、
    1. Assetテーブル (Storage URL)
    2. AssetFileテーブル (Binary)
    の順で検索してダウンロードする
    """
    if not font_filename: return

    # パスズレ防止のため絶対パスを使用
    abs_font_dir = os.path.abspath(FONT_DIR)
    os.makedirs(abs_font_dir, exist_ok=True)
    
    file_path = os.path.join(abs_font_dir, font_filename)

    # すでに有効なファイルがあればOK
    if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
        return

    # 1. Assetテーブル (Storage URL) から取得を試みる
    try:
        asset = db.query(Asset).filter(Asset.image_filename == font_filename).first()
        if asset:
            url = get_image_url(asset.image_filename)
            if url:
                response = requests.get(url, timeout=10)
                if response.status_code == 200:
                    with open(file_path, "wb") as f:
                        f.write(response.content)
                    st.toast(f"フォント(URL)を準備しました: {font_filename}", icon="🔤")
                    return
    except Exception as e:
        print(f"URL Download Error: {e}")

    # 2. AssetFileテーブル (Binary) から取得を試みる (予備)
    try:
        asset_file = db.query(AssetFile).filter(AssetFile.filename == font_filename).first()
        if asset_file and asset_file.file_data:
            with open(file_path, "wb") as f:
                f.write(asset_file.file_data)
            st.toast(f"フォント(DB)を準備しました: {font_filename}", icon="🔤")
            return
    except Exception as e:
        print(f"Binary Write Error: {e}")

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
                projects.sort(key=lambda x: x.event_date or "0000-00-00", reverse=True)
                p_map = {f"{p.event_date} {p.title}": p.id for p in projects}
                sel_label = st.selectbox("プロジェクト選択", ["(選択)"] + list(p_map.keys()))
                if sel_label != "(選択)":
                    selected_id = p_map[sel_label]

        # セッション初期化 (デフォルト値)
        if "grid_order" not in st.session_state: st.session_state.grid_order = []
        if "grid_rows" not in st.session_state: st.session_state.grid_rows = 5
        
        if "grid_row_counts_str" not in st.session_state: st.session_state.grid_row_counts_str = "5,5,5,5,5"
        if "grid_alignment" not in st.session_state: st.session_state.grid_alignment = "中央揃え"
        if "grid_layout_mode" not in st.session_state: st.session_state.grid_layout_mode = "レンガ (サイズ統一)"
        if "grid_font" not in st.session_state: st.session_state.grid_font = "keifont.ttf"
        if "grid_last_generated_params" not in st.session_state: st.session_state.grid_last_generated_params = None
        
        if selected_id:
            proj = db.query(TimetableProject).filter(TimetableProject.id == selected_id).first()
            
            # --- DBからの設定復元ロジック ---
            if proj:
                # 1. アーティストリストの初期化
                if not st.session_state.grid_order and proj.data_json:
                    try:
                        d = json.loads(proj.data_json)
                        tt_artists = [i["ARTIST"] for i in d if i["ARTIST"] not in ["開演前物販", "終演後物販"]]
                        st.session_state.grid_order = list(dict.fromkeys(reversed(tt_artists)))
                    except: pass
                
                # 2. グリッド設定の復元
                if "grid_settings_loaded" not in st.session_state or st.session_state.get("current_proj_id_check") != selected_id:
                    if proj.settings_json:
                        try:
                            settings = json.loads(proj.settings_json)
                            grid_conf = settings.get("grid_settings", {})
                            if grid_conf:
                                st.session_state.grid_order = grid_conf.get("order", st.session_state.grid_order)
                                st.session_state.grid_rows = grid_conf.get("rows", 5)
                                st.session_state.grid_row_counts_str = grid_conf.get("row_counts", "5,5,5,5,5")
                                st.session_state.grid_layout_mode = grid_conf.get("layout_mode", "レンガ (サイズ統一)")
                                st.session_state.grid_alignment = grid_conf.get("alignment", "中央揃え")
                                st.session_state.grid_font = grid_conf.get("font", "keifont.ttf")
                        except Exception as e:
                            print(f"Settings load error: {e}")
                    
                    st.session_state.grid_settings_loaded = True
                    st.session_state.current_proj_id_check = selected_id


            st.divider()
            
            # --- 設定エリア ---
            c_set1, c_set2 = st.columns([1, 2])
            with c_set1: 
                new_rows = st.number_input("行数", min_value=1, key="grid_rows")
            with c_set2:
                if st.button("リセット (タイムテーブルから再読込)", key="btn_grid_reset"):
                    if proj.data_json:
                        d = json.loads(proj.data_json)
                        tt_artists = [i["ARTIST"] for i in d if i["ARTIST"] not in ["開演前物販", "終演後物販"]]
                        st.session_state.grid_order = list(dict.fromkeys(reversed(tt_artists)))
                        # 設定もリセット
                        st.session_state.grid_rows = 5
                        st.session_state.grid_row_counts_str = "5,5,5,5,5"
                        st.session_state.grid_font = "keifont.ttf"
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
            
            # 入力欄とセッション変数の同期
            st.session_state.grid_row_counts_str = ",".join(map(str, current_counts))

            row_counts_input = st.text_input(
                "各行の枚数設定 (カンマ区切り)", 
                value=st.session_state.grid_row_counts_str,
                help="例: 3,4,6 と入力すると、1行目3枚、2行目4枚、3行目6枚になります。",
                key="grid_row_counts_input_widget"
            )
            # 入力値をセッションに反映
            st.session_state.grid_row_counts_str = row_counts_input
            
            try:
                parsed_counts = [int(x.strip()) for x in st.session_state.grid_row_counts_str.split(",") if x.strip()]
            except:
                st.error("数値とカンマで入力してください")
                parsed_counts = [5] * new_rows

            # --- レイアウト詳細設定 ---
            with st.expander("📐 レイアウト調整 (揃え・モード)", expanded=True):
                c_lay1, c_lay2 = st.columns(2)
                with c_lay1:
                    st.radio("配置モード", ["レンガ (サイズ統一)", "両端揃え (拡大縮小)"], key="grid_layout_mode", horizontal=True)
                with c_lay2:
                    disabled = (st.session_state.grid_layout_mode == "両端揃え (拡大縮小)")
                    st.radio("行の配置 (レンガモード時)", ["左揃え", "中央揃え", "右揃え"], key="grid_alignment", horizontal=True, disabled=disabled)

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

            if order_changed: st.rerun()

            st.divider()
            
            # --- 画像生成・プレビューエリア ---
            sorted_fonts = get_sorted_font_list(db)
            font_file_list = [item["filename"] for item in sorted_fonts]
            font_display_map = {item["filename"]: item["name"] for item in sorted_fonts}
            
            if not font_file_list:
                font_file_list = ["keifont.ttf"]
                font_display_map = {"keifont.ttf": "標準フォント (未設定)"}

            # フォント選択状態の確保
            if st.session_state.grid_font not in font_file_list:
                st.session_state.grid_font = font_file_list[0]

            # 見本表示
            with st.expander("🔤 フォント一覧見本を表示"):
                with st.container(height=300):
                    specimen_list = sorted(sorted_fonts, key=lambda x: x["filename"].lower())
                    specimen_img = create_font_specimen_img(db, specimen_list)
                    if specimen_img:
                        st.image(specimen_img, use_container_width=True)
                    else:
                        st.info("フォントが見つかりません。")

            # フォント選択
            st.selectbox(
                "プレビュー用フォント", 
                font_file_list,
                format_func=lambda x: font_display_map.get(x, x),
                key="grid_font" 
            )
            
            # 現在の設定パラメータ
            current_params = {
                "order": st.session_state.grid_order,
                "row_counts": st.session_state.grid_row_counts_str,
                "layout_mode": st.session_state.grid_layout_mode,
                "alignment": st.session_state.grid_alignment,
                "font": st.session_state.grid_font,
                "rows": st.session_state.grid_rows
            }

            # 自動生成ロジック (初回のみ)
            if st.session_state.get("last_generated_grid_image") is None:
                if generate_grid_image:
                    target_artists = []
                    for n in st.session_state.grid_order:
                        a = db.query(Artist).filter(Artist.name == n).first()
                        if a: target_artists.append(a)
                    
                    if target_artists:
                        try:
                            # ★フォント確保
                            check_and_download_font(db, st.session_state.grid_font)

                            is_brick = (st.session_state.grid_layout_mode == "レンガ (サイズ統一)")
                            align_map = {"左揃え": "left", "中央揃え": "center", "右揃え": "right"}
                            align_val = align_map.get(st.session_state.grid_alignment, "center")

                            # 絶対パス生成
                            abs_font_path = os.path.join(os.path.abspath(FONT_DIR), st.session_state.grid_font)
                            
                            auto_img = generate_grid_image(
                                target_artists, IMAGE_DIR, 
                                font_path=abs_font_path, 
                                row_counts=parsed_counts, is_brick_mode=is_brick, alignment=align_val
                            )
                            st.session_state.last_generated_grid_image = auto_img
                            st.session_state.grid_last_generated_params = current_params
                        except: pass

            # 設定反映・保存ボタン
            if st.button("🔄 設定反映 (プレビュー生成)", type="primary", use_container_width=True, key="btn_grid_generate"):
                if generate_grid_image:
                    target_artists = []
                    for n in st.session_state.grid_order:
                        a = db.query(Artist).filter(Artist.name == n).first()
                        if a: target_artists.append(a)
                    
                    if not target_artists:
                        st.warning("表示するアーティストデータがありません。")
                    else:
                        # ★重要: 生成直前にフォント確保
                        check_and_download_font(db, st.session_state.grid_font)

                        with st.spinner("画像を生成＆保存中..."):
                            try:
                                is_brick = (st.session_state.grid_layout_mode == "レンガ (サイズ統一)")
                                align_map = {"左揃え": "left", "中央揃え": "center", "右揃え": "right"}
                                align_val = align_map.get(st.session_state.grid_alignment, "center")

                                # ★重要: 絶対パスを渡す
                                abs_font_path = os.path.join(os.path.abspath(FONT_DIR), st.session_state.grid_font)

                                img = generate_grid_image(
                                    target_artists, IMAGE_DIR, 
                                    font_path=abs_font_path, 
                                    row_counts=parsed_counts, is_brick_mode=is_brick, alignment=align_val
                                )
                                
                                if img:
                                    st.session_state.last_generated_grid_image = img
                                    st.session_state.grid_last_generated_params = current_params
                                    
                                    # DB保存
                                    proj_to_save = db.query(TimetableProject).filter(TimetableProject.id == selected_id).first()
                                    if proj_to_save:
                                        settings = {}
                                        if proj_to_save.settings_json:
                                            try: settings = json.loads(proj_to_save.settings_json)
                                            except: pass
                                        
                                        settings["grid_settings"] = current_params
                                        proj_to_save.settings_json = json.dumps(settings, ensure_ascii=False)
                                        
                                        if save_current_project(db, selected_id):
                                            st.toast("保存＆プレビュー更新完了！", icon="✅")
                                        else:
                                            st.error("DB保存に失敗しました")
                                else:
                                    st.error("生成失敗")
                            except Exception as e:
                                st.error(f"プレビュー生成エラー: {e}")
                else:
                    st.error("ロジックエラー")

            # 判定ロジック
            is_outdated = False
            if st.session_state.get("grid_last_generated_params") is None: is_outdated = True
            elif st.session_state.grid_last_generated_params != current_params: is_outdated = True
            
            if st.session_state.get("last_generated_grid_image"):
                if is_outdated:
                    st.warning("⚠️ 設定が変更されています。最新の状態にするには「設定反映」ボタンを押してください。")
                    st.caption("👇 前回生成時のプレビュー")
                else:
                    st.caption("👇 現在のプレビュー")
                st.image(st.session_state.last_generated_grid_image, use_container_width=True)
            elif is_outdated:
                 st.info("👆 設定を行ったら「設定反映」ボタンを押してプレビューを生成してください。")

    except Exception as main_e:
        st.error(f"予期せぬエラー: {main_e}")
    finally:
        db.close()
