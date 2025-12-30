import streamlit as st
from datetime import date

def render_overview_page():
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
