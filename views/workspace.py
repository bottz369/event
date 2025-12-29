import streamlit as st
from database import get_db, TimetableProject

# 各機能の読み込み
# ※ timetable.py と grid.py は後で少し修正する必要がありますが、
#    現状のままでも動作させるために工夫して呼び出します。
from views.timetable import render_timetable_page 
from views.grid import render_grid_page
from views.flyer import render_flyer_editor

def render_workspace_page():
    st.title("🚀 プロジェクト・ワークスペース")
    db = next(get_db())
    
    # 1. プロジェクト選択エリア
    projects = db.query(TimetableProject).all()
    projects.sort(key=lambda x: x.event_date or "0000-00-00", reverse=True)
    
    proj_map = {f"{p.event_date} {p.title}": p.id for p in projects}
    
    # セッションで選択中のプロジェクトを保持
    if "ws_active_project_id" not in st.session_state:
        st.session_state.ws_active_project_id = None

    selected_label = st.selectbox(
        "作業するプロジェクトを選択", 
        ["(選択してください)"] + list(proj_map.keys()),
        index=0 if not st.session_state.ws_active_project_id else list(proj_map.values()).index(st.session_state.ws_active_project_id) + 1
    )

    if selected_label == "(選択してください)":
        st.info("まずはプロジェクトを選択してください。")
        db.close()
        return

    # 選択確定
    project_id = proj_map[selected_label]
    st.session_state.ws_active_project_id = project_id
    
    # プロジェクト情報の取得
    proj = db.query(TimetableProject).filter(TimetableProject.id == project_id).first()
    
    st.divider()
    st.markdown(f"### 📂 {proj.title} <small>({proj.event_date} @ {proj.venue_name})</small>", unsafe_allow_html=True)

    # 2. タブで機能切り替え
    tab_tt, tab_grid, tab_flyer = st.tabs(["⏱️ タイムテーブル", "🖼️ アー写グリッド", "📑 フライヤーセット"])

    with tab_tt:
        # 既存の timetable.py は「選択ボックス」を持っていますが、
        # ここでは強制的にIDをセットしてあげることで連携させます。
        st.session_state.tt_current_proj_id = project_id
        # 既存関数の呼び出し（本来は引数を受け取る形にリファクタリングするのがベストですが、今回は既存を流用）
        render_timetable_page()
    
    with tab_grid:
        st.session_state.current_grid_proj_id = project_id
        render_grid_page()

    with tab_flyer:
        # ここは新しく作ったコンポーネントを呼ぶ
        render_flyer_editor(project_id)

    db.close()
