import streamlit as st
from datetime import date, datetime
import json
import base64
import os  # ★追加: ファイル書き込み用

# ★修正: get_image_url や必要なモデルを追加インポート
from database import get_db, TimetableProject, SessionLocal, Artist, AssetFile, get_image_url
from utils import safe_int, safe_str

# ★重要: ロジックを外部ファイルからインポート
from logic_project import save_current_project, duplicate_project, load_timetable_rows

# 各機能の読み込み
from views.overview import render_overview_page 
from views.timetable import render_timetable_page 
from views.grid import render_grid_page
from views.flyer import render_flyer_editor

# --- プロジェクトデータのロード関数 ---
def load_project_to_session(proj):
    """DBから読み込んだプロジェクト情報をセッションステートに展開する"""
    st.session_state.tt_current_proj_id = proj.id
    
    # 基本情報
    st.session_state.proj_title = proj.title
    try:
        st.session_state.proj_date = datetime.strptime(proj.event_date, "%Y-%m-%d").date()
    except:
        st.session_state.proj_date = date.today()
    st.session_state.proj_venue = proj.venue_name
    st.session_state.proj_url = proj.venue_url

    # タイムテーブル基本設定
    st.session_state.tt_open_time = proj.open_time or "10:00"
    st.session_state.tt_start_time = proj.start_time or "10:30"
    st.session_state.tt_goods_offset = proj.goods_start_offset if proj.goods_start_offset is not None else 5

    # ---------------------------------------------------------
    # タイムテーブルデータのロード (DBテーブル優先)
    # ---------------------------------------------------------
    data = []
    
    # 1. まずDBテーブル(timetable_rows)からの読み込みを試みる
    db = SessionLocal()
    try:
        data = load_timetable_rows(db, proj.id)
    except Exception as e:
        print(f"Table load error: {e}")
    finally:
        db.close()

    # 2. DBが空なら、旧形式(JSON)からの移行を試みる
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
                
                # 開演前物販
                if name == "開演前物販":
                    st.session_state.tt_has_pre_goods = True
                    st.session_state.tt_pre_goods_settings = {
                        "GOODS_START_MANUAL": safe_str(item.get("GOODS_START_MANUAL")),
                        "GOODS_DURATION": safe_int(item.get("GOODS_DURATION"), 60),
                        "PLACE": safe_str(item.get("PLACE")),
                    }
                    continue
                
                # 終演後物販
                if name == "終演後物販":
                    st.session_state.tt_post_goods_settings = {
                        "GOODS_START_MANUAL": safe_str(item.get("GOODS_START_MANUAL")),
                        "GOODS_DURATION": safe_int(item.get("GOODS_DURATION"), 60),
                        "PLACE": safe_str(item.get("PLACE")),
                    }
                    continue
                
                # 通常アーティスト
                if name:
                    new_order.append(name)
                    new_artist_settings[name] = {"DURATION": safe_int(item.get("DURATION"), 20)}
                    
                    # 行設定 (追加物販情報含む)
                    new_row_settings.append({
                        "ADJUSTMENT": safe_int(item.get("ADJUSTMENT"), 0),
                        "GOODS_START_MANUAL": safe_str(item.get("GOODS_START_MANUAL")),
                        "GOODS_DURATION": safe_int(item.get("GOODS_DURATION"), 60),
                        "PLACE": safe_str(item.get("PLACE")),
                        # ★ここが重要: 追加物販情報の読み込み
                        "ADD_GOODS_START": safe_str(item.get("ADD_GOODS_START")),
                        "ADD_GOODS_DURATION": safe_int(item.get("ADD_GOODS_DURATION"), None),
                        "ADD_GOODS_PLACE": safe_str(item.get("ADD_GOODS_PLACE")),
                        "IS_POST_GOODS": bool(item.get("IS_POST_GOODS", False))
                    })
            
            # セッションに反映
            st.session_state.tt_artists_order = new_order
            st.session_state.tt_artist_settings = new_artist_settings
            st.session_state.tt_row_settings = new_row_settings
            st.session_state.rebuild_table_flag = True 
            
        except Exception as e:
            print(f"Data parse error: {e}")

    # 設定のロード
    settings = {}
    if proj.settings_json:
        try: settings = json.loads(proj.settings_json)
        except: pass
    st.session_state.tt_font = settings.get("tt_font", "keifont.ttf")
    st.session_state.grid_font = settings.get("grid_font", "keifont.ttf")
    
    # チケット情報のロード
    tickets_data = []
    if proj.tickets_json:
        try:
            data = json.loads(proj.tickets_json)
            if isinstance(data, list): tickets_data = data
        except: pass
    if not tickets_data: tickets_data = [{"name":"", "price":"", "note":""}]
    st.session_state.proj_tickets = tickets_data

    # チケット共通備考のロード
    notes_data = []
    raw_notes = getattr(proj, "ticket_notes_json", None)
    if raw_notes:
        try:
            data = json.loads(raw_notes)
            if isinstance(data, list): notes_data = data
        except: pass
    st.session_state.proj_ticket_notes = notes_data

    # 自由記述のロード
    free_data = []
    if proj.free_text_json:
        try:
            data = json.loads(proj.free_text_json)
            if isinstance(data, list): free_data = data
        except: pass
    if not free_data: free_data = [{"title":"", "content":""}]
    st.session_state.proj_free_text = free_data

    # フライヤー設定
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
        elif session_key in st.session_state:
            pass

    # グリッド情報のロード
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
    st.session_state.overview_text_preview = None

# --- ★修正: フォントの準備関数（ファイル復元 ＆ CSS注入） ---
def prepare_active_project_fonts(db):
    """
    1. DBからフォントデータを取得
    2. ローカルにファイルが存在しなければ書き出し (画像生成ライブラリ用)
    3. ブラウザ用にCSS注入 (プレビュー表示用)
    """
    needed_fonts = set()
    if st.session_state.get("tt_font"): needed_fonts.add(st.session_state.tt_font)
    if st.session_state.get("grid_font"): needed_fonts.add(st.session_state.grid_font)
    if st.session_state.get("flyer_font"): needed_fonts.add(st.session_state.flyer_font)
    needed_fonts = {f for f in needed_fonts if f}
    
    if not needed_fonts: return

    try:
        # DBからフォントデータ取得
        assets = db.query(AssetFile).filter(AssetFile.filename.in_(list(needed_fonts))).all()
        
        css_styles = ""
        # フォント保存先ディレクトリ（必要なら変更してください）
        font_dir = "." 
        
        for asset in assets:
            if not asset.file_data:
                continue

            # --- A. ファイル生成 (画像生成用) ---
            file_path = os.path.join(font_dir, asset.filename)
            # ファイルが存在しない、またはサイズが0の場合のみ書き出す
            if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
                try:
                    with open(file_path, "wb") as f:
                        f.write(asset.file_data)
                except Exception as e:
                    print(f"Failed to write font file {file_path}: {e}")

            # --- B. CSS生成 (ブラウザ表示用) ---
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

# --- メイン描画 ---
def render_workspace_page():
    # 画像表示診断 (変更なし)
    with st.sidebar.expander("🔧 画像表示診断", expanded=False):
        st.caption("タイムテーブルに画像が出ない場合、ここでチェックしてください。")
        debug_name = st.text_input("アーティスト名 (完全一致)", placeholder="例: アーティストA")
        if st.button("診断開始"):
            if not debug_name:
                st.warning("名前を入力してください")
            else:
                db_debug = SessionLocal()
                try:
                    # 1. DB検索
                    artist = db_debug.query(Artist).filter(Artist.name == debug_name).first()
                    if artist:
                        st.success(f"✅ DB登録あり (ID: {artist.id})")
                        st.write(f"ファイル名: `{artist.image_filename}`")
                        
                        if artist.image_filename:
                            # 2. URL生成確認
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
                        # 似た名前を探す
                        similar = db_debug.query(Artist).filter(Artist.name.like(f"%{debug_name}%")).limit(3).all()
                        if similar:
                            st.info(f"候補: {', '.join([a.name for a in similar])}")
                        else:
                            st.write("※スペースの有無などを確認してください")
                except Exception as e:
                    st.error(f"DB接続エラー: {e}")
                finally:
                    db_debug.close()
    
    # ----------------------------------------------------

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
            
            # プロジェクトIDが変わった場合のみロード処理を行う
            if selected_id != st.session_state.ws_active_project_id:
                st.session_state.ws_active_project_id = selected_id
                proj = db.query(TimetableProject).filter(TimetableProject.id == selected_id).first()
                if proj:
                    load_project_to_session(proj)
                    st.rerun()

        # --- 新規作成モード ---
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

        # --- 編集画面 ---
        project_id = st.session_state.ws_active_project_id
        
        # ★修正: ここでフォント準備処理を実行（ファイル復元+CSS注入）
        prepare_active_project_fonts(db)

        proj_check = db.query(TimetableProject).filter(TimetableProject.id == project_id).first()
        
        if not proj_check:
            st.error("プロジェクトが見つかりません")
            st.session_state.ws_active_project_id = None
            st.rerun()

        st.markdown("---")
        
        # 複製ボタン
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

        # ヘッダー
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
