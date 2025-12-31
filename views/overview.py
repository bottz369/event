import streamlit as st
from datetime import datetime
from logic_project import save_current_project

# --- ヘルパー関数 ---
def get_day_of_week_jp(dt):
    """日付から日本語の曜日を取得 (月)〜(日)"""
    w_list = ['(月)', '(火)', '(水)', '(木)', '(金)', '(土)', '(日)']
    return w_list[dt.weekday()]

def get_circled_number(n):
    """数値を丸数字の文字に変換 (1->① ... 50->㊿)"""
    if 1 <= n <= 20:
        return chr(0x2460 + (n - 1))
    elif 21 <= n <= 35:
        return chr(0x3251 + (n - 21))
    elif 36 <= n <= 50:
        return chr(0x32B1 + (n - 36))
    else:
        return f"({n})"

def generate_event_text():
    """
    イベント概要を新しいフォーマットで生成する
    """
    # 1. 基本情報の取得
    title = st.session_state.get("proj_title", "")
    date_val = st.session_state.get("proj_date")
    venue = st.session_state.get("proj_venue", "")
    url = st.session_state.get("proj_url", "")
    
    # 日付フォーマット: 2026年2月15日(日)
    date_str = ""
    if date_val:
        date_str = date_val.strftime("%Y年%m月%d日") + get_day_of_week_jp(date_val)
    
    open_t = st.session_state.get("tt_open_time", "10:00")
    start_t = st.session_state.get("tt_start_time", "10:30")
    
    # 2. テキスト構築開始
    text = f"""【公演概要】
{date_str}
『{title}』

■会場: {venue}"""

    if url:
        text += f"\n {url}"

    text += f"\n\nOPEN▶{open_t}\nSTART▶{start_t}"

    # 3. チケット情報
    text += "\n\n■チケット"
    if "proj_tickets" in st.session_state and st.session_state.proj_tickets:
        for t in st.session_state.proj_tickets:
            name = t.get("name", "")
            price = t.get("price", "")
            note = t.get("note", "")
            # フォーマット: - Sチケット: ¥6,000 (備考)
            line = f"- {name}: {price}"
            if note:
                line += f" ({note})"
            if name or price:
                text += "\n" + line
    else:
        text += "\n(情報なし)"

    # ★追加: チケット共通備考 (テキスト生成への反映)
    if "proj_ticket_notes" in st.session_state and st.session_state.proj_ticket_notes:
        for note in st.session_state.proj_ticket_notes:
            if note and str(note).strip():
                # 備考らしく「※」を頭につけて改行
                text += f"\n※{str(note).strip()}"

    # 4. 出演者リスト
    # ★重要: アー写グリッドの並び順 (grid_order) を最優先で使用
    if "grid_order" in st.session_state and st.session_state.grid_order:
        artists = st.session_state.grid_order
    else:
        # グリッド順序がまだない場合はタイムテーブル順をバックアップとして使用
        artists = st.session_state.get("tt_artists_order", [])

    # 重複排除しつつ順序を維持（念のため）
    valid_artists = list(dict.fromkeys(artists))

    if valid_artists:
        text += f"\n\n■出演者（{len(valid_artists)}組予定）"
        for i, artist_name in enumerate(valid_artists, 1):
            c_num = get_circled_number(i)
            text += f"\n{c_num}{artist_name}"

    # 5. 自由記述 (注意事項など)
    if "proj_free_text" in st.session_state and st.session_state.proj_free_text:
        for f in st.session_state.proj_free_text:
            ft = f.get("title", "")
            fc = f.get("content", "")
            if ft or fc:
                text += f"\n\n■{ft}\n{fc}"
                
    return text

def render_overview_page():
    """イベント概要（基本情報・チケット・自由記述）の編集画面"""
    
    project_id = st.session_state.get("ws_active_project_id")
    
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

        # --- ★追加: チケット共通備考エリア ---
        st.markdown("---") # 区切り線
        st.markdown("**チケット共通備考**") # ラベル

        # データ初期化
        if "proj_ticket_notes" not in st.session_state:
            st.session_state.proj_ticket_notes = [] # 空リストで初期化
        
        # リストのクリーニング
        if not isinstance(st.session_state.proj_ticket_notes, list):
             st.session_state.proj_ticket_notes = []

        # 入力フォームループ
        # 削除時のインデックスズレを防ぐため、コピーやenumerateを使用
        current_notes = st.session_state.proj_ticket_notes
        for i in range(len(current_notes)):
            c_note_in, c_note_del = st.columns([8, 1])
            with c_note_in:
                # 入力値をsession_stateに直接反映
                current_notes[i] = st.text_input(
                    "共通備考",
                    value=current_notes[i],
                    key=f"t_common_note_{i}",
                    label_visibility="collapsed",
                    placeholder="例：別途1ドリンク代が必要です"
                )
            with c_note_del:
                if st.button("🗑️", key=f"del_t_common_{i}"):
                    st.session_state.proj_ticket_notes.pop(i)
                    st.rerun()

        # 追加ボタン
        if st.button("＋ チケット共通備考を追加"):
            st.session_state.proj_ticket_notes.append("")
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

    # --- 設定反映 & テキストプレビューエリア ---
    st.caption("変更内容は以下のボタンで保存してください。同時に告知用テキストを生成します。")
    
    # 初回表示時の自動生成
    if "overview_text_preview" not in st.session_state or st.session_state.overview_text_preview is None:
        st.session_state.overview_text_preview = generate_event_text()

    if st.button("🔄 設定反映 (保存＆テキスト生成)", type="primary", use_container_width=True, key="btn_overview_save"):
        if project_id:
            from database import get_db
            db = next(get_db())
            try:
                # ※注: 新しい「チケット共通備考」をDBに保存するには、save_current_project側の修正も必要ですが、
                # ここではまずUIとテキスト生成を優先しています。
                if save_current_project(db, project_id):
                    st.toast("イベント情報を保存しました！", icon="✅")
                    
                    # 1. 新しいテキストを生成
                    new_text = generate_event_text()
                    st.session_state.overview_text_preview = new_text
                    
                    # 2. ★重要: テキストエリアのウィジェットキー自体を直接上書きする
                    # これにより、st.text_areaの表示を強制的に更新します
                    st.session_state["txt_overview_preview_area"] = new_text
                    
                else:
                    st.error("保存に失敗しました")
            finally:
                db.close()
        else:
            st.error("プロジェクトが選択されていません")

    # テキストエリア
    # value引数だけでなく、session_stateのキー自体が更新されているので反映されます
    st.subheader("📝 告知用テキストプレビュー")
    st.text_area(
        "コピーしてSNSなどで使用できます", 
        value=st.session_state.overview_text_preview, 
        height=400, 
        key="txt_overview_preview_area"
    )
