import streamlit as st
import uuid
import os
from database import get_db, Asset, upload_image_to_supabase, get_image_url

def render_assets_page():
    st.title("🗂️ 素材アーカイブ管理")
    st.caption("フライヤー作成で使用するロゴや背景画像を事前に登録します。")
    
    db = next(get_db())
    ALLOWED_EXTENSIONS = ['jpg', 'jpeg', 'png', 'webp', 'gif']

    # --- 新規登録 ---
    with st.expander("➕ 新規素材を追加", expanded=False):
        with st.form("new_asset"):
            c1, c2 = st.columns(2)
            with c1:
                name = st.text_input("素材名 (例: イベントロゴver1)")
                a_type = st.selectbox("種類", ["logo", "background"], format_func=lambda x: "ロゴ" if x=="logo" else "背景")
            with c2:
                f = st.file_uploader("画像ファイル", type=ALLOWED_EXTENSIONS)
            
            if st.form_submit_button("アーカイブに保存"):
                if name and f:
                    ext = os.path.splitext(f.name)[1].lower()
                    fname = f"asset_{uuid.uuid4()}{ext}"
                    upload_image_to_supabase(f, fname)
                    
                    new_asset = Asset(name=name, asset_type=a_type, image_filename=fname)
                    db.add(new_asset)
                    db.commit()
                    st.success("保存しました")
                    st.rerun()
                else:
                    st.error("素材名と画像は必須です")

    st.divider()

    # --- 一覧表示 ---
    tabs = st.tabs(["ロゴ一覧", "背景一覧"])
    
    for i, a_type in enumerate(["logo", "background"]):
        with tabs[i]:
            assets = db.query(Asset).filter(Asset.asset_type == a_type, Asset.is_deleted == False).all()
            if not assets:
                st.info("登録されている素材はありません")
            else:
                cols = st.columns(4)
                for idx, asset in enumerate(assets):
                    with cols[idx % 4]:
                        with st.container(border=True):
                            u = get_image_url(asset.image_filename)
                            if u: st.image(u, use_container_width=True)
                            st.caption(asset.name)
                            if st.button("削除", key=f"del_ast_{asset.id}"):
                                asset.is_deleted = True
                                db.commit()
                                st.rerun()
    db.close()
