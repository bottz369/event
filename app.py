import streamlit as st
import pandas as pd
from datetime import date
from sqlalchemy import text, inspect
from database import init_db, engine, TimetableProject

from constants import get_default_row_settings

# --- 各画面の読み込み ---
from views.workspace import render_workspace_page   # 統合ワークスペース
from views.projects import render_projects_page    # プロジェクト管理
from views.assets import render_assets_page        # 素材アーカイブ（アセット管理）
from views.artists import render_artists_page      # アーティスト管理
from views.template import render_template_management_page # テンプレート管理
from views.manual import render_manual_page        # ユーザーマニュアル
# ★追加: 開発者ドキュメント
from views.developer_docs import render_developer_docs_page

# --- 設定 ---
st.set_page_config(page_title="イベント画像生成アプリ", layout="wide")
init_db()

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

# チケット関連の安全策
if "tt_tickets" not in st.session_state: st.session_state.tt_tickets = []
if "tt_ticket_notes" not in st.session_state: st.session_state.tt_ticket_notes = []

if "tt_unsaved_changes" not in st.session_state: st.session_state.tt_unsaved_changes = False

# デフォルトメニュー設定
if "last_menu" not in st.session_state: st.session_state.last_menu = "ワークスペース"

# ==========================================
# サイドバー & メニュー
# ==========================================
st.sidebar.title("メニュー")

# メニュー構成
# ★追加: 「開発者向けドキュメント」を追加
menu_items = [
    "ワークスペース", 
    "プロジェクト管理", 
    "テンプレート管理", 
    "アーティスト管理", 
    "アセット管理", 
    "使い方マニュアル",
    "開発者向けドキュメント"
]
menu_selection = st.sidebar.radio("機能を選択", menu_items, key="sb_menu")

# ==========================================
# ページ遷移制御 (保存確認ロジック)
# ==========================================
def revert_nav():
    """ナビゲーションを元に戻すコールバック"""
    st.session_state.sb_menu = st.session_state.last_menu

current_page = menu_selection

# ワークスペースから他へ移動する際、未保存の変更があれば警告を出す
is_leaving_workspace = (st.session_state.last_menu == "ワークスペース" and current_page != "ワークスペース")

if st.session_state.tt_unsaved_changes and is_leaving_workspace:
    st.warning("⚠️ ワークスペースに未保存の変更があります！")
    col_nav1, col_nav2 = st.columns(2)
    with col_nav1:
        if st.button("変更を破棄して移動する"):
            st.session_state.tt_unsaved_changes = False
            st.session_state.last_menu = menu_selection
            st.rerun()
    with col_nav2:
        if st.button("キャンセル（元の画面に戻る）", on_click=revert_nav):
            st.rerun()
    
    # ユーザーが選択するまでは画面遷移させない
    current_page = st.session_state.last_menu
else:
    # 移動承認、または警告不要な場合
    st.session_state.last_menu = menu_selection
    current_page = menu_selection

# ==========================================
# ルーティング
# ==========================================
if current_page == "ワークスペース":
    render_workspace_page()

elif current_page == "プロジェクト管理":
    render_projects_page()

elif current_page == "テンプレート管理":
    render_template_management_page()

elif current_page == "アーティスト管理":
    render_artists_page()

elif current_page == "アセット管理":
    render_assets_page()

elif current_page == "使い方マニュアル":
    render_manual_page()

elif current_page == "開発者向けドキュメント":
    render_developer_docs_page()
