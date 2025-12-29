import streamlit as st
from datetime import date, datetime
import json
from database import get_db, TimetableProject

# 各機能の読み込み
from views.timetable import render_timetable_page 
from views.grid import render_grid_page
from views.flyer import render_flyer_editor

# --- プロジェクトデータのロード関数 ---
def load_project_to_session(proj):
    st.session_state.tt_current_proj_id = proj.id
    
    # 基本情報
    st.session_state.proj_title = proj.title
    try:
        st.session_state.proj_date = datetime.strptime(proj.event_date, "%Y-%m-%d").date()
    except:
        st.session_state.proj_date = date.today()
    st.session_state.proj_venue = proj.venue_name
    st.session_state.proj_url = proj.venue_url

    # 設定のロード
    settings = {}
    if proj.settings_json:
        try: settings = json.loads(proj.settings_json)
        except: pass
    st.session_state.tt_font = settings.get("tt_font", "keifont.ttf")
    st.session_state.grid_font = settings.get("grid_font", "keifont.ttf")
    
    # ★重要: チケット・自由記述をリストとしてロード
    # JSONが保存されていない場合は、空のリストではなく初期フォーム用に1行入ったリストを作るなどの調整も可
    if proj.tickets_json:
        try: st.session_state.proj_tickets = json.loads(proj.tickets_json)
        except: st.session_state.proj_tickets = [{"name":"", "price":"", "note":""}]
    else:
        st.session_state.proj_tickets = [{"name":"", "price":"", "note":""}]

    if proj.free_text_json:
        try: st.session_state.proj_free_text = json.loads(proj.free_text_json)
        except: st.session_state.proj_free_text = [{"title":"", "content":""}]
    else:
        st.session_state.proj_free_text = [{"title":"", "content":""}]

    # フライヤー設定（テキストエリア系は削除し、デザイン設定のみロード）
    flyer_settings = {}
    if proj.flyer_json:
        try: flyer_settings = json.loads(proj.flyer_json)
        except: pass
    
    # フライヤー画面固有の新しいキー名に対応
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
            del st.session_state[session_key]

    # グリッド情報のロード
    grid_loaded = False
    if proj.grid_order_json:
        try:
            g_data = json.loads(proj.grid_order_json)
            if isinstance(g_data, dict):
                st.session_state.grid_order = g_data.get("order", [])
                st.session_state.grid_cols = g_data.get("cols", 5)
                st.session_state.grid_rows = g_data.get("rows", 5)
                grid_loaded = True
            elif isinstance(g_data, list):
                st.session_state.grid_order = g_data
                grid_loaded = True
        except: pass
    
    if not grid_loaded and proj.data_json:
        try:
            d = json.loads(proj.data_json)
            tt_artists = [i["ARTIST"] for i in d if i["ARTIST"] not in ["開演前物販", "終演後物販"]]
            st.session_state.grid_order = list(reversed(tt_artists))
            st.session_state.grid_cols = 5
            st.session_state.grid_rows = 5
        except: pass

# --- 保存処理 ---
def save_current_project(db, project_id):
    proj = db.query(TimetableProject).filter(TimetableProject.id == project_id).first()
    if not proj: return False
    
    # 基本情報
    if "proj_title" in st.session_state: proj.title = st.session_state.proj_title
    if "proj_date" in st.session_state: proj.event_date = st.session_state.proj_date.strftime("%Y-%m-%d")
    if "proj_venue" in st.session_state: proj.venue_name = st.session_state.proj_venue
    if "proj_url" in st.session_state: proj.venue_url = st.session_state.proj_url
    
    # ★変更: チケット・自由記述をJSONとして保存
    if "proj_tickets" in st.session_state:
        proj.tickets_json = json.dumps(st.session_state.proj_tickets, ensure_ascii=False)
    if "proj_free_text" in st.session_state:
        proj.free_text_json = json.dumps(st.session_state.proj_free_text, ensure_ascii=False)

    # タイムテーブルデータ
    if "binding_df" in st.session_state and not st.session_state.binding_df.empty:
        save_data = st.session_state.binding_df.to_dict(orient="records")
        proj.data_json = json.dumps(save_data, ensure_ascii=False)
    
    if "tt_open_time" in st.session_state: proj.open_time = st.session_state.tt_open_time
    if "tt_start_time" in st.session_state: proj.start_time = st.session_state.tt_start_time
    if "tt_goods_offset" in st.session_state: proj.goods_start_offset = st.session_state.tt_goods_offset

    # グリッド設定
    if "grid_order" in st.session_state:
        grid_data = {
            "cols": st.session_state.get("grid_cols", 5),
            "rows": st.session_state.get("grid_rows", 5),
            "order": st.session_state.grid_order
        }
        proj.grid_order_json = json.dumps(grid_data, ensure_ascii=False)

    # 画面設定
    settings = {
        "tt_font": st.session_state.get("tt_font", "keifont.ttf"),
        "grid_font": st.session_state.get("grid_font", "keifont.ttf")
    }
    proj.settings_json = json.dumps(settings, ensure_ascii=False)

    # フライヤー設定（新しいキー名に対応）
    flyer_data = {}
    keys = ["flyer_logo_id", "flyer_bg_id", "flyer_sub_title", "flyer_input_1", 
            "flyer_bottom_left", "flyer_bottom_right", "flyer_font", "flyer_text_color", "flyer_stroke_color"]
    for k in keys:
        if k in st.session_state:
            flyer_data[k.replace("flyer_", "")] = st.session_state[k]
    
    proj.flyer_json = json.dumps(flyer_data, ensure_ascii=False)
    db.commit()
    return True

# --- 複製処理 ---
def duplicate_project(db, project_id):
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

# --- メイン描画 ---
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

    selected_label = st.selectbox("作業するプロジェクトを選択", options, index=current_idx, key="ws_project_selector")

    if selected_label not in ["(選択してください)", "➕ 新規プロジェクト作成"]:
        selected_id = proj_map.get(selected_label)
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
        db.close()
        return

    if selected_label == "(選択してください)":
        st.info("👆 上のボックスからプロジェクトを選択するか、新規作成してください。")
        db.close()
        return

    # --- 編集画面 ---
    project_id = st.session_state.ws_active_project_id
    proj = db.query(TimetableProject).filter(TimetableProject.id == project_id).first()
    
    if not proj:
        st.error("プロジェクトが見つかりません")
        st.session_state.ws_active_project_id = None
        st.rerun()

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
            save_current_project(db, project_id)
            new_proj = duplicate_project(db, project_id)
            if new_proj:
                st.session_state.ws_active_project_id = new_proj.id
                load_project_to_session(new_proj)
                st.toast("プロジェクトを複製しました！", icon="✨")
                st.rerun()

    st.markdown(f"### 📂 {proj.title} <small>({proj.event_date} @ {proj.venue_name})</small>", unsafe_allow_html=True)

    # タブ表示
    tab_overview, tab_tt, tab_grid, tab_flyer = st.tabs(["📝 イベント概要", "⏱️ タイムテーブル", "🖼️ アー写グリッド", "📑 フライヤーセット"])

    # === 1. イベント概要タブ (ダイナミックフォーム実装) ===
    with tab_overview:
        st.subheader("基本情報")
        c_basic1, c_basic2 = st.columns(2)
        with c_basic1:
            st.date_input("開催日", key="proj_date")
            st.text_input("イベント名", key="proj_title")
        with c_basic2:
            st.text_input("会場名", key="proj_venue")
            st.text_input("会場URL", key="proj_url")
        
        st.divider()
        
        c_tic, c_free = st.columns(2)
        
        # --- チケット情報入力 (行追加・削除) ---
        with c_tic:
            st.subheader("チケット情報")
            if "proj_tickets" not in st.session_state:
                st.session_state.proj_tickets = [{"name":"", "price":"", "note":""}]
            
            # リストのコピーを使ってイテレーション
            for i, ticket in enumerate(st.session_state.proj_tickets):
                with st.container(border=True):
                    cols = st.columns([3, 2, 4, 1])
                    with cols[0]:
                        ticket["name"] = st.text_input("チケット名", value=ticket.get("name",""), key=f"t_name_{i}", label_visibility="collapsed", placeholder="Sチケット")
                    with cols[1]:
                        ticket["price"] = st.text_input("金額", value=ticket.get("price",""), key=f"t_price_{i}", label_visibility="collapsed", placeholder="¥3,000")
                    with cols[2]:
                        ticket["note"] = st.text_input("備考", value=ticket.get("note",""), key=f"t_note_{i}", label_visibility="collapsed", placeholder="ドリンク代別")
                    with cols[3]:
                        if st.button("🗑️", key=f"del_t_{i}"):
                            st.session_state.proj_tickets.pop(i)
                            st.rerun()
            
            if st.button("＋ 新しいチケットを追加"):
                st.session_state.proj_tickets.append({"name":"", "price":"", "note":""})
                st.rerun()

        # --- 自由記述入力 (行追加・削除) ---
        with c_free:
            st.subheader("自由記述 (注意事項など)")
            if "proj_free_text" not in st.session_state:
                st.session_state.proj_free_text = [{"title":"", "content":""}]
            
            for i, item in enumerate(st.session_state.proj_free_text):
                with st.container(border=True):
                    c_head, c_btn = st.columns([5, 1])
                    with c_head:
                        item["title"] = st.text_input("タイトル", value=item.get("title",""), key=f"f_title_{i}", placeholder="注意事項")
                    with c_btn:
                        if st.button("🗑️", key=f"del_f_{i}"):
                            st.session_state.proj_free_text.pop(i)
                            st.rerun()
                    
                    item["content"] = st.text_area("内容", value=item.get("content",""), key=f"f_content_{i}", height=100)

            if st.button("＋ 新しい項目を追加"):
                st.session_state.proj_free_text.append({"title":"", "content":""})
                st.rerun()

    # === 2. タイムテーブルタブ ===
    with tab_tt:
        render_timetable_page()
    
    # === 3. グリッドタブ ===
    with tab_grid:
        st.session_state.current_grid_proj_id = project_id
        render_grid_page()

    # === 4. フライヤータブ ===
    with tab_flyer:
        render_flyer_editor(project_id)

    db.close()
