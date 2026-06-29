"""
ワークスペース画面(統合編集画面)。

リファクタ後の方針:
- プロジェクトのロード/セーブは services.project_service が一手に担う。
- このファイルは「プロジェクト選択 UI」と「タブのルーティング」だけを行う。
- 旧 load_project_to_session() と prepare_active_project_fonts(), ensure_generated_contents() の
  巨大ブロックは削除した。フォント準備と画像自動生成はフェーズ2以降で
  font_service / image_service へ移管予定。

このファイルから直接 DB を叩くことは原則しない(プロジェクト一覧の取得のみ例外)。
"""
from __future__ import annotations

from datetime import date

import streamlit as st

from services import session_manager, project_service

from views.overview import render_overview_page
from views.timetable import render_timetable_page
from views.grid import render_grid_page
from views.flyer import render_flyer_editor


# =========================================================
# 画像自動生成は明示トリガー方式に変更
# =========================================================
# 旧コードではワークスペースを開くたびに TT/グリッド/フライヤーの 3 つを
# 自動生成していたため「遅い」原因になっていた。
# フェーズ3で削除予定。当面は何もしないスタブを置き、各タブ側で
# 「プレビュー生成」ボタンを使ってもらう運用にする。
def _autogenerate_previews_if_needed() -> None:
    """旧 ensure_generated_contents の置き換え。当面は何もしない。"""
    pass


# =========================================================
# メイン描画
# =========================================================
def render_workspace_page():
    st.title("🚀 プロジェクト・ワークスペース")

    # プロジェクト選択 UI
    _render_project_selector()

    # 未選択時は何もしない
    active_id = session_manager.get_active_project_id()
    if active_id is None:
        return

    # アクティブプロジェクトがセッションにロードされていることを保証
    if not session_manager.ensure_project_loaded(active_id):
        st.error("プロジェクトの読み込みに失敗しました。再度選択してください。")
        session_manager.clear_project_session()
        session_manager.set_active_project_id(None)
        return

    draft = session_manager.get_draft_project()
    if draft is None:
        st.error("プロジェクトデータの取得に失敗しました。")
        return

    # 未保存警告
    if session_manager.has_unsaved_changes():
        st.warning("⚠️ このプロジェクトには未保存の変更があります。各タブの「設定反映」で保存してください。")

    # ヘッダー(タイトル / 日付 / 会場 + 複製ボタン)
    _render_project_header(draft)

    # 旧 ensure_generated_contents の置き換え(現状は no-op)
    _autogenerate_previews_if_needed()

    # 各タブ
    tab_overview, tab_tt, tab_grid, tab_flyer = st.tabs(
        ["📝 イベント概要", "⏱️ タイムテーブル", "🖼️ アー写グリッド", "📑 フライヤーセット"]
    )

    with tab_overview:
        render_overview_page()

    with tab_tt:
        render_timetable_page()

    with tab_grid:
        # 旧コードで grid 側がこのキーを参照しているため一応セット(後で消す)
        st.session_state.current_grid_proj_id = active_id
        render_grid_page()

    with tab_flyer:
        render_flyer_editor(active_id)


# =========================================================
# UI 部品
# =========================================================
def _render_project_selector() -> None:
    """
    プロジェクト選択ボックスを描画。
    選択が変わったら session_manager 経由でロードし直す。
    """
    project_list = project_service.list_projects_for_selector()
    label_to_id = {label: pid for pid, label in project_list}

    options = ["(選択してください)", "➕ 新規プロジェクト作成"] + list(label_to_id.keys())

    # 現在の active から初期インデックスを決める
    current_idx = 0
    active_id = session_manager.get_active_project_id()
    if active_id is not None:
        for i, label in enumerate(options):
            if label_to_id.get(label) == active_id:
                current_idx = i
                break

    selected_label = st.selectbox(
        "作業するプロジェクトを選択",
        options,
        index=current_idx,
        key="ws_project_selector_label",
    )

    if selected_label == "➕ 新規プロジェクト作成":
        _render_new_project_form()
        return

    if selected_label == "(選択してください)":
        # 何も選択していない状態
        return

    new_id = label_to_id.get(selected_label)
    if new_id is None:
        return

    # 選択が変わったら強制再ロード
    if new_id != session_manager.get_active_project_id():
        if session_manager.reload_project(new_id):
            st.rerun()
        else:
            st.error("プロジェクトの読み込みに失敗しました。")


def _render_new_project_form() -> None:
    st.divider()
    st.subheader("✨ 新しいプロジェクトを作成")
    with st.form("ws_new_project_form"):
        c1, c2 = st.columns(2)
        with c1:
            p_date = st.date_input("開催日", value=date.today())
            p_title = st.text_input("イベント名")
        with c2:
            p_venue = st.text_input("会場名")
            p_url = st.text_input("会場URL")

        submitted = st.form_submit_button("作成して開始", type="primary")
        if submitted:
            if not (p_title and p_venue):
                st.error("イベント名と会場名は必須です")
                return

            new_id = project_service.create_new_project(
                title=p_title,
                event_date=p_date,
                venue_name=p_venue,
                venue_url=p_url,
            )
            if new_id:
                st.success("プロジェクトを作成しました！")
                st.rerun()
            else:
                st.error("作成に失敗しました")


def _render_project_header(draft) -> None:
    st.markdown("---")
    col_dummy, col_act = st.columns([4, 1])
    with col_act:
        if st.button("📄 複製して編集", width='stretch', key="btn_proj_duplicate"):
            new_id = project_service.duplicate_active_project()
            if new_id:
                st.toast("プロジェクトを複製しました！", icon="✨")
                st.rerun()
            else:
                st.error("複製に失敗しました")

    title = draft.title or "(無題)"
    date_str = str(draft.event_date) if draft.event_date else "----"
    venue = draft.venue_name or ""
    st.markdown(
        f"### 📂 {title} <small>({date_str} @ {venue})</small>",
        unsafe_allow_html=True,
    )
