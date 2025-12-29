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
    
    # 1. ロゴ一覧 (従来通り画像全体を表示)
    with tabs[0]:
        assets = db.query(Asset).filter(Asset.asset_type == "logo", Asset.is_deleted == False).all()
        if not assets:
            st.info("登録されているロゴはありません")
        else:
            cols = st.columns(4)
            for idx, asset in enumerate(assets):
                with cols[idx % 4]:
                    with st.container(border=True):
                        u = get_image_url(asset.image_filename)
                        if u:
                            # ロゴは形が様々なので、アスペクト比固定の枠に入れつつ、全体が見えるように (contain)
                            st.markdown(f"""
                            <div style="width:100%; aspect-ratio: 1/1; background-color: #f0f2f6; display:flex; align-items:center; justify-content:center; border-radius:4px; overflow:hidden; margin-bottom:8px;">
                                <img src="{u}" style="max-width:100%; max-height:100%; object-fit:contain;">
                            </div>
                            """, unsafe_allow_html=True)
                        
                        st.caption(asset.name)
                        if st.button("削除", key=f"del_logo_{asset.id}"):
                            asset.is_deleted = True
                            db.commit()
                            st.rerun()

    # 2. 背景一覧 (★ここを変更: A4縦比率で隙間なく埋める)
    with tabs[1]:
        assets = db.query(Asset).filter(Asset.asset_type == "background", Asset.is_deleted == False).all()
        if not assets:
            st.info("登録されている背景素材はありません")
        else:
            cols = st.columns(4)
            for idx, asset in enumerate(assets):
                with cols[idx % 4]:
                    with st.container(border=True):
                        u = get_image_url(asset.image_filename)
                        if u:
                            # A4比率 (210:297) で枠を作り、画像を拡大して埋める (cover)
                            st.markdown(f"""
                            <div style="
                                width: 100%;
                                aspect-ratio: 210 / 297;
                                background-color: #333;
                                border-radius: 4px;
                                overflow: hidden;
                                margin-bottom: 8px;
                                position: relative;
                            ">
                                <img src="{u}" style="
                                    width: 100%;
                                    height: 100%;
                                    object-fit: cover;
                                    object-position: center;
                                ">
                            </div>
                            """, unsafe_allow_html=True)
                        
                        st.caption(asset.name)
                        if st.button("削除", key=f"del_bg_{asset.id}"):
                            asset.is_deleted = True
                            db.commit()
                            st.rerun()
    
    db.close()
