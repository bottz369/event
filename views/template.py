import streamlit as st
import json
from datetime import datetime
from database import get_db, FlyerTemplate

def render_template_management_page():
    st.title("📂 テンプレート管理")
    st.caption("保存済みのフライヤーデザイン設定を確認・編集・削除できます。")

    db = next(get_db())
    
    # テンプレート一覧を取得 (新しい順)
    try:
        templates = db.query(FlyerTemplate).order_by(FlyerTemplate.created_at.desc()).all()
    except Exception as e:
        st.error(f"データ取得エラー: {e}")
        templates = []

    if not templates:
        st.info("保存されたテンプレートはありません。")
        st.markdown("※ フライヤー作成画面から「テンプレートとして保存」を行うとここに表示されます。")
        db.close()
        return

    st.markdown(f"**保存済み: {len(templates)} 件**")
    st.divider()

    for tmpl in templates:
        # カード型のデザイン
        with st.container(border=True):
            col_main, col_action = st.columns([3, 1])
            
            with col_main:
                c1, c2 = st.columns([2, 1])
                with c1:
                    # 名前編集用の入力欄
                    new_name = st.text_input(
                        "テンプレート名", 
                        value=tmpl.name, 
                        key=f"tmpl_name_{tmpl.id}",
                        label_visibility="collapsed"
                    )
                with c2:
                    st.caption(f"📅 作成日: {tmpl.created_at}")

                # JSONデータの中身を少しだけ表示（確認用）
                with st.expander("詳細データを確認"):
                    st.json(tmpl.data_json)

            with col_action:
                # 更新ボタン
                if st.button("名前を更新", key=f"upd_{tmpl.id}", use_container_width=True):
                    if new_name:
                        tmpl.name = new_name
                        db.commit()
                        st.toast(f"テンプレート名を「{new_name}」に更新しました！", icon="✅")
                        # 反映のためにリロード
                        import time
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error("名前を入力してください")

                st.write("") # スペース

                # 削除ボタン
                if st.button("🗑 削除", key=f"del_{tmpl.id}", type="primary", use_container_width=True):
                    db.delete(tmpl)
                    db.commit()
                    st.toast("テンプレートを削除しました", icon="🗑")
                    import time
                    time.sleep(1)
                    st.rerun()

    db.close()
