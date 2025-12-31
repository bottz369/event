import streamlit as st
from datetime import datetime
import traceback # エラー詳細表示用

# データベース関連
from database import get_db
from logic_project import save_current_project, load_project_data

# ==========================================
# 🔧 デバッグ用ヘルパー
# ==========================================
def debug_log(message, data=None):
    """画面上のサイドバーまたはメインエリアにデバッグ情報を出す"""
    msg = f"[{datetime.now().strftime('%H:%M:%S')}] {message}"
    print(msg) # コンソールにも出す
    with st.sidebar:
        st.caption(msg)
        if data is not None:
            st.code(str(data), language="json")

# ==========================================
# ヘルパー関数
# ==========================================
def get_day_of_week_jp(dt):
    """日付から日本語の曜日を取得 (月)〜(日)"""
    if not dt: return ""
    w_list = ['(月)', '(火)', '(水)', '(木)', '(金)', '(土)', '(日)']
    return w_list[dt.weekday()]

def get_circled_number(n):
    """数値を丸数字の文字に変換"""
    if 1 <= n <= 20:
        return chr(0x2460 + (n - 1))
    elif 21 <= n <= 35:
        return chr(0x3251 + (n - 21))
    elif 36 <= n <= 50:
        return chr(0x32B1 + (n - 36))
    else:
        return f"({n})"

def generate_event_text():
    """イベント概要を生成"""
    try:
        # 1. 基本情報の取得
        title = st.session_state.get("proj_title", "")
        date_val = st.session_state.get("proj_date")
        venue = st.session_state.get("proj_venue", "")
        url = st.session_state.get("proj_url", "")
        
        # 日付フォーマット
        date_str = ""
        if date_val:
            date_str = date_val.strftime("%Y年%m月%d日") + get_day_of_week_jp(date_val)
        
        open_t = st.session_state.get("tt_open_time", "10:00")
        start_t = st.session_state.get("tt_start_time", "10:30")
        
        # 2. テキスト構築
        text = f"【公演概要】\n{date_str}\n『{title}』\n\n■会場: {venue}"
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
                line = f"- {name}: {price}"
                if note:
                    line += f" ({note})"
                if name or price:
                    text += "\n" + line
        else:
            text += "\n(情報なし)"

        # チケット共通備考
        if "proj_ticket_notes" in st.session_state and st.session_state.proj_ticket_notes:
            for note in st.session_state.proj_ticket_notes:
                if note and str(note).strip():
                    text += f"\n※{str(note).strip()}"

        # 4. 出演者リスト
        artists = st.session_state.get("grid_order") or st.session_state.get("tt_artists_order", [])
        valid_artists = list(dict.fromkeys(artists)) # 重複排除

        if valid_artists:
            text += f"\n\n■出演者（{len(valid_artists)}組予定）"
            for i, artist_name in enumerate(valid_artists, 1):
                c_num = get_circled_number(i)
                text += f"\n{c_num}{artist_name}"

        # 5. 自由記述
        if "proj_free_text" in st.session_state and st.session_state.proj_free_text:
            for f in st.session_state.proj_free_text:
                ft = f.get("title", "")
                fc = f.get("content", "")
                if ft or fc:
                    text += f"\n\n■{ft}\n{fc}"
                    
        return text
    except Exception as e:
        return f"テキスト生成エラー: {e}"

# ==========================================
# メイン描画関数
# ==========================================
def render_overview_page():
    """イベント概要の編集画面 (Debug Mode)"""
    
    st.title("🛠️ イベント概要編集 (Debug Mode)")
    
    # サイドバーに現在のデータ状態を表示（デバッグ用）
    st.sidebar.markdown("---")
    st.sidebar.warning("📊 データ監視中")
    if st.sidebar.checkbox("生データを表示", value=False):
        st.sidebar.write("Project ID:", st.session_state.get("ws_active_project_id"))
        st.sidebar.write("Notes List:", st.session_state.get("proj_ticket_notes"))
        st.sidebar.write("Tickets:", st.session_state.get("proj_tickets"))

    project_id = st.session_state.get("ws_active_project_id")
    
    # --- データ読み込み ---
    if project_id:
        # 必要なキーがない場合のみロード
        if "proj_title" not in st.session_state:
            debug_log("DBからデータをロードします...")
            db = next(get_db())
            try:
                load_project_data(db, project_id)
                debug_log("ロード完了")
            except Exception as e:
                st.error(f"ロードエラー: {e}")
            finally:
                db.close()
    
    # --- 基本情報 UI ---
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
    
    # --- チケット情報 UI ---
    with c_tic:
        st.subheader("チケット情報")
        
        # 初期化
        if "proj_tickets" not in st.session_state:
            st.session_state.proj_tickets = [{"name":"", "price":"", "note":""}]
        
        # リストの中身を安全にする
        safe_tickets = []
        for t in st.session_state.proj_tickets:
            if isinstance(t, dict): safe_tickets.append(t)
            else: safe_tickets.append({"name": str(t), "price":"", "note":""})
        st.session_state.proj_tickets = safe_tickets

        # 描画ループ
        for i, ticket in enumerate(st.session_state.proj_tickets):
            with st.container(border=True):
                cols = st.columns([3, 2, 4, 1])
                # ★修正: ここではリストを直接書き換えず、keyを使って管理させるのが安全だが
                # 既存ロジックを生かしつつ、入力値をリストに反映
                with cols[0]:
                    ticket["name"] = st.text_input("チケット名", value=ticket.get("name",""), key=f"t_name_{i}", label_visibility="collapsed", placeholder="Sチケット")
                with cols[1]:
                    ticket["price"] = st.text_input("金額", value=ticket.get("price",""), key=f"t_price_{i}", label_visibility="collapsed", placeholder="¥3,000")
                with cols[2]:
                    ticket["note"] = st.text_input("備考", value=ticket.get("note",""), key=f"t_note_{i}", label_visibility="collapsed", placeholder="D代別")
                with cols[3]:
                    if i > 0:
                        if st.button("🗑️", key=f"del_t_{i}"):
                            st.session_state.proj_tickets.pop(i)
                            st.rerun()
        
        if st.button("＋ 新しいチケットを追加"):
            st.session_state.proj_tickets.append({"name":"", "price":"", "note":""})
            st.rerun()

        # --- チケット共通備考エリア (ここが問題の箇所の可能性大) ---
        st.markdown("---") 
        st.markdown("**チケット共通備考**")

        if "proj_ticket_notes" not in st.session_state:
            st.session_state.proj_ticket_notes = []
        if not isinstance(st.session_state.proj_ticket_notes, list):
            st.session_state.proj_ticket_notes = []

        current_notes = st.session_state.proj_ticket_notes
        
        # ループで入力欄表示
        for i in range(len(current_notes)):
            c_note_in, c_note_del = st.columns([8, 1])
            with c_note_in:
                # ★デバッグ修正ポイント: valueの設定と受け取り方を明確にする
                val = st.text_input(
                    "共通備考",
                    value=current_notes[i],
                    key=f"t_common_note_{i}", # ウィジェットのキー
                    label_visibility="collapsed",
                    placeholder="例：別途1ドリンク代が必要です"
                )
                # リストを即時更新 (念のため)
                current_notes[i] = val
                
            with c_note_del:
                if st.button("🗑️", key=f"del_t_common_{i}"):
                    st.session_state.proj_ticket_notes.pop(i)
                    st.rerun()

        if st.button("＋ チケット共通備考を追加"):
            st.session_state.proj_ticket_notes.append("")
            st.rerun()

    # --- 自由記述 UI ---
    with c_free:
        st.subheader("自由記述 (注意事項など)")
        if "proj_free_text" not in st.session_state:
            st.session_state.proj_free_text = [{"title":"", "content":""}]
        
        safe_free = []
        for f in st.session_state.proj_free_text:
            if isinstance(f, dict): safe_free.append(f)
            else: safe_free.append({"title": str(f), "content":""})
        st.session_state.proj_free_text = safe_free

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

    # --- 設定反映 & デバッグ保存処理 ---
    st.caption("変更内容は以下のボタンで保存してください。")

    # ★ここが最大の修正ポイント：保存ボタン処理
    if st.button("🔄 設定反映 (保存＆テキスト生成)", type="primary", use_container_width=True, key="btn_overview_save"):
        
        debug_log("🚀 保存ボタンが押されました。処理を開始します。")

        # 【重要】強制同期: ウィジェット(入力欄)の値を、確実にデータリストに書き戻す
        # これをやらないと、入力途中のデータが反映されないことがあります
        debug_log("--- 強制同期処理開始 ---")
        
        # 1. チケット共通備考の同期
        if "proj_ticket_notes" in st.session_state:
            for i in range(len(st.session_state.proj_ticket_notes)):
                widget_key = f"t_common_note_{i}"
                if widget_key in st.session_state:
                    # ウィジェットにある最新の値をリストに格納
                    st.session_state.proj_ticket_notes[i] = st.session_state[widget_key]
        
        # 2. チケット情報の同期
        if "proj_tickets" in st.session_state:
            for i, ticket in enumerate(st.session_state.proj_tickets):
                if f"t_name_{i}" in st.session_state:
                    ticket["name"] = st.session_state[f"t_name_{i}"]
                if f"t_price_{i}" in st.session_state:
                    ticket["price"] = st.session_state[f"t_price_{i}"]
                if f"t_note_{i}" in st.session_state:
                    ticket["note"] = st.session_state[f"t_note_{i}"]

        # 3. 自由記述の同期
        if "proj_free_text" in st.session_state:
            for i, item in enumerate(st.session_state.proj_free_text):
                if f"f_title_{i}" in st.session_state:
                    item["title"] = st.session_state[f"f_title_{i}"]
                if f"f_content_{i}" in st.session_state:
                    item["content"] = st.session_state[f"f_content_{i}"]
        
        debug_log("--- 強制同期完了 ---")
        debug_log("保存するTicket Notes:", st.session_state.proj_ticket_notes)

        # 保存処理実行
        if project_id:
            db = next(get_db())
            try:
                if save_current_project(db, project_id):
                    st.toast("イベント情報を保存しました！", icon="✅")
                    # テキスト生成
                    new_text = generate_event_text()
                    st.session_state.txt_overview_preview_area = new_text
                    debug_log("✅ 保存成功")
                else:
                    st.error("保存処理が False を返しました。")
                    debug_log("❌ 保存失敗 (save_current_project returned False)")
            except Exception as e:
                st.error(f"保存中にエラーが発生: {e}")
                st.code(traceback.format_exc()) # エラー詳細を表示
            finally:
                db.close()
        else:
            st.error("プロジェクトIDが不明です")

    # テキストプレビュー表示
    if "txt_overview_preview_area" not in st.session_state:
        st.session_state.txt_overview_preview_area = generate_event_text()

    st.subheader("📝 告知用テキストプレビュー")
    st.text_area(
        "コピーしてSNSなどで使用できます", 
        height=400, 
        key="txt_overview_preview_area"
    )
