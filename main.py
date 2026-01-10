import streamlit as st
import pandas as pd
from datetime import date
from database import init_db
from constants import get_default_row_settings

# --- 各ページ（ビュー）のインポート ---
# views/workspace.py (メイン作業場: 概要/TT/グリッド/フライヤー)
from views.workspace import render_workspace_page
# views/projects.py (管理: 保存データ一覧/PDF出力/削除)
from views.projects import render_projects_page
# views/artists.py (マスタ: アーティスト登録/編集)
from views.artists import render_artists_page
# views/assets.py (マスタ: 素材・フォント管理)
from views.assets import render_assets_page
# views/manual.py (マニュアル: 使い方)
from views.manual import render_manual_page
# views/template.py (テンプレート管理)
from views.template import render_template_management_page

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
if "last_menu" not in st.session_state: st.session_state.last_menu = "プロジェクト・ワークスペース"

# ==========================================
# サイドバー & メニュー
# ==========================================
st.sidebar.title("メニュー")

# 機能構成の整理
# Workspaceに「タイムテーブル」「グリッド」「フライヤー」が含まれるため統合
menu_options = [
    "プロジェクト・ワークスペース", # 新規作成・編集・画像生成 (Main)
    "プロジェクト管理",            # 一覧・PDF出力・削除 (Projects)
    "アーティスト管理",            # マスタ (Artists)
    "素材・フォント管理",          # マスタ (Assets)
    "テンプレート管理",            # マスタ (Templates)
    "使い方マニュアル"             # Manual
]

menu_selection = st.sidebar.radio("機能を選択", menu_options, key="sb_menu")

def revert_nav():
    st.session_state.sb_menu = st.session_state.last_menu

current_page = menu_selection

# 保存確認（ワークスペース使用時、未保存があれば警告）
# ※ 簡易実装として、ワークスペースから他へ移動するときのみチェック
is_leaving_workspace = (st.session_state.last_menu == "プロジェクト・ワークスペース" and current_page != "プロジェクト・ワークスペース")

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
    # キャンセルされた場合は移動しないように見せるため、描画対象を直前のものに戻す
    current_page = st.session_state.last_menu
else:
    st.session_state.last_menu = menu_selection
    current_page = menu_selection

# ==========================================
# ルーティング
# ==========================================
if current_page == "プロジェクト・ワークスペース":
    # 統合された編集画面 (概要/TT/グリッド/フライヤー)
    render_workspace_page()

elif current_page == "プロジェクト管理":
    # データ一覧、PDF出力、削除
    render_projects_page()

elif current_page == "アーティスト管理":
    # 出演者登録、画像トリミング
    render_artists_page()

elif current_page == "素材・フォント管理":
    # ロゴ、背景、フォント登録
    render_assets_page()

elif current_page == "テンプレート管理":
    # フライヤーテンプレートの管理
    render_template_management_page()

elif current_page == "使い方マニュアル":
    # マニュアル表示
    render_manual_page()
