import streamlit as st
import pandas as pd
from datetime import date
from sqlalchemy import text, inspect
from database import init_db, engine, TimetableProject

from utils.logger import get_logger  # ロガー有効化(except: pass を撲滅する基盤)

# --- 各画面の読み込み ---
from views.workspace import render_workspace_page   # 統合ワークスペース
from views.projects import render_projects_page    # プロジェクト管理
from views.assets import render_assets_page        # 素材アーカイブ（アセット管理）
from views.artists import render_artists_page      # アーティスト管理
from views.template import render_template_management_page # テンプレート管理
from views.manual import render_manual_page        # ユーザーマニュアル

# --- 設定 ---
st.set_page_config(page_title="イベント画像生成アプリ", layout="wide")

logger = get_logger("app")

# Phase 3 Fix1: init_db() をプロセス 1 回のみに削減。
# Base.metadata.create_all は冪等な CREATE TABLE IF NOT EXISTS だが、
# 毎 rerun ごとに全テーブル分の DDL ラウンドトリップが発生して累積で重い。
# @st.cache_resource で初回のみ実行、以降はキャッシュヒットで ~0ms に。
@st.cache_resource
def _ensure_db_initialized():
    init_db()
    return True

_ensure_db_initialized()

logger.info("App started")

# ==========================================
# ★重要: セッションステートの初期化
# ==========================================
if "tt_editor_key" not in st.session_state: st.session_state.tt_editor_key = 0
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
menu_items = [
    "ワークスペース",
    "プロジェクト管理",
    "テンプレート管理",
    "アーティスト管理",
    "アセット管理",
    "使い方マニュアル"
]
menu_selection = st.sidebar.radio("機能を選択", menu_items, key="sb_menu")

# ==========================================
# ページ遷移制御
# ==========================================
# 警告ロジックを削除し、選択されたメニューへ即座に移動するように修正
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
