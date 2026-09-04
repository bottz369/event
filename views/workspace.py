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
from models.flyer_keys import FLYER_KEY_REGISTRY

from views.overview import render_overview_page
from views.timetable import render_timetable_page
from views.grid import render_grid_page
from views.flyer import render_flyer_editor


# =========================================================
# タブ遅延描画のための session_state ピン留め
# =========================================================
# Streamlit は「そのラン中に描画されなかったウィジェット」の session_state を
# ランの終わりに破棄する。タブを遅延描画(選択中のタブだけ render)に変えると、
# 非表示タブのウィジェット値がタブ切替のたびに消えてしまう。
#
#   実測: A タブで入力 → B タブへ切替 → A へ戻す と入力値が '' に戻る。
#
# 明示保存型(DB に入るのは保存ボタンだけ)なので、未保存の編集が黙って
# 消えるのは許容できない。そこでランの先頭で保持対象キーを自分自身に
# 再代入して「生きている」状態を維持する(ウィジェット実体化より前に行うので
# 通常の「既定値をあらかじめ session_state に置く」パターンと同じ扱いになる)。
#
# 対象は SESSION_PROJECT_KEYS + flyer レジストリ + プロジェクトデータ系の
# 動的キー(チケット / フリーテキスト行など)。ボタン・ダウンロード・
# file_uploader のキーは session_state 経由で値を設定できず例外になるため
# 明示的に除外する。
_PIN_ALLOW_PREFIXES = (
    "tt_", "grid_", "flyer_", "proj_", "overview_", "txt_overview_",
    "t_name_", "t_price_", "t_note_", "t_common_note_",
    "f_title_", "f_content_",
)
# ボタン / download_button / file_uploader のキー(値の設定が禁止されている)
_PIN_DENY_PREFIXES = (
    "btn_", "del_", "dl_", "rename_btn_", "rst_", "up_", "upd_",
    "tt_pending_rm_",
    # st.data_editor のウィジェット state。延命すると編集差分(edited_rows)の
    # 状態機械が壊れる(罠33 の回帰テストが RED になることを実測)。
    # TT の SSOT は draft_rows(素のキーなので破棄対象外)で、data_editor は
    # セル編集ごとに rerun して「先取り確定」ブロックが draft_rows へ反映する
    # ため、延命しなくても確定済みの編集は失われない。
    "tt_editor_",
)
_PIN_DENY_EXACT = frozenset({"csv_upload_key", "save_font_conf", "save_pos"})


def _pinned_keys(existing_keys) -> set:
    """このランで再代入して延命するキー集合を返す(純関数・テスト可能)。"""
    keys = set(session_manager.SESSION_PROJECT_KEYS)
    keys |= {f"flyer_{e.short_key}" for e in FLYER_KEY_REGISTRY}
    for k in existing_keys:
        if isinstance(k, str) and k.startswith(_PIN_ALLOW_PREFIXES):
            keys.add(k)
    return {
        k
        for k in keys
        if k not in _PIN_DENY_EXACT and not k.startswith(_PIN_DENY_PREFIXES)
    }


def _pin_session_keys() -> None:
    """非表示タブのウィジェット値が破棄されないよう自身に再代入する。"""
    for k in _pinned_keys(list(st.session_state.keys())):
        if k in st.session_state:
            try:
                st.session_state[k] = st.session_state[k]
            except Exception:
                # 設定不可なウィジェット種別(想定外の追加)は延命対象から外す。
                # 落とすほどではないので握って続行する。
                pass


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

    # タブ遅延描画で非表示タブの未保存編集が消えないよう延命する
    # (ウィジェット実体化より前に行う必要があるためタブ描画の手前で呼ぶ)
    _pin_session_keys()

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
