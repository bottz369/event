import streamlit as st
import uuid
import os
# ★ IMAGE_DIR を追加インポート
from database import get_db, Asset, upload_image_to_supabase, get_image_url, IMAGE_DIR

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
                    # 1. ファイル名の決定
                    ext = os.path.splitext(f.name)[1].lower()
                    fname = f"asset_{uuid.uuid4()}{ext}"
                    
                    # 2. Supabase へアップロード (既存機能)
                    # ファイルポインタをリセットしてから渡す
                    f.seek(0)
                    upload_image_to_supabase(f, fname)
                    
                    # 3. ★追加: ローカルの IMAGE_DIR にも保存する (フライヤー生成用)
                    # これにより、画像生成時に「ファイルが見つからない」エラーを防ぎます
                    local_path = os.path.join(IMAGE_DIR, fname)
                    try:
                        f.seek(0) # 再度リセット
                        with open(local_path, "wb") as local_f:
                            local_f.write(f.read())
                    except Exception as e:
                        st.error(f"ローカル保存エラー: {e}")

                    # 4. DB登録
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
    
    # 1. ロゴ一覧
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

    # 2. 背景一覧
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
