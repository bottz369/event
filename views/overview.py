import streamlit as st
from datetime import datetime
from logic_project import save_current_project

def generate_event_text():
    """イベント概要をテキスト形式で生成する（SNS投稿用など）"""
    title = st.session_state.get("proj_title", "")
    date_val = st.session_state.get("proj_date")
    venue = st.session_state.get("proj_venue", "")
    url = st.session_state.get("proj_url", "")
    
    date_str = date_val.strftime("%Y年%m月%d日") if date_val else ""
    open_t = st.session_state.get("tt_open_time", "10:00")
    start_t = st.session_state.get("tt_start_time", "10:30")
    
    text = f"""【イベント情報】
{date_str}
『{title}』
会場: {venue}
OPEN {open_t} / START {start_t}

🎫 チケット"""
    
    if "proj_tickets" in st.session_state:
        for t in st.session_state.proj_tickets:
            name = t.get("name", "")
            price = t.get("price", "")
            note = t.get("note", "")
            line = f"- {name}: {price}"
            if note: line += f" ({note})"
            if name or price: text += "\n" + line
    
    if url:
        text += f"\n\n🔗 詳細・予約:\n{url}"
        
    if "proj_free_text" in st.session_state:
        for f in st.session_state.proj_free_text:
            ft = f.get("title", "")
            fc = f.get("content", "")
            if ft or fc:
                text += f"\n\n■ {ft}\n{fc}"
                
    return text

def render_overview_page():
    """イベント概要（基本情報・チケット・自由記述）の編集画面"""
    
    # プロジェクトIDの取得（保存用）
    project_id = st.session_state.get("ws_active_project_id")
    db = next(get_db_session_helper()) # DBセッション取得用のヘルパーが必要ですが、ここでは簡易的にimport元を想定

    # --- 基本情報 ---
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
    
    # --- チケット情報入力 ---
    with c_tic:
        st.subheader("チケット情報")
        if "proj_tickets" not in st.session_state:
            st.session_state.proj_tickets = [{"name":"", "price":"", "note":""}]
        
        # データ修復
        clean_tickets = []
        for t in st.session_state.proj_tickets:
            if isinstance(t, dict): clean_tickets.append(t)
            else: clean_tickets.append({"name": str(t), "price":"", "note":""})
        st.session_state.proj_tickets = clean_tickets

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
                    if i > 0:
                        if st.button("🗑️", key=f"del_t_{i}"):
                            st.session_state.proj_tickets.pop(i)
                            st.rerun()
        
        if st.button("＋ 新しいチケットを追加"):
            st.session_state.proj_tickets.append({"name":"", "price":"", "note":""})
            st.rerun()

    # --- 自由記述入力 ---
    with c_free:
        st.subheader("自由記述 (注意事項など)")
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
                    item["title"] = st.text_input("タイトル", value=item.get("title",""), key=f"f_title_{i}", placeholder="注意事項")
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

    # --- ★追加: 設定反映 & テキストプレビューエリア ---
    # レイアウトを他のタブに合わせる
    st.caption("変更内容は以下のボタンで保存してください。同時に告知用テキストを生成します。")
    
    if st.button("🔄 設定反映 (保存＆テキスト生成)", type="primary", use_container_width=True, key="btn_overview_save"):
        if project_id:
            # DB接続を取得して保存実行
            from database import get_db
            db = next(get_db())
            try:
                if save_current_project(db, project_id):
                    st.toast("イベント情報を保存しました！", icon="✅")
                    
                    # テキスト生成してセッションに保存（再描画後も表示するため）
                    st.session_state.overview_text_preview = generate_event_text()
                else:
                    st.error("保存に失敗しました")
            finally:
                db.close()
        else:
            st.error("プロジェクトが選択されていません")

    # 生成されたテキストがあれば表示
    if "overview_text_preview" in st.session_state and st.session_state.overview_text_preview:
        st.subheader("📝 告知用テキストプレビュー")
        st.text_area("コピーしてSNSなどで使用できます", value=st.session_state.overview_text_preview, height=300, key="txt_preview_area")

# ヘルパー関数 (DBセッション取得用)
def get_db_session_helper():
    from database import get_db
    return get_db()
