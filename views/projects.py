import streamlit as st
import json
import pandas as pd
from datetime import date, datetime
from database import get_db, TimetableProject

def render_projects_page():
    st.title("📂 プロジェクト管理")
    db = next(get_db())
    
    tab_new, tab_list = st.tabs(["新規作成", "プロジェクト一覧"])
    
    # --- タブ1: 新規作成 ---
    with tab_new:
        st.subheader("新規プロジェクト作成")
        with st.form("new_project_form"):
            c1, c2 = st.columns(2)
            with c1:
                p_date = st.date_input("開催日 (必須)", value=date.today())
                p_title = st.text_input("イベント名 (必須)")
            with c2:
                p_venue = st.text_input("会場名 (必須)")
                p_url = st.text_input("会場URL")

            st.divider()
            st.markdown("##### 🎟️ チケット設定")
            if "new_tickets" not in st.session_state:
                st.session_state.new_tickets = [{"name": "", "price": "", "note": ""}]
            
            for i, ticket in enumerate(st.session_state.new_tickets):
                c1, c2, c3 = st.columns([2, 1, 2])
                with c1: ticket["name"] = st.text_input(f"チケット名 {i+1}", value=ticket["name"], key=f"t_name_{i}")
                with c2: ticket["price"] = st.text_input(f"代金 {i+1}", value=ticket["price"], key=f"t_price_{i}")
                with c3: ticket["note"] = st.text_input(f"備考 {i+1}", value=ticket["note"], key=f"t_note_{i}")
            
            if st.form_submit_button("＋ チケット行を追加"):
                st.session_state.new_tickets.append({"name": "", "price": "", "note": ""})
                st.rerun()

            st.divider()
            st.markdown("##### 📝 自由入力情報")
            if "new_free_texts" not in st.session_state:
                st.session_state.new_free_texts = [{"title": "", "content": ""}]
            
            for i, ft in enumerate(st.session_state.new_free_texts):
                ft["title"] = st.text_input(f"タイトル {i+1}", value=ft["title"], key=f"ft_title_{i}")
                ft["content"] = st.text_area(f"内容 {i+1}", value=ft["content"], key=f"ft_content_{i}")
            
            if st.form_submit_button("＋ 自由入力セットを追加"):
                st.session_state.new_free_texts.append({"title": "", "content": ""})
                st.rerun()

            st.divider()
            if st.form_submit_button("保存して作成", type="primary"):
                if not p_title or not p_venue:
                    st.error("開催日、イベント名、会場名は必須です")
                else:
                    new_proj = TimetableProject(
                        title=p_title,
                        event_date=p_date.strftime("%Y-%m-%d"),
                        venue_name=p_venue,
                        venue_url=p_url,
                        tickets_json=json.dumps(st.session_state.new_tickets, ensure_ascii=False),
                        free_text_json=json.dumps(st.session_state.new_free_texts, ensure_ascii=False),
                        open_time="10:00", start_time="10:30"
                    )
                    db.add(new_proj)
                    db.commit()
                    st.session_state.new_tickets = [{"name": "", "price": "", "note": ""}]
                    st.session_state.new_free_texts = [{"title": "", "content": ""}]
                    st.success("プロジェクトを作成しました！一覧タブで確認してください。")

    # --- タブ2: プロジェクト一覧 ---
    with tab_list:
        if "edit_proj_id" not in st.session_state: st.session_state.edit_proj_id = None
        projects = db.query(TimetableProject).all()
        projects.sort(key=lambda x: x.event_date or "0000-00-00", reverse=True)

        if not projects:
            st.info("プロジェクトがありません。")
        
        for proj in projects:
            with st.container(border=True):
                # === 編集モード ===
                if st.session_state.edit_proj_id == proj.id:
                    st.caption(f"編集中: ID {proj.id}")
                    # 基本情報
                    e_date = st.date_input("開催日", value=datetime.strptime(proj.event_date, "%Y-%m-%d").date() if proj.event_date else date.today(), key=f"e_date_{proj.id}")
                    e_title = st.text_input("イベント名", value=proj.title, key=f"e_title_{proj.id}")
                    e_venue = st.text_input("会場名", value=proj.venue_name, key=f"e_venue_{proj.id}")
                    e_url = st.text_input("会場URL", value=proj.venue_url or "", key=f"e_url_{proj.id}")
                    
                    st.divider()
                    # チケット編集
                    st.markdown("🎟️ **チケット情報**")
                    t_list = json.loads(proj.tickets_json) if proj.tickets_json else [{"name":"", "price":"", "note":""}]
                    t_df = pd.DataFrame(t_list)
                    edited_t = st.data_editor(t_df, key=f"et_{proj.id}", num_rows="dynamic", use_container_width=True, 
                                              column_config={"name":"チケット名", "price":"代金", "note":"備考"})
                    
                    # 自由入力編集
                    st.markdown("📝 **自由入力情報**")
                    f_list = json.loads(proj.free_text_json) if proj.free_text_json else [{"title":"", "content":""}]
                    f_df = pd.DataFrame(f_list)
                    edited_f = st.data_editor(f_df, key=f"ef_{proj.id}", num_rows="dynamic", use_container_width=True,
                                              column_config={"title":"タイトル", "content":"内容"})
                    
                    c1, c2 = st.columns(2)
                    with c1:
                        if st.button("変更を保存", key=f"sv_p_{proj.id}", type="primary"):
                            proj.event_date = e_date.strftime("%Y-%m-%d")
                            proj.title = e_title
                            proj.venue_name = e_venue
                            proj.venue_url = e_url
                            proj.tickets_json = json.dumps(edited_t.to_dict(orient="records"), ensure_ascii=False)
                            proj.free_text_json = json.dumps(edited_f.to_dict(orient="records"), ensure_ascii=False)
                            db.commit()
                            st.session_state.edit_proj_id = None
                            st.success("更新しました")
                            st.rerun()
                    with c2:
                        if st.button("キャンセル", key=f"cn_p_{proj.id}"):
                            st.session_state.edit_proj_id = None
                            st.rerun()

                # === 通常表示 ===
                else:
                    c1, c2 = st.columns([4, 1])
                    with c1:
                        st.subheader(f"{proj.event_date} : {proj.title}")
                        st.text(f"📍 {proj.venue_name}")
                        if proj.venue_url: st.markdown(f"[会場URL]({proj.venue_url})")
                    with c2:
                        if st.button("編集", key=f"ed_p_{proj.id}"):
                            st.session_state.edit_proj_id = proj.id
                            st.rerun()
                        if st.button("削除", key=f"del_p_{proj.id}"):
                            db.delete(proj)
                            db.commit()
                            st.rerun()
    db.close()
