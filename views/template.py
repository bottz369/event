import streamlit as st
from services import template_service

def render_template_management_page():
    st.title("📂 テンプレート管理")
    st.caption("保存済みのフライヤーデザイン設定を確認・編集・削除できます。")

    # テンプレート一覧を取得 (新しい順)
    try:
        templates = template_service.list_templates()
    except Exception as e:
        st.error(f"データ取得エラー: {e}")
        templates = []

    if not templates:
        st.info("保存されたテンプレートはありません。")
        st.markdown("※ フライヤー作成画面から「テンプレートとして保存」を行うとここに表示されます。")
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
                if st.button("名前を更新", key=f"upd_{tmpl.id}", width='stretch'):
                    if new_name:
                        if template_service.rename_template(tmpl.id, new_name):
                            st.toast(f"テンプレート名を「{new_name}」に更新しました！", icon="✅")
                            # 反映のためにリロード
                            import time
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error("更新に失敗しました")
                    else:
                        st.error("名前を入力してください")

                st.write("") # スペース

                # 削除ボタン
                if st.button("🗑 削除", key=f"del_{tmpl.id}", type="primary", width='stretch'):
                    if template_service.delete_template(tmpl.id):
                        st.toast("テンプレートを削除しました", icon="🗑")
                        import time
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error("削除に失敗しました")
