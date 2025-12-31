import streamlit as st
from datetime import datetime
import json

# データベース関連
from database import get_db, TimetableProject
from logic_project import save_current_project, load_project_data

# ==========================================
# ヘルパー関数 (generate_event_textなど)
# ==========================================
def get_day_of_week_jp(dt):
    if not dt: return ""
    w_list = ['(月)', '(火)', '(水)', '(木)', '(金)', '(土)', '(日)']
    return w_list[dt.weekday()]

def get_circled_number(n):
    if 1 <= n <= 20:
        return chr(0x2460 + (n - 1))
    elif 21 <= n <= 35:
        return chr(0x3251 + (n - 21))
    elif 36 <= n <= 50:
        return chr(0x32B1 + (n - 36))
    else:
        return f"({n})"

def generate_event_text():
    """イベント概要テキストを生成"""
    try:
        title = st.session_state.get("proj_title", "")
        date_val = st.session_state.get("proj_date")
        venue = st.session_state.get("proj_venue", "")
        url = st.session_state.get("proj_url", "")
        
        date_str = ""
        if date_val:
            date_str = date_val.strftime("%Y年%m月%d日") + get_day_of_week_jp(date_val)
        
        open_t = st.session_state.get("tt_open_time", "10:00")
        start_t = st.session_state.get("tt_start_time", "10:30")
        
        text = f"【公演概要】\n{date_str}\n『{title}』\n\n■会場: {venue}"
        if url: text += f"\n {url}"
        text += f"\n\nOPEN▶{open_t}\nSTART▶{start_t}"

        text += "\n\n■チケット"
        if "proj_tickets" in st.session_state and st.session_state.proj_tickets:
            for t in st.session_state.proj_tickets:
                name = t.get("name", "")
                price = t.get("price", "")
                note = t.get("note", "")
                line = f"- {name}: {price}"
                if note: line += f" ({note})"
                if name or price: text += "\n" + line
        else:
            text += "\n(情報なし)"

        # 共通備考の反映
        if "proj_ticket_notes" in st.session_state and st.session_state.proj_ticket_notes:
            for note in st.session_state.proj_ticket_notes:
                if note and str(note).strip():
                    text += f"\n※{str(note).strip()}"

        artists = st.session_state.get("grid_order") or st.session_state.get("tt_artists_order", [])
        valid_artists = list(dict.fromkeys(artists))

        if valid_artists:
            text += f"\n\n■出演者（{len(valid_artists)}組予定）"
            for i, artist_name in enumerate(valid_artists, 1):
                c_num = get_circled_number(i)
                text += f"\n{c_num}{artist_name}"

        if "proj_free_text" in st.session_state and st.session_state.proj_free_text:
            for f in st.session_state.proj_free_text:
                ft = f.get("title", "")
                fc = f.get("content", "")
                if ft or fc:
                    text += f"\n\n■{ft}\n{fc}"
        return text
    except Exception as e:
        return f"エラー: {e}"

# ==========================================
# メイン描画関数
# ==========================================
def render_overview_page():
    """イベント概要の編集画面"""
    
    project_id = st.session_state.get("ws_active_project_id")

    # --- 時間データ復旧 (セッション切れ対策) ---
    if project_id:
        should_restore = False
        if "tt_open_time" not in st.session_state: should_restore = True
        if "tt_start_time" not in st.session_state: should_restore = True
        
        if should_restore:
            db = next(get_db())
            try:
                proj = db.query(TimetableProject).filter(TimetableProject.id == project_id).first()
                if proj:
                    st.session_state.tt_open_time = proj.open_time or "10:00"
                    st.session_state.tt_start_time = proj.start_time or "10:30"
            finally:
                db.close()
    
    # --- データロード (workspace.py経由ならスキップされる) ---
    if project_id:
        if "proj_title" not in st.session_state:
            db = next(get_db())
            try:
                # ここが実行されるのはセッションが飛んだ場合のみ
                load_project_data(db, project_id)
                st.session_state.overview_last_saved_params = {
                    "tickets": json.dumps(st.session_state.get("proj_tickets", []), sort_keys=True, ensure_ascii=False),
                    "notes": json.dumps(st.session_state.get("proj_ticket_notes", []), sort_keys=True, ensure_ascii=False),
                    "free": json.dumps(st.session_state.get("proj_free_text", []), sort_keys=True, ensure_ascii=False),
                    "title": st.session_state.get("proj_title", ""),
                    "venue": st.session_state.get("proj_venue", ""),
                    "url": st.session_state.get("proj_url", ""),
                    "date": str(st.session_state.get("proj_date", ""))
                }
            finally:
                db.close()

    # --- UI描画 ---
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
    
    # チケット情報
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
                with cols[0]: ticket["name"] = st.text_input("チケット名", value=ticket.get("name",""), key=f"t_name_{i}", label_visibility="collapsed", placeholder="Sチケット")
                with cols[1]: ticket["price"] = st.text_input("金額", value=ticket.get("price",""), key=f"t_price_{i}", label_visibility="collapsed", placeholder="¥3,000")
                with cols[2]: ticket["note"] = st.text_input("備考", value=ticket.get("note",""), key=f"t_note_{i}", label_visibility="collapsed", placeholder="D代別")
                with cols[3]:
                    if i > 0:
                        if st.button("🗑️", key=f"del_t_{i}"):
                            st.session_state.proj_tickets.pop(i)
                            st.rerun()
        
        if st.button("＋ 新しいチケットを追加"):
            st.session_state.proj_tickets.append({"name":"", "price":"", "note":""})
            st.rerun()

        # チケット共通備考
        st.markdown("---") 
        st.markdown("**チケット共通備考**")

        if "proj_ticket_notes" not in st.session_state: st.session_state.proj_ticket_notes = []
        if not isinstance(st.session_state.proj_ticket_notes, list): st.session_state.proj_ticket_notes = []

        current_notes = st.session_state.proj_ticket_notes
        for i in range(len(current_notes)):
            c_note_in, c_note_del = st.columns([8, 1])
            with c_note_in:
                val = st.text_input("共通備考", value=current_notes[i], key=f"t_common_note_{i}", label_visibility="collapsed", placeholder="例：別途1ドリンク代が必要です")
                current_notes[i] = val 
            with c_note_del:
                if st.button("🗑️", key=f"del_t_common_{i}"):
                    st.session_state.proj_ticket_notes.pop(i)
                    st.rerun()

        if st.button("＋ チケット共通備考を追加"):
            st.session_state.proj_ticket_notes.append("")
            # ★追加: ここでrerunすると、workspace.pyのload処理が走らないことを確認済み(ID不変のため)
            st.rerun()

    # 自由記述
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
                with c_head: item["title"] = st.text_input("タイトル", value=item.get("title",""), key=f"f_title_{i}", placeholder="注意事項")
                with c_btn:
                    if i > 0:
                        if st.button("🗑️", key=f"del_f_{i}"):
                            st.session_state.proj_free_text.pop(i)
                            st.rerun()
                item["content"] = st.text_area("内容", value=item.get("content",""), key=f"f_content_{i}", height=100)

        if st.button("＋ 新しい項目を追加"):
            st.session_state.proj_free_text.append({"title":"", "content":""})
            st.rerun()

    st.divider()

    # 変更検知ロジック
    current_params = {
        "tickets": json.dumps(st.session_state.get("proj_tickets", []), sort_keys=True, ensure_ascii=False),
        "notes": json.dumps(st.session_state.get("proj_ticket_notes", []), sort_keys=True, ensure_ascii=False),
        "free": json.dumps(st.session_state.get("proj_free_text", []), sort_keys=True, ensure_ascii=False),
        "title": st.session_state.get("proj_title", ""),
        "venue": st.session_state.get("proj_venue", ""),
        "url": st.session_state.get("proj_url", ""),
        "date": str(st.session_state.get("proj_date", ""))
    }

    if "overview_last_saved_params" not in st.session_state:
        st.session_state.overview_last_saved_params = current_params

    is_changed = (st.session_state.overview_last_saved_params != current_params)
    if is_changed:
        st.warning("⚠️ 設定が変更されています。最新の状態にするには「設定反映」ボタンを押してください。")
    
    st.caption("変更内容は以下のボタンで保存してください。")

    if st.button("🔄 設定反映 (保存＆テキスト生成)", type="primary", use_container_width=True, key="btn_overview_save"):
        # 強制同期
        if "proj_ticket_notes" in st.session_state:
            for i in range(len(st.session_state.proj_ticket_notes)):
                widget_key = f"t_common_note_{i}"
                if widget_key in st.session_state: st.session_state.proj_ticket_notes[i] = st.session_state[widget_key]
        
        if "proj_tickets" in st.session_state:
            for i, ticket in enumerate(st.session_state.proj_tickets):
                if f"t_name_{i}" in st.session_state: ticket["name"] = st.session_state[f"t_name_{i}"]
                if f"t_price_{i}" in st.session_state: ticket["price"] = st.session_state[f"t_price_{i}"]
                if f"t_note_{i}" in st.session_state: ticket["note"] = st.session_state[f"t_note_{i}"]

        if "proj_free_text" in st.session_state:
            for i, item in enumerate(st.session_state.proj_free_text):
                if f"f_title_{i}" in st.session_state: item["title"] = st.session_state[f"f_title_{i}"]
                if f"f_content_{i}" in st.session_state: item["content"] = st.session_state[f"f_content_{i}"]
        
        # 保存実行
        if project_id:
            db = next(get_db())
            try:
                if save_current_project(db, project_id):
                    st.toast("イベント情報を保存しました！", icon="✅")
                    # 最新状態をスナップショットに保存
                    updated_params = {
                        "tickets": json.dumps(st.session_state.get("proj_tickets", []), sort_keys=True, ensure_ascii=False),
                        "notes": json.dumps(st.session_state.get("proj_ticket_notes", []), sort_keys=True, ensure_ascii=False),
                        "free": json.dumps(st.session_state.get("proj_free_text", []), sort_keys=True, ensure_ascii=False),
                        "title": st.session_state.get("proj_title", ""),
                        "venue": st.session_state.get("proj_venue", ""),
                        "url": st.session_state.get("proj_url", ""),
                        "date": str(st.session_state.get("proj_date", ""))
                    }
                    st.session_state.overview_last_saved_params = updated_params
                    st.rerun()
                else:
                    st.error("保存に失敗しました")
            except Exception as e:
                st.error(f"保存エラー: {e}")
            finally:
                db.close()
        else:
            st.error("プロジェクトIDが不明です")

    # プレビュー生成
    st.session_state.txt_overview_preview_area = generate_event_text()

    st.subheader("📝 告知用テキストプレビュー")
    st.text_area("コピーしてSNSなどで使用できます", height=400, key="txt_overview_preview_area")

