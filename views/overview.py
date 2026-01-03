import streamlit as st
from datetime import datetime
import json
import traceback

# データベース関連
from database import get_db, TimetableProject
from logic_project import save_current_project, load_project_data
from constants import TIME_OPTIONS

# ★追加: 共通のテキスト生成ロジックをインポート
# （これにより、このファイル内で generate_event_text を定義する必要がなくなりました）
from utils.text_generator import build_event_summary_text

# ==========================================
# 定数定義
# ==========================================
# 既存の時間リストの先頭に選択肢を追加します
EXTENDED_TIME_OPTIONS = ["※調整中"] + TIME_OPTIONS

# ==========================================
# コールバック関数
# ==========================================
def update_time_sync(key_name):
    st.session_state[key_name] = st.session_state[f"ov_{key_name}"]

def update_ticket(i, field):
    key = f"t_{field}_{i}"
    if key in st.session_state and "proj_tickets" in st.session_state:
        st.session_state.proj_tickets[i][field] = st.session_state[key]

def update_note(i):
    key = f"t_common_note_{i}"
    if key in st.session_state and "proj_ticket_notes" in st.session_state:
        st.session_state.proj_ticket_notes[i] = st.session_state[key]

def update_free(i, field):
    key = f"f_{field}_{i}"
    if key in st.session_state and "proj_free_text" in st.session_state:
        st.session_state.proj_free_text[i][field] = st.session_state[key]

# ==========================================
# メイン描画関数
# ==========================================
def render_overview_page():
    
    project_id = st.session_state.get("ws_active_project_id")

    # --- 時間データ・サブタイトル復旧 ---
    if project_id:
        should_restore = False
        if "tt_open_time" not in st.session_state: should_restore = True
        if "tt_start_time" not in st.session_state: should_restore = True
        # ★追加: サブタイトルが未ロードの場合も復旧対象にする
        if "proj_subtitle" not in st.session_state: should_restore = True
        
        if should_restore:
            db = next(get_db())
            try:
                proj = db.query(TimetableProject).filter(TimetableProject.id == project_id).first()
                if proj:
                    # DB値があれば使う、なければ "※調整中"
                    st.session_state.tt_open_time = proj.open_time or "※調整中"
                    st.session_state.tt_start_time = proj.start_time or "※調整中"
                    # ★追加: サブタイトルのロード
                    st.session_state.proj_subtitle = getattr(proj, "subtitle", "")
            finally:
                db.close()
    
    # --- データロード (初回のみ) ---
    if project_id:
        if "proj_title" not in st.session_state:
            db = next(get_db())
            try:
                load_project_data(db, project_id)
                # ★追加: load_project_dataでサブタイトルが読まれていない場合の保険
                if "proj_subtitle" not in st.session_state:
                    proj = db.query(TimetableProject).filter(TimetableProject.id == project_id).first()
                    st.session_state.proj_subtitle = getattr(proj, "subtitle", "")

                st.session_state.overview_last_saved_params = {
                    "tickets": json.dumps(st.session_state.get("proj_tickets", []), sort_keys=True, ensure_ascii=False),
                    "notes": json.dumps(st.session_state.get("proj_ticket_notes", []), sort_keys=True, ensure_ascii=False),
                    "free": json.dumps(st.session_state.get("proj_free_text", []), sort_keys=True, ensure_ascii=False),
                    "title": st.session_state.get("proj_title", ""),
                    "subtitle": st.session_state.get("proj_subtitle", ""), # ★追加
                    "venue": st.session_state.get("proj_venue", ""),
                    "url": st.session_state.get("proj_url", ""),
                    "date": str(st.session_state.get("proj_date", "")),
                    "open": st.session_state.get("tt_open_time", ""),
                    "start": st.session_state.get("tt_start_time", "")
                }
            finally:
                db.close()

    # --- UI描画: 基本情報 ---
    st.subheader("基本情報")
    c_basic1, c_basic2 = st.columns(2)
    with c_basic1:
        st.date_input("開催日", key="proj_date")
        st.text_input("イベント名", key="proj_title")
        # ★追加: サブタイトル入力欄
        st.text_input("サブタイトル", key="proj_subtitle", placeholder="例：〜夏の特大号〜")
    with c_basic2:
        st.text_input("会場名", key="proj_venue")
        st.text_input("会場URL", key="proj_url")
    
    # --- UI描画: 時間設定 ---
    c_time1, c_time2 = st.columns(2)
    
    # 現在の値取得 (なければ ※調整中)
    curr_open = st.session_state.get("tt_open_time", "※調整中")
    curr_start = st.session_state.get("tt_start_time", "※調整中")
    
    # リストに含まれていない値の場合のフォールバック
    if curr_open not in EXTENDED_TIME_OPTIONS: curr_open = EXTENDED_TIME_OPTIONS[0]
    if curr_start not in EXTENDED_TIME_OPTIONS: curr_start = EXTENDED_TIME_OPTIONS[0]

    with c_time1:
        st.selectbox("OPEN", EXTENDED_TIME_OPTIONS, index=EXTENDED_TIME_OPTIONS.index(curr_open), 
                     key="ov_tt_open_time", on_change=update_time_sync, args=("tt_open_time",))
    with c_time2:
        st.selectbox("START", EXTENDED_TIME_OPTIONS, index=EXTENDED_TIME_OPTIONS.index(curr_start), 
                     key="ov_tt_start_time", on_change=update_time_sync, args=("tt_start_time",))

    st.divider()
    c_tic, c_free = st.columns(2)
    
    # --- チケット情報 ---
    with c_tic:
        st.subheader("チケット情報")
        if "proj_tickets" not in st.session_state:
            st.session_state.proj_tickets = [{"name":"", "price":"", "note":""}]
        
        clean_tickets = []
        for t in st.session_state.proj_tickets:
            if isinstance(t, dict): clean_tickets.append(t)
            else: clean_tickets.append({"name": str(t), "price":"", "note":""})
        st.session_state.proj_tickets = clean_tickets

        for i, ticket in enumerate(st.session_state.proj_tickets):
            with st.container(border=True):
                cols = st.columns([3, 2, 4, 1])
                with cols[0]: 
                    st.text_input("チケット名", value=ticket.get("name",""), key=f"t_name_{i}", 
                                  label_visibility="collapsed", placeholder="Sチケット",
                                  on_change=update_ticket, args=(i, "name"))
                with cols[1]: 
                    st.text_input("金額", value=ticket.get("price",""), key=f"t_price_{i}", 
                                  label_visibility="collapsed", placeholder="¥3,000",
                                  on_change=update_ticket, args=(i, "price"))
                with cols[2]: 
                    st.text_input("備考", value=ticket.get("note",""), key=f"t_note_{i}", 
                                  label_visibility="collapsed", placeholder="D代別",
                                  on_change=update_ticket, args=(i, "note"))
                with cols[3]:
                    if i > 0:
                        if st.button("🗑️", key=f"del_t_{i}"):
                            st.session_state.proj_tickets.pop(i)
                            st.rerun()
        
        if st.button("＋ 新しいチケットを追加"):
            st.session_state.proj_tickets.append({"name":"", "price":"", "note":""})
            st.rerun()

        # --- チケット共通備考 ---
        st.markdown("---") 
        st.markdown("**チケット共通備考**")

        if "proj_ticket_notes" not in st.session_state: st.session_state.proj_ticket_notes = []
        if not isinstance(st.session_state.proj_ticket_notes, list): st.session_state.proj_ticket_notes = []

        for i in range(len(st.session_state.proj_ticket_notes)):
            c_note_in, c_note_del = st.columns([8, 1])
            with c_note_in:
                st.text_input(
                    "共通備考",
                    value=st.session_state.proj_ticket_notes[i],
                    key=f"t_common_note_{i}",
                    label_visibility="collapsed",
                    placeholder="例：別途1ドリンク代が必要です",
                    on_change=update_note, args=(i,)
                )
            with c_note_del:
                if st.button("🗑️", key=f"del_t_common_{i}"):
                    st.session_state.proj_ticket_notes.pop(i)
                    st.rerun()

        if st.button("＋ チケット共通備考を追加"):
            st.session_state.proj_ticket_notes.append("")
            st.rerun()

    # --- 自由記述 ---
    with c_free:
        st.subheader("自由記述")
        if "proj_free_text" not in st.session_state:
            st.session_state.proj_free_text = [{"title":"", "content":""}]
        
        clean_free = []
        for f in st.session_state.proj_free_text:
            if isinstance(f, dict): clean_free.append(f)
            else: clean_free.append({"title": str(f), "content":""})
        st.session_state.proj_free_text = clean_free

        for i, item in enumerate(st.session_state.proj_free_text):
            with st.container(border=True):
                c_head, c_btn = st.columns([5, 1])
                with c_head: 
                    st.text_input("タイトル", value=item.get("title",""), key=f"f_title_{i}", 
                                  placeholder="注意事項",
                                  on_change=update_free, args=(i, "title"))
                with c_btn:
                    if i > 0:
                        if st.button("🗑️", key=f"del_f_{i}"):
                            st.session_state.proj_free_text.pop(i)
                            st.rerun()
                
                st.text_area("内容", value=item.get("content",""), key=f"f_content_{i}", 
                             height=100,
                             on_change=update_free, args=(i, "content"))

        if st.button("＋ 新しい項目を追加"):
            st.session_state.proj_free_text.append({"title":"", "content":""})
            st.rerun()

    st.divider()

    # --- 変更検知 ---
    # プレビュー同期 (ここでも最新の値を入れておく)
    if "ov_tt_open_time" in st.session_state:
        st.session_state.tt_open_time = st.session_state.ov_tt_open_time
    if "ov_tt_start_time" in st.session_state:
        st.session_state.tt_start_time = st.session_state.ov_tt_start_time

    current_params = {
        "tickets": json.dumps(st.session_state.get("proj_tickets", []), sort_keys=True, ensure_ascii=False),
        "notes": json.dumps(st.session_state.get("proj_ticket_notes", []), sort_keys=True, ensure_ascii=False),
        "free": json.dumps(st.session_state.get("proj_free_text", []), sort_keys=True, ensure_ascii=False),
        "title": st.session_state.get("proj_title", ""),
        "subtitle": st.session_state.get("proj_subtitle", ""), # ★追加: 検知対象に追加
        "venue": st.session_state.get("proj_venue", ""),
        "url": st.session_state.get("proj_url", ""),
        "date": str(st.session_state.get("proj_date", "")),
        "open": st.session_state.get("tt_open_time", ""),
        "start": st.session_state.get("tt_start_time", "")
    }

    if "overview_last_saved_params" not in st.session_state:
        st.session_state.overview_last_saved_params = current_params

    is_changed = (st.session_state.overview_last_saved_params != current_params)
    if is_changed:
        st.warning("⚠️ 設定が変更されています。最新の状態にするには「設定反映」ボタンを押してください。")
    
    st.caption("変更内容は以下のボタンで保存してください。")

    if st.button("🔄 設定反映 (保存＆テキスト生成)", type="primary", use_container_width=True, key="btn_overview_save"):
        
        # 最終同期
        if "proj_ticket_notes" in st.session_state:
            for i in range(len(st.session_state.proj_ticket_notes)):
                key = f"t_common_note_{i}"
                if key in st.session_state: st.session_state.proj_ticket_notes[i] = st.session_state[key]
        
        if project_id:
            db = next(get_db())
            try:
                # 時間・サブタイトルの保存
                proj = db.query(TimetableProject).filter(TimetableProject.id == project_id).first()
                if proj:
                    proj.open_time = st.session_state.tt_open_time
                    proj.start_time = st.session_state.tt_start_time
                    # ★追加: サブタイトルのDB保存（モデルにカラムがある前提）
                    if hasattr(proj, "subtitle"):
                        proj.subtitle = st.session_state.proj_subtitle

                if save_current_project(db, project_id):
                    st.toast("イベント情報を保存しました！", icon="✅")
                    
                    updated_params = {
                        "tickets": json.dumps(st.session_state.get("proj_tickets", []), sort_keys=True, ensure_ascii=False),
                        "notes": json.dumps(st.session_state.get("proj_ticket_notes", []), sort_keys=True, ensure_ascii=False),
                        "free": json.dumps(st.session_state.get("proj_free_text", []), sort_keys=True, ensure_ascii=False),
                        "title": st.session_state.get("proj_title", ""),
                        "subtitle": st.session_state.get("proj_subtitle", ""), # ★追加
                        "venue": st.session_state.get("proj_venue", ""),
                        "url": st.session_state.get("proj_url", ""),
                        "date": str(st.session_state.get("proj_date", "")),
                        "open": st.session_state.get("tt_open_time", ""),
                        "start": st.session_state.get("tt_start_time", "")
                    }
                    st.session_state.overview_last_saved_params = updated_params
                    st.rerun()
                else:
                    st.error("保存に失敗しました")
            except Exception as e:
                st.error(f"保存エラー: {e}")
                st.code(traceback.format_exc())
            finally:
                db.close()
        else:
            st.error("プロジェクトIDが不明です")

    # ==========================================
    # ★修正: 共通関数を使用してプレビュー生成
    # ==========================================
    
    # Session Stateから必要なデータを収集して共通ロジックに渡す
    artists_list = st.session_state.get("grid_order") or st.session_state.get("tt_artists_order", [])
    
    generated_text = build_event_summary_text(
        title=st.session_state.get("proj_title", ""),
        subtitle=st.session_state.get("proj_subtitle", ""),
        date_val=st.session_state.get("proj_date"),
        venue=st.session_state.get("proj_venue", ""),
        url=st.session_state.get("proj_url", ""),
        open_time=st.session_state.get("tt_open_time", "※調整中"),
        start_time=st.session_state.get("tt_start_time", "※調整中"),
        tickets=st.session_state.get("proj_tickets", []),
        ticket_notes=st.session_state.get("proj_ticket_notes", []),
        artists=artists_list,
        free_texts=st.session_state.get("proj_free_text", [])
    )

    st.session_state.txt_overview_preview_area = generated_text

    st.subheader("📝 告知用テキストプレビュー")
    st.text_area("コピーしてSNSなどで使用できます", height=400, key="txt_overview_preview_area")
