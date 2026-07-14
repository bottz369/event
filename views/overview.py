import streamlit as st
from datetime import datetime
import json
import traceback

# データベース関連
from database import get_db, TimetableProject, TimetableRow
from logic_project import load_project_data
from constants import TIME_OPTIONS

# Phase 2B-1b: save_active_project 経由に切替
from services import project_service

# 共通のテキスト生成ロジック
from utils.text_generator import build_event_summary_text

# ==========================================
# 定数定義
# ==========================================
EXTENDED_TIME_OPTIONS = ["※調整中"] + TIME_OPTIONS

# ==========================================
# コールバック関数
# ==========================================
# フェーズ1 workaround:
# widget key にプロジェクトID を含めるようにしたので、コールバックもそれに合わせて
# project_id 引数を受け取る形に変更している。フェーズ2 で overview.py 全面書き換え時に
# この workaround は不要になる予定。
# Phase 2B-1b: update_time_sync は OPEN/START を直接バインドに切り替えたため削除。
def update_ticket(i, field, project_id):
    key = f"t_{field}_{project_id}_{i}"
    if key in st.session_state and "proj_tickets" in st.session_state:
        st.session_state.proj_tickets[i][field] = st.session_state[key]

def update_note(i, project_id):
    key = f"t_common_note_{project_id}_{i}"
    if key in st.session_state and "proj_ticket_notes" in st.session_state:
        st.session_state.proj_ticket_notes[i] = st.session_state[key]

def update_free(i, field, project_id):
    key = f"f_{field}_{project_id}_{i}"
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
        if "proj_subtitle" not in st.session_state: should_restore = True
        
        if should_restore:
            db = next(get_db())
            try:
                proj = db.query(TimetableProject).filter(TimetableProject.id == project_id).first()
                if proj:
                    st.session_state.tt_open_time = proj.open_time or "※調整中"
                    st.session_state.tt_start_time = proj.start_time or "※調整中"
                    st.session_state.proj_subtitle = getattr(proj, "subtitle", "")
            finally:
                db.close()
    
    # --- データロード (初回のみ) ---
    if project_id:
        if "proj_title" not in st.session_state:
            db = next(get_db())
            try:
                load_project_data(db, project_id)
                if "proj_subtitle" not in st.session_state:
                    proj = db.query(TimetableProject).filter(TimetableProject.id == project_id).first()
                    st.session_state.proj_subtitle = getattr(proj, "subtitle", "")

                st.session_state.overview_last_saved_params = {
                    "tickets": json.dumps(st.session_state.get("proj_tickets", []), sort_keys=True, ensure_ascii=False),
                    "notes": json.dumps(st.session_state.get("proj_ticket_notes", []), sort_keys=True, ensure_ascii=False),
                    "free": json.dumps(st.session_state.get("proj_free_text", []), sort_keys=True, ensure_ascii=False),
                    "title": st.session_state.get("proj_title", ""),
                    "subtitle": st.session_state.get("proj_subtitle", ""),
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
        st.text_input("サブタイトル", key="proj_subtitle", placeholder="例：〜夏の特大号〜")
    with c_basic2:
        st.text_input("会場名", key="proj_venue")
        st.text_input("会場URL", key="proj_url")
    
    # --- UI描画: 時間設定 ---
    # Phase 2B-1b: 間接バインドを廃止し、key="tt_open_time" / "tt_start_time" で直接バインドする。
    # session_state の値が選択肢に無い場合は強制的に有効値に更新(防御的)。
    if st.session_state.get("tt_open_time") not in EXTENDED_TIME_OPTIONS:
        st.session_state["tt_open_time"] = EXTENDED_TIME_OPTIONS[0]
    if st.session_state.get("tt_start_time") not in EXTENDED_TIME_OPTIONS:
        st.session_state["tt_start_time"] = EXTENDED_TIME_OPTIONS[0]

    c_time1, c_time2 = st.columns(2)
    with c_time1:
        st.selectbox("OPEN", EXTENDED_TIME_OPTIONS, key="tt_open_time")
    with c_time2:
        st.selectbox("START", EXTENDED_TIME_OPTIONS, key="tt_start_time")

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
                    st.text_input("チケット名", value=ticket.get("name",""), key=f"t_name_{project_id}_{i}",
                                  label_visibility="collapsed", placeholder="Sチケット",
                                  on_change=update_ticket, args=(i, "name", project_id))
                with cols[1]:
                    st.text_input("金額", value=ticket.get("price",""), key=f"t_price_{project_id}_{i}",
                                  label_visibility="collapsed", placeholder="¥3,000",
                                  on_change=update_ticket, args=(i, "price", project_id))
                with cols[2]:
                    st.text_input("備考", value=ticket.get("note",""), key=f"t_note_{project_id}_{i}",
                                  label_visibility="collapsed", placeholder="D代別",
                                  on_change=update_ticket, args=(i, "note", project_id))
                with cols[3]:
                    if i > 0:
                        if st.button("🗑️", key=f"del_t_{project_id}_{i}"):
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
                    key=f"t_common_note_{project_id}_{i}",
                    label_visibility="collapsed",
                    placeholder="例：別途1ドリンク代が必要です",
                    on_change=update_note, args=(i, project_id)
                )
            with c_note_del:
                if st.button("🗑️", key=f"del_t_common_{project_id}_{i}"):
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
                    st.text_input("タイトル", value=item.get("title",""), key=f"f_title_{project_id}_{i}",
                                  placeholder="注意事項",
                                  on_change=update_free, args=(i, "title", project_id))
                with c_btn:
                    if i > 0:
                        if st.button("🗑️", key=f"del_f_{project_id}_{i}"):
                            st.session_state.proj_free_text.pop(i)
                            st.rerun()

                st.text_area("内容", value=item.get("content",""), key=f"f_content_{project_id}_{i}",
                             height=100,
                             on_change=update_free, args=(i, "content", project_id))

        if st.button("＋ 新しい項目を追加"):
            st.session_state.proj_free_text.append({"title":"", "content":""})
            st.rerun()

    st.divider()

    # --- (削除: 強制同期ロジック) ---

    current_params = {
        "tickets": json.dumps(st.session_state.get("proj_tickets", []), sort_keys=True, ensure_ascii=False),
        "notes": json.dumps(st.session_state.get("proj_ticket_notes", []), sort_keys=True, ensure_ascii=False),
        "free": json.dumps(st.session_state.get("proj_free_text", []), sort_keys=True, ensure_ascii=False),
        "title": st.session_state.get("proj_title", ""),
        "subtitle": st.session_state.get("proj_subtitle", ""),
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

    if st.button("🔄 設定反映 (保存＆テキスト生成)", type="primary", width='stretch', key="btn_overview_save"):
        if "proj_ticket_notes" in st.session_state:
            for i in range(len(st.session_state.proj_ticket_notes)):
                key = f"t_common_note_{project_id}_{i}"
                if key in st.session_state: st.session_state.proj_ticket_notes[i] = st.session_state[key]
        
        if project_id:
            try:
                # Phase 2B-1b: save_active_project() 経由で保存
                # sync_session_to_draft が proj_title / proj_subtitle / proj_date / proj_venue / proj_url /
                # tt_open_time / tt_start_time / proj_tickets / proj_ticket_notes / proj_free_text を
                # draft_project に同期 → apply_draft で DB へ書き出す。
                if project_service.save_active_project():
                    st.toast("イベント情報を保存しました！", icon="✅")

                    updated_params = {
                        "tickets": json.dumps(st.session_state.get("proj_tickets", []), sort_keys=True, ensure_ascii=False),
                        "notes": json.dumps(st.session_state.get("proj_ticket_notes", []), sort_keys=True, ensure_ascii=False),
                        "free": json.dumps(st.session_state.get("proj_free_text", []), sort_keys=True, ensure_ascii=False),
                        "title": st.session_state.get("proj_title", ""),
                        "subtitle": st.session_state.get("proj_subtitle", ""),
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
        else:
            st.error("プロジェクトIDが不明です")

    # ==========================================
    # ★リスト生成ロジック (非表示対応済)
    # ==========================================
    
    artists_list = []
    
    if project_id:
        db = next(get_db())
        try:
            rows = db.query(TimetableRow).filter(TimetableRow.project_id == project_id).all()
            
            hidden_map = {}
            for r in rows:
                if r.artist_name:
                    hidden_map[r.artist_name] = r.is_hidden

            raw_order = st.session_state.get("grid_order", [])
            
            if not raw_order:
                proj = db.query(TimetableProject).filter(TimetableProject.id == project_id).first()
                if proj and proj.grid_order_json:
                    try:
                        grid_data = json.loads(proj.grid_order_json)
                        if isinstance(grid_data, dict):
                            raw_order = grid_data.get("order", [])
                        elif isinstance(grid_data, list):
                            raw_order = grid_data
                    except Exception:
                        pass
            
            if not raw_order and rows:
                sorted_rows = sorted(rows, key=lambda x: x.sort_order)
                raw_order = [r.artist_name for r in sorted_rows]

            final_artists = []
            for name in raw_order:
                if name in ["開演前物販", "終演後物販"]:
                    continue
                
                is_hidden = hidden_map.get(name, False)
                
                if not is_hidden:
                    final_artists.append(name)
            
            artists_list = final_artists

        except Exception as e:
            st.error(f"リスト生成エラー: {e}")
            artists_list = st.session_state.get("grid_order", [])
        finally:
            db.close()
    
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
