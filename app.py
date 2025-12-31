import streamlit as st
import pandas as pd
from datetime import date
from sqlalchemy import text, inspect # ★inspectを追加
from database import init_db, engine, TimetableProject # ★TimetableProjectを追加

from constants import get_default_row_settings

# --- 各画面の読み込み ---
from views.workspace import render_workspace_page   # 統合ワークスペース
from views.projects import render_projects_page    # プロジェクト管理
from views.assets import render_assets_page        # 素材アーカイブ
from views.artists import render_artists_page      # アーティスト管理

# --- 設定 ---
st.set_page_config(page_title="イベント画像生成アプリ", layout="wide")
init_db()

# ==========================================
# 🔍 システム内部診断 (Step 3)
# ==========================================
st.markdown("### 🔍 システム内部診断")
st.caption("※確認が終わったらこのブロックは削除してOKです")
col1, col2 = st.columns(2)

# 1. Pythonの設計図に項目があるかチェック
with col1:
    if hasattr(TimetableProject, 'ticket_notes_json'):
        st.success("✅ Python設計図: OK (ticket_notes_json あり)")
    else:
        st.error("❌ Python設計図: NG (database.py が反映されていません)")

# 2. データベースの実物に項目があるかチェック
with col2:
    try:
        inspector = inspect(engine)
        columns = [c['name'] for c in inspector.get_columns('projects_v4')]
        if 'ticket_notes_json' in columns:
            st.success("✅ データベース実物: OK (カラムあり)")
        else:
            st.error("❌ データベース実物: NG (カラムが追加されていません)")
    except Exception as e:
        st.error(f"DB接続エラー: {e}")

st.divider()

# ==========================================
# ★重要: セッションステートの初期化
# ==========================================
if "tt_artists_order" not in st.session_state: st.session_state.tt_artists_order = []
if "tt_artist_settings" not in st.session_state: st.session_state.tt_artist_settings = {}
if "tt_row_settings" not in st.session_state: st.session_state.tt_row_settings = []
if "tt_has_pre_goods" not in st.session_state: st.session_state.tt_has_pre_goods = False
if "tt_pre_goods_settings" not in st.session_state: st.session_state.tt_pre_goods_settings = get_default_row_settings()
if "tt_post_goods_settings" not in st.session_state: st.session_state.tt_post_goods_settings = get_default_row_settings()
if "tt_editor_key" not in st.session_state: st.session_state.tt_editor_key = 0
if "binding_df" not in st.session_state: st.session_state.binding_df = pd.DataFrame()
if "rebuild_table_flag" not in st.session_state: st.session_state.rebuild_table_flag = True
if "tt_title" not in st.session_state: st.session_state.tt_title = ""
if "tt_event_date" not in st.session_state: st.session_state.tt_event_date = date.today()
if "tt_venue" not in st.session_state: st.session_state.tt_venue = ""
if "tt_open_time" not in st.session_state: st.session_state.tt_open_time = "10:00"
if "tt_start_time" not in st.session_state: st.session_state.tt_start_time = "10:30"
if "tt_goods_offset" not in st.session_state: st.session_state.tt_goods_offset = 5
if "request_calc" not in st.session_state: st.session_state.request_calc = False
if "tt_current_proj_id" not in st.session_state: st.session_state.tt_current_proj_id = None

if "tt_unsaved_changes" not in st.session_state: st.session_state.tt_unsaved_changes = False

# デフォルトメニュー設定
if "last_menu" not in st.session_state: st.session_state.last_menu = "ワークスペース"

# ==========================================
# サイドバー & メニュー
# ==========================================
st.sidebar.title("メニュー")

menu_items = ["ワークスペース", "プロジェクト管理", "素材アーカイブ", "アーティスト管理"]
menu_selection = st.sidebar.radio("機能を選択", menu_items, key="sb_menu")

# ==========================================
# ページ遷移
# ==========================================
st.session_state.last_menu = menu_selection
current_page = menu_selection

# ==========================================
# ルーティング
# ==========================================
if current_page == "ワークスペース":
    render_workspace_page()

elif current_page == "プロジェクト管理":
    render_projects_page()

elif current_page == "素材アーカイブ":
    render_assets_page()

elif current_page == "アーティスト管理":
    render_artists_page()
