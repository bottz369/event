import streamlit as st
from datetime import date, datetime, timedelta
import json
import base64
import os
import pandas as pd

from database import get_db, TimetableProject, SessionLocal, Artist, AssetFile, get_image_url

# constantsから FONT_DIR を読み込み
from constants import FONT_DIR, get_default_row_settings
from utils import safe_int, safe_str, calculate_timetable_flow

from logic_project import save_current_project, duplicate_project, load_timetable_rows

# --- 画像生成ロジックの読み込み ---
try:
    from logic_timetable import generate_timetable_image
except ImportError:
    generate_timetable_image = None

try:
    # グリッド生成関数の読み込み
    from views.grid import generate_grid_image_buffer 
except ImportError:
    generate_grid_image_buffer = None

try:
    # ★追加: フライヤー生成関数の読み込み
    # views/flyer.py に generate_flyer_image があると仮定しています
    from views.flyer import generate_flyer_image
except ImportError:
    generate_flyer_image = None

from views.overview import render_overview_page 
from views.timetable import render_timetable_page 
from views.grid import render_grid_page
from views.flyer import render_flyer_editor

# --- プロジェクトデータのロード関数 ---
def load_project_to_session(proj):
    """DBから読み込んだプロジェクト情報をセッションステートに展開する"""
    st.session_state.tt_current_proj_id = proj.id
    st.session_state.proj_title = proj.title
    try:
        st.session_state.proj_date = datetime.strptime(proj.event_date, "%Y-%m-%d").date()
    except:
        st.session_state.proj_date = date.today()
    st.session_state.proj_venue = proj.venue_name
    st.session_state.proj_url = proj.venue_url
    st.session_state.tt_open_time = proj.open_time or "10:00"
    st.session_state.tt_start_time = proj.start_time or "10:30"
    st.session_state.tt_goods_offset = proj.goods_start_offset if proj.goods_start_offset is not None else 5

    data = []
    db = SessionLocal()
    try:
        data = load_timetable_rows(db, proj.id)
    except Exception as e:
        print(f"Table load error: {e}")
    finally:
        db.close()

    if not data and proj.data_json:
        try:
            data = json.loads(proj.data_json)
        except:
            data = []

    if data:
        try:
            new_order = []
            new_artist_settings = {}
            new_row_settings = []
            st.session_state.tt_has_pre_goods = False
            
            for item in data:
                name = item.get("ARTIST")
                if name == "開演前物販":
                    st.session_state.tt_has_pre_goods = True
                    st.session_state.tt_pre_goods_settings = {
                        "GOODS_START_MANUAL": safe_str(item.get("GOODS_START_MANUAL")),
                        "GOODS_DURATION": safe_int(item.get("GOODS_DURATION"), 60),
                        "PLACE": safe_str(item.get("PLACE")),
                        "IS_HIDDEN": bool(item.get("IS_HIDDEN", False))
                    }
                    continue
                if name == "終演後物販":
                    st.session_state.tt_post_goods_settings = {
                        "GOODS_START_MANUAL": safe_str(item.get("GOODS_START_MANUAL")),
                        "GOODS_DURATION": safe_int(item.get("GOODS_DURATION"), 60),
                        "PLACE": safe_str(item.get("PLACE")),
                        "IS_HIDDEN": bool(item.get("IS_HIDDEN", False))
                    }
                    continue
                if name:
                    new_order.append(name)
                    new_artist_settings[name] = {"DURATION": safe_int(item.get("DURATION"), 20)}
                    new_row_settings.append({
                        "ADJUSTMENT": safe_int(item.get("ADJUSTMENT"), 0),
                        "GOODS_START_MANUAL": safe_str(item.get("GOODS_START_MANUAL")),
                        "GOODS_DURATION": safe_int(item.get("GOODS_DURATION"), 60),
                        "PLACE": safe_str(item.get("PLACE")),
                        "ADD_GOODS_START": safe_str(item.get("ADD_GOODS_START")),
                        "ADD_GOODS_DURATION": safe_int(item.get("ADD_GOODS_DURATION"), None),
                        "ADD_GOODS_PLACE": safe_str(item.get("ADD_GOODS_PLACE")),
                        "IS_POST_GOODS": bool(item.get("IS_POST_GOODS", False)),
                        "IS_HIDDEN": bool(item.get("IS_HIDDEN", False))
                    })
            st.session_state.tt_artists_order = new_order
            st.session_state.tt_artist_settings = new_artist_settings
            st.session_state.tt_row_settings = new_row_settings
            st.session_state.rebuild_table_flag = True 
        except Exception as e:
            print(f"Data parse error: {e}")

    settings = {}
    if proj.settings_json:
        try: settings = json.loads(proj.settings_json)
        except: pass
    st.session_state.tt_font = settings.get("tt_font", "keifont.ttf")
    st.session_state.tt_columns = settings.get("tt_columns", 2)  # ★追加: 列数設定の読み込み
    st.session_state.grid_font = settings.get("grid_font", "keifont.ttf")
    
    tickets_data = []
    if proj.tickets_json:
        try:
            data = json.loads(proj.tickets_json)
            if isinstance(data, list): tickets_data = data
        except: pass
    if not tickets_data: tickets_data = [{"name":"", "price":"", "note":""}]
    st.session_state.proj_tickets = tickets_data

    notes_data = []
    raw_notes = getattr(proj, "ticket_notes_json", None)
    if raw_notes:
        try:
            data = json.loads(raw_notes)
            if isinstance(data, list): notes_data = data
        except: pass
    st.session_state.proj_ticket_notes = notes_data

    free_data = []
    if proj.free_text_json:
        try:
            data = json.loads(proj.free_text_json)
            if isinstance(data, list): free_data = data
        except: pass
    if not free_data: free_data = [{"title":"", "content":""}]
    st.session_state.proj_free_text = free_data

    flyer_settings = {}
    if proj.flyer_json:
        try: flyer_settings = json.loads(proj.flyer_json)
        except: pass
    keys_map = {
        "flyer_logo_id": "logo_id", "flyer_bg_id": "bg_id",
        "flyer_sub_title": "sub_title", "flyer_input_1": "input_1",
        "flyer_bottom_left": "bottom_left", "flyer_bottom_right": "bottom_right",
        "flyer_font": "font", "flyer_text_color": "text_color", 
        "flyer_stroke_color": "stroke_color"
    }
    for session_key, json_key in keys_map.items():
        if json_key in flyer_settings:
            st.session_state[session_key] = flyer_settings[json_key]

    grid_loaded = False
    if proj.grid_order_json:
        try:
            g_data = json.loads(proj.grid_order_json)
            if isinstance(g_data, dict):
                st.session_state.grid_order = g_data.get("order", [])
                st.session_state.grid_cols = g_data.get("cols", 5)
                st.session_state.grid_rows = g_data.get("rows", 5)
                st.session_state.grid_row_counts_str = g_data.get("row_counts_str", "5,5,5,5,5")
                st.session_state.grid_alignment = g_data.get("alignment", "中央揃え")
                st.session_state.grid_layout_mode = g_data.get("layout_mode", "レンガ (サイズ統一)")
                grid_loaded = True
            elif isinstance(g_data, list):
                st.session_state.grid_order = g_data
                st.session_state.grid_cols = 5
                st.session_state.grid_rows = 5
                st.session_state.grid_row_counts_str = "5,5,5,5,5"
                st.session_state.grid_alignment = "中央揃え"
                st.session_state.grid_layout_mode = "レンガ (サイズ統一)"
                grid_loaded = True
        except: pass
    
    if not grid_loaded and proj.data_json:
        try:
            d = json.loads(proj.data_json)
            tt_artists = [i.get("ARTIST") for i in d if i.get("ARTIST") not in ["開演前物販", "終演後物販"]]
            st.session_state.grid_order = list(reversed(tt_artists))
            st.session_state.grid_cols = 5
            st.session_state.grid_rows = 5
            st.session_state.grid_row_counts_str = "5,5,5,5,5"
        except: pass

    # キャッシュリセット
    st.session_state.last_generated_tt_image = None
    st.session_state.tt_last_generated_params = None
    st.session_state.last_generated_grid_image = None
    st.session_state.grid_last_generated_params = None
    st.session_state.last_generated_flyer_image = None # フライヤー用キャッシュもリセット
    st.session_state.overview_text_preview = None

# --- フォント準備関数 (絶対パス対応) ---
def prepare_active_project_fonts(db):
    needed_fonts = set()
    if st.session_state.get("tt_font"): needed_fonts.add(st.session_state.tt_font)
    if st.session_state.get("grid_font"): needed_fonts.add(st.session_state.grid_font)
    if st.session_state.get("flyer_font"): needed_fonts.add(st.session_state.flyer_font)
    needed_fonts = {f for f in needed_fonts if f}
    
    if not needed_fonts: return

    try:
        assets = db.query(AssetFile).filter(AssetFile.filename.in_(list(needed_fonts))).all()
        css_styles = ""
        
        # ★重要: 絶対パスに変換
        font_dir = os.path.abspath(FONT_DIR)
        os.makedirs(font_dir, exist_ok=True)
        
        for asset in assets:
            if not asset.file_data: continue
            
            # A. ファイル書き出し
            file_path = os.path.join(font_dir, asset.filename)
            
            # ファイルが存在しない、またはサイズが0の場合のみ書き出す
            if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
                try:
                    with open(file_path, "wb") as f:
                        f.write(asset.file_data)
                except Exception as e:
                    print(f"Failed to write font file {file_path}: {e}")

            # B. CSS注入
            try:
                b64_data = base64.b64encode(asset.file_data).decode()
                mime_type = "font/ttf"
                if asset.filename.lower().endswith(".otf"): mime_type = "font/otf"
                elif asset.filename.lower().endswith(".woff"): mime_type = "font/woff"
                elif asset.filename.lower().endswith(".woff2"): mime_type = "font/woff2"

                css_styles += f"""
                @font-face {{
                    font-family: '{asset.filename}';
                    src: url(data:{mime_type};base64,{b64_data});
                }}
                """
            except Exception as e:
                print(f"Font encode error ({asset.filename}): {e}")
        
        if css_styles:
            st.markdown(f"<style>{css_styles}</style>", unsafe_allow_html=True)
            
    except Exception as e:
        print(f"Font preparation error: {e}")

# --- コンテンツ自動生成関数 (絶対パス対応) ---
def ensure_generated_contents(db):
    """
    リロード時などに画像キャッシュがない場合、保存された設定とフォントを使って
    タイムテーブル、グリッド、フライヤー画像を自動生成する。
    """
    font_dir_abs = os.path.abspath(FONT_DIR)

    # ---------------------------------------------------------
    # 1. タイムテーブル画像の自動生成
    # ---------------------------------------------------------
    if st.session_state.get("last_generated_tt_image") is None:
        if generate_timetable_image and "tt_artists_order" in st.session_state:
            try:
                # データの構築
                rows = []
                hidden_flags = []

                if st.session_state.get("tt_has_pre_goods"):
                    p = st.session_state.tt_pre_goods_settings
                    is_h = bool(p.get("IS_HIDDEN", False))
                    hidden_flags.append(is_h)
                    rows.append({
                        "ARTIST": "開演前物販", "DURATION":0, "ADJUSTMENT":0, "IS_POST_GOODS":False, 
                        "GOODS_START_MANUAL": safe_str(p.get("GOODS_START_MANUAL")), "GOODS_DURATION": safe_int(p.get("GOODS_DURATION"), 60), "PLACE": "", 
                        "ADD_GOODS_START":"", "ADD_GOODS_DURATION":None, "ADD_GOODS_PLACE":"",
                        "IS_HIDDEN": is_h
                    })
                
                has_post = False
                for i, name in enumerate(st.session_state.tt_artists_order):
                    ad = st.session_state.tt_artist_settings.get(name, {"DURATION": 20})
                    rd = {}
                    if i < len(st.session_state.tt_row_settings):
                        rd = st.session_state.tt_row_settings[i]
                    else:
                        rd = get_default_row_settings()

                    is_p = bool(rd.get("IS_POST_GOODS", False))
                    is_h = bool(rd.get("IS_HIDDEN", False))
                    hidden_flags.append(is_h)

                    if is_p: has_post = True
                    rows.append({
                        "ARTIST": name, "DURATION": safe_int(ad.get("DURATION"), 20), "IS_POST_GOODS": is_p,
                        "ADJUSTMENT": safe_int(rd.get("ADJUSTMENT"), 0),
                        "GOODS_START_MANUAL": safe_str(rd.get("GOODS_START_MANUAL")), "GOODS_DURATION": safe_int(rd.get("GOODS_DURATION"), 60), "PLACE": safe_str(rd.get("PLACE")),
                        "ADD_GOODS_START": safe_str(rd.get("ADD_GOODS_START")), "ADD_GOODS_DURATION": safe_int(rd.get("ADD_GOODS_DURATION"), None), "ADD_GOODS_PLACE": safe_str(rd.get("ADD_GOODS_PLACE")),
                        "IS_HIDDEN": is_h
                    })
                
                if has_post:
                    p = st.session_state.tt_post_goods_settings
                    is_h = bool(p.get("IS_HIDDEN", False))
                    hidden_flags.append(is_h)
                    rows.append({
                        "ARTIST": "終演後物販", "DURATION":0, "ADJUSTMENT":0, "IS_POST_GOODS":False,
                        "GOODS_START_MANUAL": safe_str(p.get("GOODS_START_MANUAL")), "GOODS_DURATION": safe_int(p.get("GOODS_DURATION"), 60), "PLACE": "",
                        "ADD_GOODS_START":"", "ADD_GOODS_DURATION":None, "ADD_GOODS_PLACE":"",
                        "IS_HIDDEN": is_h
                    })

                column_order = ["ARTIST", "DURATION", "IS_POST_GOODS", "ADJUSTMENT", "GOODS_START_MANUAL", "GOODS_DURATION", "PLACE", "ADD_GOODS_START", "ADD_GOODS_DURATION", "ADD_GOODS_PLACE", "IS_HIDDEN"]
                df_for_calc = pd.DataFrame(rows, columns=column_order)
                
                # 時間計算
                calc_df = calculate_timetable_flow(df_for_calc, st.session_state.tt_open_time, st.session_state.tt_start_time)
                
                # 生成リスト作成
                gen_list = []
                flag_idx = 0 

                for _, row in calc_df.iterrows():
                    if row["ARTIST"] == "OPEN / START": 
                        continue
                    
                    is_hidden = False
                    if flag_idx < len(hidden_flags):
                        is_hidden = hidden_flags[flag_idx]
                    
                    flag_idx += 1 

                    if is_hidden:
                        continue

                    gen_list.append([row["TIME_DISPLAY"], row["ARTIST"], row["GOODS_DISPLAY"], row["PLACE"]])
                
                st.session_state.tt_gen_list = gen_list
                
                # 画像生成実行
                if gen_list:
                    font_path = os.path.join(font_dir_abs, st.session_state.tt_font)
                    tt_cols = st.session_state.get("tt_columns", 2) # ★追加: 列数を取得
                    
                    # ★追加: columns 引数を追加
                    img = generate_timetable_image(gen_list, font_path=font_path, columns=tt_cols)
                    st.session_state.last_generated_tt_image = img
                    
                    st.session_state.tt_last_generated_params = {
                        "gen_list": gen_list,
                        "font": st.session_state.tt_font,
                        "columns": tt_cols # ★追加: パラメータに列数を保持
                    }
            
            except Exception as e:
                print(f"Auto-generate TT failed: {e}")

    # ---------------------------------------------------------
    # 2. グリッド画像の自動生成
    # ---------------------------------------------------------
    if st.session_state.get("last_generated_grid_image") is None:
        if generate_grid_image_buffer and "grid_order" in st.session_state and st.session_state.grid_order:
            try:
                # アーティスト情報の取得
                target_names = st.session_state.grid_order
                artists_map = {}
                artists = db.query(Artist).filter(Artist.name.in_(target_names)).all()
                for a in artists:
                    artists_map[a.name] = a
                
                # 並び順通りにArtistオブジェクトのリストを作成
                ordered_artists = []
                for name in target_names:
                    if name in artists_map:
                        ordered_artists.append(artists_map[name])
                
                if ordered_artists:
                    font_path = os.path.join(font_dir_abs, st.session_state.get("grid_font", "keifont.ttf"))
                    
                    # グリッド生成実行 (generate_grid_image_bufferの引数は実際のviews/grid.pyの実装に依存します)
                    # ここでは標準的な引数を想定しています。エラー時はcatchされます。
                    img_buffer = generate_grid_image_buffer(
                        artists=ordered_artists,
                        cols=st.session_state.get("grid_cols", 5),
                        rows=st.session_state.get("grid_rows", 5),
                        font_path=font_path,
                        alignment=st.session_state.get("grid_alignment", "中央揃え"),
                        layout_mode=st.session_state.get("grid_layout_mode", "レンガ (サイズ統一)"),
                        row_counts_str=st.session_state.get("grid_row_counts_str", "5,5,5,5,5")
                    )
                    
                    if img_buffer:
                        st.session_state.last_generated_grid_image = img_buffer
                        st.session_state.grid_last_generated_params = {
                            "order": target_names,
                            "cols": st.session_state.get("grid_cols", 5)
                        }
            except Exception as e:
                print(f"Auto-generate Grid failed: {e}")

    # ---------------------------------------------------------
    # 3. フライヤー画像の自動生成
    # ---------------------------------------------------------
    if st.session_state.get("last_generated_flyer_image") is None:
        if generate_flyer_image:
            try:
                # generate_flyer_imageの実装に合わせて引数を渡す必要があります
                # プロジェクトIDやセッションステートからデータを取得する形式を想定
                project_id = st.session_state.get("tt_current_proj_id")
                if project_id:
                     # ここでは単純に generate_flyer_image() などを呼び出しています
                     # 必要であれば generate_flyer_image(project_id) のように引数を調整してください
                    img = generate_flyer_image(project_id) 
                    
                    if img:
                        st.session_state.last_generated_flyer_image = img
            except Exception as e:
                print(f"Auto-generate Flyer failed: {e}")


# --- メイン描画 ---
def render_workspace_page():
    with st.sidebar.expander("🔧 画像表示診断", expanded=False):
        st.caption("タイムテーブルに画像が出ない場合、ここでチェックしてください。")
        debug_name = st.text_input("アーティスト名 (完全一致)", placeholder="例: アーティストA")
        if st.button("診断開始"):
            if not debug_name:
                st.warning("名前を入力してください")
            else:
                db_debug = SessionLocal()
                try:
                    artist = db_debug.query(Artist).filter(Artist.name == debug_name).first()
                    if artist:
                        st.success(f"✅ DB登録あり (ID: {artist.id})")
                        st.write(f"ファイル名: `{artist.image_filename}`")
                        if artist.image_filename:
                            try:
                                url = get_image_url(artist.image_filename)
                                st.write(f"URL: `{url}`")
                                if url:
                                    st.image(url, caption="取得画像", width=150)
                                else:
                                    st.error("❌ URL生成失敗 (None)")
                            except Exception as e:
                                st.error(f"❌ URL生成エラー: {e}")
                        else:
                            st.warning("⚠️ 画像ファイル名が未登録です")
                    else:
                        st.error("❌ DBに名前が見つかりません")
                        similar = db_debug.query(Artist).filter(Artist.name.like(f"%{debug_name}%")).limit(3).all()
                        if similar:
                            st.info(f"候補: {', '.join([a.name for a in similar])}")
                except Exception as e:
                    st.error(f"DB接続エラー: {e}")
                finally:
                    db_debug.close()
    
    st.title("🚀 プロジェクト・ワークスペース")
    
    db = next(get_db())
    try:
        projects = db.query(TimetableProject).all()
        projects.sort(key=lambda x: x.event_date or "0000-00-00", reverse=True)
        
        proj_map = {f"{p.event_date} {p.title}": p.id for p in projects}
        options = ["(選択してください)", "➕ 新規プロジェクト作成"] + list(proj_map.keys())
        
        if "ws_active_project_id" not in st.session_state:
            st.session_state.ws_active_project_id = None

        current_idx = 0
        if st.session_state.ws_active_project_id:
            current_val = next((k for k, v in proj_map.items() if v == st.session_state.ws_active_project_id), None)
            if current_val in options:
                current_idx = options.index(current_val)

        selected_label = st.selectbox("作業するプロジェクトを選択", options, index=current_idx, key="ws_project_selector")

        if selected_label not in ["(選択してください)", "➕ 新規プロジェクト作成"]:
            selected_id = proj_map.get(selected_label)
            if selected_id != st.session_state.ws_active_project_id:
                st.session_state.ws_active_project_id = selected_id
                proj = db.query(TimetableProject).filter(TimetableProject.id == selected_id).first()
                if proj:
                    load_project_to_session(proj)
                    st.rerun()

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
                        st.session_state.ws_active_project_id = new_proj.id
                        load_project_to_session(new_proj)
                        st.success("プロジェクトを作成しました！")
                        st.rerun()
                    else:
                        st.error("イベント名と会場名は必須です")
            return

        if selected_label == "(選択してください)":
            st.info("👆 上のボックスからプロジェクトを選択するか、新規作成してください。")
            return

        project_id = st.session_state.ws_active_project_id
        
        # 1. フォント準備（ファイル生成・絶対パス）
        prepare_active_project_fonts(db)
        
        # 2. コンテンツ自動生成（絶対パス使用）
        # ★ここでタイムテーブル、グリッド、フライヤーの3つを自動生成します
        ensure_generated_contents(db)

        proj_check = db.query(TimetableProject).filter(TimetableProject.id == project_id).first()
        if not proj_check:
            st.error("プロジェクトが見つかりません")
            st.session_state.ws_active_project_id = None
            st.rerun()

        st.markdown("---")
        
        col_dummy, col_act = st.columns([4, 1])
        with col_act:
            if st.button("📄 複製して編集", use_container_width=True, key="btn_proj_duplicate"):
                save_current_project(db, project_id)
                new_proj = duplicate_project(db, project_id)
                if new_proj:
                    st.session_state.ws_active_project_id = new_proj.id
                    load_project_to_session(new_proj)
                    st.toast("プロジェクトを複製しました！", icon="✨")
                    st.rerun()

        display_title = st.session_state.get("proj_title", "")
        display_date = st.session_state.get("proj_date", "")
        display_venue = st.session_state.get("proj_venue", "")

        st.markdown(f"### 📂 {display_title} <small>({display_date} @ {display_venue})</small>", unsafe_allow_html=True)

        tab_overview, tab_tt, tab_grid, tab_flyer = st.tabs(["📝 イベント概要", "⏱️ タイムテーブル", "🖼️ アー写グリッド", "📑 フライヤーセット"])

        with tab_overview:
            render_overview_page()

        with tab_tt:
            render_timetable_page()
        
        with tab_grid:
            st.session_state.current_grid_proj_id = project_id
            render_grid_page()

        with tab_flyer:
            render_flyer_editor(project_id)

    finally:
        db.close()
