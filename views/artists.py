import streamlit as st
import uuid
import os
import time
from database import get_db, Artist, upload_image_to_supabase, get_image_url

def render_artists_page():
    st.title("🎤 アーティスト管理")
    db = next(get_db())
    if "editing_artist_id" not in st.session_state: st.session_state.editing_artist_id = None

    try:
        with st.expander("➕ 新規登録", expanded=False):
            with st.form("new_artist"):
                n = st.text_input("名前")
                f = st.file_uploader("画像", type=['jpg','png'])
                if st.form_submit_button("登録"):
                    if n:
                        fname = None
                        if f:
                            ext = os.path.splitext(f.name)[1]
                            fname = f"{uuid.uuid4()}{ext}"
                            upload_image_to_supabase(f, fname)
                        
                        exists = db.query(Artist).filter(Artist.name==n).first()
                        if exists:
                            if exists.is_deleted: exists.is_deleted=False; exists.image_filename=fname; st.success("復元しました")
                            else: st.error("登録済み")
                        else:
                            db.add(Artist(name=n, image_filename=fname)); st.success("登録しました")
                        db.commit(); st.rerun()
                    else: st.error("名前必須")

        st.divider()
        artists = db.query(Artist).filter(Artist.is_deleted==False).order_by(Artist.name).all()
        # ... (以下、元の表示コード) ...
    finally:
        db.close()
