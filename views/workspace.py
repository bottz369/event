import streamlit as st
from datetime import date
import json
import uuid
from database import get_db, TimetableProject

# 各機能の読み込み
from views.timetable import render_timetable_page 
from views.grid import render_grid_page
from views.flyer import render_flyer_editor

def load_project_to_session(proj):
    """DBから読み込んだプロジェクト情報をセッションステートに展開する"""
    st.session_state.tt_current_proj_id = proj.id
    
    # 1. タイムテーブル設定
    # データ展開ロジックは timetable.py 側で selected_id 変更検知時に走るため、
    # ここでは「設定(フォント等)」のロードを行う
    settings = {}
    if proj.settings_json:
        try: settings = json.loads(proj.settings_json)
        except: pass
    
    st.session_state.tt_font = settings.get("tt_font", "keifont.ttf")
    st.session_state.grid_font = settings.get("grid_font", "keifont.ttf")
    
    # 2. フライヤー設定
    flyer_settings = {}
    if proj.flyer_json:
        try: flyer_settings = json.loads(proj.flyer_json)
        except: pass
    
    # フライヤーの各入力欄のキーに値をセット
    # (キーが存在しない場合のみセット＝初回ロード時)
    keys_map = {
        "flyer_logo_id": "logo_id", "flyer_bg_id": "bg_id",
        "flyer_date_str": "date_str", "flyer_venue_str": "venue_str",
        "flyer_open_time": "open_time", "flyer_start_time": "start_time",
        "flyer_ticket_info": "ticket_info", "flyer_notes": "notes",
        "flyer_font": "font", "flyer_text_color": "text_color", 
        "flyer_stroke_color": "stroke_color"
    }
    for session_key, json_key in keys_map.items():
        if json_key in flyer_settings:
            st.session_state[session_key] = flyer_settings[json_key]
        elif session_key in st.session_state:
            # DBにない場合、既存のセッションをクリア（前のPJの情報を消す）
            del st.session_state[session_key]

def save_current_project(db, project_id):
    """現在のセッションステートの内容をDBに保存する"""
    proj = db.query(TimetableProject).filter(TimetableProject.id == project_id).first()
    if not proj: return False
    
    # 1. タイムテーブルデータ
    # DataEditorのデータは st.session_state.binding_df にある
    if "binding_df" in st.session_state and not st.session_state.binding_df.empty:
        save_data = st.session_state.binding_df.to_dict(orient="records")
        proj.data_json = json.dumps(save_data, ensure_ascii=False)
    
    # 基本設定
    if "tt_open_time" in st.session_state: proj.open_time = st.session_state.tt_open_time
    if "tt_start_time" in st.session_state: proj.start_time = st.session_state.tt_start_time
    if "tt_goods_offset" in st.session_state: proj.goods_start_offset = st.session_state.tt_goods_offset

    # 2. グリッド設定
    if "grid_order" in st.session_state:
        grid_data = {
            "cols": st.session_state.get("grid_cols", 5),
            "rows": st.session_state.get("grid_rows", 5),
            "order": st.session_state.grid_order
        }
        proj.grid_order_json = json.dumps(grid_data, ensure_ascii=False)

    # 3. 画面設定（フォント等）
    settings = {
        "tt_font": st.session_state.get("tt_font", "keifont.ttf"),
        "grid_font": st.session_state.get("grid_font", "keifont.ttf")
    }
    proj.settings_json = json.dumps(settings, ensure_ascii=False)

    # 4. フライヤー設定
    # セッションステートからキーを取得して保存
    flyer_data = {}
    keys = ["flyer_logo_id", "flyer_bg_id", "flyer_date_str", "flyer_venue_str", 
            "flyer_open_time", "flyer_start_time", "flyer_ticket_info", 
            "flyer_notes", "flyer_font", "flyer_text_color", "flyer_stroke_color"]
    
    for k in keys:
        # キー名の "flyer_" を除いたものをJSONのキーにする
        json_key = k.replace("flyer_", "")
        if k in st.session_state:
            flyer_data[json_key] = st.session_state[k]
    
    proj.flyer_json = json.dumps(flyer_data, ensure_ascii=False)

    db.commit()
    return True

def duplicate_project(db, project_id):
    """プロジェクトを複製する"""
    src = db.query(TimetableProject).filter(TimetableProject.id == project_id).first()
    if not src: return None
    
    new_proj = TimetableProject(
        title=f"{src.title} (コピー)",
        event_date=src.event_date,
        venue_name=src.venue_name,
        venue_url=src.venue_url,
        open_time=src.open_time,
        start_time=src.start_time,
        goods_start_offset=src.goods_start_offset,
        data_json=src.data_json,
        grid_order_json=src.grid_order_json,
        tickets_json=src.tickets_json,
        free_text_json=src.free_text_json,
        flyer_json=src.flyer_json,
        settings_json=src.settings_json
    )
    db.add(new_proj)
    db.commit()
    return new_proj

def render_workspace_page():
    st.title("🚀 プロジェクト・ワークスペース")
    db = next(get_db())
    
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

    # セレクトボックス（変更検知）
    selected_label = st.selectbox("作業するプロジェクトを選択", options, index=current_idx, key="ws_project_selector")

    # --- 選択変更時の処理 ---
    # セレクトボックスの値がセッションステートのIDと一致しない場合＝ユーザーが変更した瞬間
    selected_id = proj_map.get(selected_label)
    if selected_label not in ["(選択してください)", "➕ 新規プロジェクト作成"] and selected_id != st.session_state.ws_active_project_id:
        st.session_state.ws_active_project_id = selected_id
        # 新しいプロジェクトのデータをロード
        proj = db.query(TimetableProject).filter(TimetableProject.id == selected_id).first()
        if proj:
            load_project_to_session(proj)
            st.rerun()

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
                    st.session_state.ws_active_project_id = new_proj.id
                    load_project_to_session(new_proj)
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
    project_id = st.session_state.ws_active_project_id
    proj = db.query(TimetableProject).filter(TimetableProject.id == project_id).first()
    
    if not proj:
        st.error("プロジェクトが見つかりません")
        st.session_state.ws_active_project_id = None
        st.rerun()

    # === 操作ボタンエリア (共通) ===
    st.markdown("---")
    col_act1, col_act2, col_dummy = st.columns([1, 1, 3])
    with col_act1:
        if st.button("💾 上書き保存", type="primary", use_container_width=True):
            if save_current_project(db, project_id):
                st.session_state.tt_unsaved_changes = False
                st.toast("保存しました！", icon="✅")
            else:
                st.error("保存に失敗しました")
    
    with col_act2:
        if st.button("📄 複製して編集", use_container_width=True):
            # まず現在の状態を保存
            save_current_project(db, project_id)
            # 複製実行
            new_proj = duplicate_project(db, project_id)
            if new_proj:
                st.session_state.ws_active_project_id = new_proj.id
                load_project_to_session(new_proj)
                st.toast("プロジェクトを複製しました！", icon="✨")
                st.rerun()

    st.markdown(f"### 📂 {proj.title} <small>({proj.event_date} @ {proj.venue_name})</small>", unsafe_allow_html=True)

    # タブ表示
    tab_tt, tab_grid, tab_flyer = st.tabs(["⏱️ タイムテーブル", "🖼️ アー写グリッド", "📑 フライヤーセット"])

    with tab_tt:
        render_timetable_page()
    
    with tab_grid:
        st.session_state.current_grid_proj_id = project_id
        render_grid_page()

    with tab_flyer:
        render_flyer_editor(project_id)

    db.close()
