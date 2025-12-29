import streamlit as st
import pandas as pd
from datetime import date
from database import init_db
from constants import get_default_row_settings

# --- 各画面の読み込み ---
from views.workspace import render_workspace_page  # ★新機能: 統合ワークスペース
from views.projects import render_projects_page    # プロジェクト管理
from views.assets import render_assets_page        # ★新機能: 素材アーカイブ
from views.artists import render_artists_page      # アーティスト管理

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
if "tt_unsaved_changes" not in st.session_state: st.session_state.tt_unsaved_changes = False

# デフォルトメニュー設定
if "last_menu" not in st.session_state: st.session_state.last_menu = "ワークスペース"

# ==========================================
# サイドバー & メニュー
# ==========================================
st.sidebar.title("メニュー")

# ★メニュー構成を刷新
# 「タイムテーブル作成」「アー写グリッド作成」などは「ワークスペース」内に統合されました
menu_items = ["ワークスペース", "プロジェクト管理", "素材アーカイブ", "アーティスト管理"]
menu_selection = st.sidebar.radio("機能を選択", menu_items, key="sb_menu")

def revert_nav():
    st.session_state.sb_menu = st.session_state.last_menu

current_page = menu_selection

# 保存確認（タイムテーブル作成等の未保存チェック）
if st.session_state.tt_unsaved_changes and menu_selection != st.session_state.last_menu:
    st.warning("⚠️ 作業中の内容に未保存の変更があります！")
    col_nav1, col_nav2 = st.columns(2)
    with col_nav1:
        if st.button("変更を破棄して移動する"):
            st.session_state.tt_unsaved_changes = False
            st.session_state.last_menu = menu_selection
            st.rerun()
    with col_nav2:
        if st.button("キャンセル（元の画面に戻る）", on_click=revert_nav):
            st.rerun()
    current_page = st.session_state.last_menu
else:
    st.session_state.last_menu = menu_selection
    current_page = menu_selection

# ==========================================
# ルーティング
# ==========================================
if current_page == "ワークスペース":
    # ★ここがメインの作業場所になります
    render_workspace_page()

elif current_page == "プロジェクト管理":
    # プロジェクトの新規作成・削除など
    render_projects_page()

elif current_page == "素材アーカイブ":
    # ロゴや背景画像の管理
    render_assets_page()

elif current_page == "アーティスト管理":
    # アーティスト情報の登録・編集
    render_artists_page()
