import streamlit as st
import uuid
import os
import time
from PIL import Image
from database import get_db, Artist, upload_image_to_supabase, get_image_url

# 画像処理ロジックの読み込み
try:
    from logic_grid import (
        load_image_from_url, crop_smart, create_no_image_placeholder
    )
    HAS_LOGIC = True
except ImportError:
    HAS_LOGIC = False

# 画像処理をキャッシュ化して高速化
@st.cache_data(show_spinner=False)
def get_processed_thumbnail(image_filename):
    """
    画像を読み込み、アー写グリッドと同じ比率(16:9)で顔認識クロップを行う。
    画像がない場合はNo Image画像を生成して返す。
    """
    target_w, target_h = 400, 225

    if not HAS_LOGIC:
        return Image.new("RGB", (target_w, target_h), (50, 50, 50))

    if image_filename:
        url = get_image_url(image_filename)
        if url:
            img = load_image_from_url(url)
            if img:
                cropped = crop_smart(img)
                return cropped.resize((target_w, target_h), Image.LANCZOS)
    
    return create_no_image_placeholder(target_w, target_h)

def render_artists_page():
    st.title("🎤 アーティスト管理")
    db = next(get_db())
    if "editing_artist_id" not in st.session_state: st.session_state.editing_artist_id = None

    ALLOWED_EXTENSIONS = ['jpg', 'jpeg', 'png', 'webp', 'gif', 'bmp', 'tiff', 'tif']

    try:
        with st.expander("➕ 新規登録", expanded=False):
            with st.form("new_artist"):
                n = st.text_input("名前")
                f = st.file_uploader("画像", type=ALLOWED_EXTENSIONS)
                if st.form_submit_button("登録"):
                    if n:
                        fname = None
                        if f:
                            ext = os.path.splitext(f.name)[1].lower()
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
        if not artists: st.info("なし")
        
        cols = st.columns(3)
        for i, a in enumerate(artists):
            with cols[i%3]:
                with st.container(border=True):
                    # --- 編集モード ---
                    if st.session_state.editing_artist_id == a.id:
                        en = st.text_input("名前", a.name, key=f"en_{a.id}")
                        ef = st.file_uploader("画像変更", type=ALLOWED_EXTENSIONS, key=f"ef_{a.id}")
                        c1, c2 = st.columns(2)
                        with c1:
                            if st.button("保存", key=f"sv_{a.id}"):
                                if en:
                                    fn = a.image_filename
                                    if ef:
                                        ext = os.path.splitext(ef.name)[1].lower()
                                        fn = f"{uuid.uuid4()}{ext}"
                                        upload_image_to_supabase(ef, fn)
                                    a.name = en; a.image_filename = fn; db.commit()
                                    st.session_state.editing_artist_id = None; st.rerun()
                        with c2:
                            if st.button("中止", key=f"cn_{a.id}"):
                                st.session_state.editing_artist_id = None; st.rerun()
                    
                    # --- 通常表示モード ---
                    else:
                        thumb = get_processed_thumbnail(a.image_filename)
                        st.image(thumb, use_container_width=True)
                        
                        # ★ここを変更: CSSを使って改行禁止＆省略表示(...)にする
                        # title属性を入れているので、マウスオーバーすると全文字出ます
                        st.markdown(f"""
                        <div style="
                            white-space: nowrap; 
                            overflow: hidden; 
                            text-overflow: ellipsis; 
                            font-size: 1.2rem; 
                            font-weight: bold;
                            margin-bottom: 10px;
                        " title="{a.name}">
                            {a.name}
                        </div>
                        """, unsafe_allow_html=True)

                        c1, c2 = st.columns(2)
                        with c1:
                            if st.button("編集", key=f"ed_{a.id}"):
                                st.session_state.editing_artist_id = a.id; st.rerun()
                        with c2:
                            if st.button("削除", key=f"dl_{a.id}"):
                                a.is_deleted = True; a.name = f"{a.name}_del_{int(time.time())}"
                                db.commit(); st.rerun()
    finally:
        db.close()
