import streamlit as st
import pandas as pd
from database import get_db, TimetableProject, Asset
from utils import create_event_summary_pdf, create_project_assets_zip, create_business_pdf, calculate_timetable_flow
import json
import io

def render_projects_page():
    st.title("🗂️ プロジェクト管理")
    st.caption("作成済みプロジェクトのデータ出力や削除を行います。編集は「ワークスペース」で行ってください。")
    
    db = next(get_db())
    projects = db.query(TimetableProject).all()
    projects.sort(key=lambda x: x.event_date or "0000-00-00", reverse=True)

    if not projects:
        st.info("プロジェクトがありません。")
        db.close()
        return

    for proj in projects:
        with st.container(border=True):
            c_info, c_action = st.columns([3, 2])
            
            with c_info:
                st.subheader(f"{proj.event_date} : {proj.title}")
                st.text(f"📍 {proj.venue_name}")
                if proj.venue_url: st.caption(f"🔗 {proj.venue_url}")

            with c_action:
                st.markdown("##### 📥 ダウンロード / 操作")
                
                # 1. イベント概要PDF
                pdf_summary = create_event_summary_pdf(proj)
                st.download_button(
                    "📄 イベント概要PDF",
                    pdf_summary,
                    f"summary_{proj.id}.pdf",
                    "application/pdf",
                    key=f"dl_sum_{proj.id}",
                    use_container_width=True
                )

                # 2. タイムテーブルPDF (データがある場合のみ)
                if proj.data_json:
                    try:
                        # データフレームを復元して計算
                        df_src = pd.DataFrame(json.loads(proj.data_json))
                        df_calc = calculate_timetable_flow(df_src, proj.open_time, proj.start_time)
                        pdf_tt = create_business_pdf(df_calc, proj.title, proj.event_date, proj.venue_name)
                        st.download_button(
                            "⏱️ タイムテーブルPDF",
                            pdf_tt,
                            f"timetable_{proj.id}.pdf",
                            "application/pdf",
                            key=f"dl_tt_{proj.id}",
                            use_container_width=True
                        )
                    except:
                        st.warning("タイムテーブルデータが不完全です")

                # 3. 全素材ZIP (簡易版)
                # zip_data = create_project_assets_zip(proj, db, Asset)
                # st.download_button("📦 素材＆データZIP", zip_data, f"assets_{proj.id}.zip", "application/zip", key=f"dl_zip_{proj.id}", use_container_width=True)
                
                # 4. 削除ボタン (確認付き)
                with st.expander("🗑️ プロジェクトを削除"):
                    st.warning("この操作は取り消せません！")
                    if st.button("本当に削除する", key=f"del_{proj.id}", type="primary"):
                        db.delete(proj)
                        db.commit()
                        st.success("削除しました")
                        st.rerun()

    db.close()
