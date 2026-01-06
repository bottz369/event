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

# --- ★追加: 手動トリミング用の関数 ---
def apply_manual_crop(img, scale=1.0, x_off=0, y_off=0, target_w=400, target_h=225):
    """
    画像を中心からトリミングし、ズームと位置調整を適用する関数
    scale: 1.0=基準サイズ, >1.0=拡大
    x_off: 正=右へ移動, 負=左へ移動 (ピクセル)
    y_off: 正=下へ移動, 負=上へ移動 (ピクセル)
    """
    if not img: return create_no_image_placeholder(target_w, target_h)

    # 1. まずターゲットのアスペクト比(16:9)に合わせて「隙間なく埋まるサイズ」にリサイズ（Cover）
    img_ratio = img.width / img.height
    target_ratio = target_w / target_h

    if img_ratio > target_ratio:
        # 画像の方が横長 -> 高さを合わせる
        new_h = target_h
        new_w = int(new_h * img_ratio)
    else:
        # 画像の方が縦長 -> 幅を合わせる
        new_w = target_w
        new_h = int(new_w / img_ratio)

    resized_img = img.resize((new_w, new_h), Image.LANCZOS)

    # 2. ズーム適用
    if scale > 1.0:
        z_w = int(new_w * scale)
        z_h = int(new_h * scale)
        resized_img = resized_img.resize((z_w, z_h), Image.LANCZOS)
    
    # 3. 切り抜き位置の計算 (中心基準 + オフセット)
    center_x = resized_img.width // 2
    center_y = resized_img.height // 2

    # UIのスライダー操作に合わせて計算 (スライダー右=画像右移動 なら cropは左へ)
    crop_x = center_x - (target_w // 2) - x_off
    crop_y = center_y - (target_h // 2) - y_off

    # 4. 切り抜き実行
    return resized_img.crop((crop_x, crop_y, crop_x + target_w, crop_y + target_h))


# 画像処理をキャッシュ化して高速化
# ★変更: 引数に scale, x, y を追加して、変更があったら再生成されるようにする
@st.cache_data(show_spinner=False)
def get_processed_thumbnail(image_filename, scale=1.0, x=0, y=0):
    """
    画像を読み込み、アー写グリッドと同じ比率(16:9)で処理する。
    scale等がデフォルト値(1.0, 0, 0)の場合は「自動(crop_smart)」を使い、
    値が入っている場合は「手動(apply_manual_crop)」を使う。
    """
    target_w, target_h = 400, 225

    if not HAS_LOGIC:
        return Image.new("RGB", (target_w, target_h), (50, 50, 50))

    if image_filename:
        url = get_image_url(image_filename)
        if url:
            img = load_image_from_url(url)
            if img:
                # ★ここが分岐ポイント
                # 調整値がデフォルトから変更されているか判定
                is_manual = (scale != 1.0) or (x != 0) or (y != 0)

                if is_manual:
                    # 手動調整モード
                    return apply_manual_crop(img, scale, x, y, target_w, target_h)
                else:
                    # 自動モード (既存のロジック)
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
                            # 新規登録時は crop設定はデフォルト(None or 初期値)
                            db.add(Artist(name=n, image_filename=fname))
                            st.success("登録しました")
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
                        st.caption(f"編集中: {a.name}")
                        en = st.text_input("名前", a.name, key=f"en_{a.id}")
                        ef = st.file_uploader("画像変更", type=ALLOWED_EXTENSIONS, key=f"ef_{a.id}")
                        
                        # --- ★追加: 位置調整スライダー ---
                        st.markdown("##### 🖼️ 画像位置調整")
                        
                        # DBにカラムがない場合のエラー回避用 (getattr使用)
                        current_scale = getattr(a, 'crop_scale', 1.0) or 1.0
                        current_x = getattr(a, 'crop_x', 0) or 0
                        current_y = getattr(a, 'crop_y', 0) or 0

                        col_slide1, col_slide2 = st.columns(2)
                        with col_slide1:
                            new_scale = st.slider("ズーム", 1.0, 3.0, float(current_scale), 0.1, key=f"sc_{a.id}")
                        with col_slide2:
                            if st.button("位置リセット", key=f"rst_{a.id}"):
                                # 一時的にセッションなどで管理する手もありますが、
                                # シンプルに再読み込みしてDBの初期値(0)に戻す運用とするか、
                                # ここではスライダーを手動で戻してもらうのが一番安全です。
                                # ボタンで即座にDB書き換えはリスクがあるため、今回は「手動で戻す」運用を推奨しますが、
                                # UX向上のためリロードをかけます（ただし未保存の変更は消えます）
                                st.rerun()

                        new_x = st.slider("左右 (X)", -200, 200, int(current_x), 5, key=f"sx_{a.id}")
                        new_y = st.slider("上下 (Y)", -112, 112, int(current_y), 5, key=f"sy_{a.id}")

                        # プレビュー表示 (スライダーを動かすとここが変わる)
                        # DB保存前の filename or アップロードされたファイルの処理
                        # ※ファイル変更直後のプレビューは複雑になるため、既存ファイルに対する調整プレビューを表示
                        preview_filename = a.image_filename
                        
                        preview_img = get_processed_thumbnail(preview_filename, new_scale, new_x, new_y)
                        st.image(preview_img, caption="プレビュー", use_container_width=True)

                        st.divider()

                        c1, c2 = st.columns(2)
                        with c1:
                            if st.button("保存", key=f"sv_{a.id}", type="primary"):
                                if en:
                                    fn = a.image_filename
                                    if ef:
                                        ext = os.path.splitext(ef.name)[1].lower()
                                        fn = f"{uuid.uuid4()}{ext}"
                                        upload_image_to_supabase(ef, fn)
                                    
                                    a.name = en
                                    a.image_filename = fn
                                    
                                    # ★追加: 調整値の保存
                                    # モデルに属性がある場合のみセット
                                    if hasattr(a, 'crop_scale'): a.crop_scale = new_scale
                                    if hasattr(a, 'crop_x'): a.crop_x = new_x
                                    if hasattr(a, 'crop_y'): a.crop_y = new_y

                                    db.commit()
                                    st.session_state.editing_artist_id = None; st.rerun()
                        with c2:
                            if st.button("中止", key=f"cn_{a.id}"):
                                st.session_state.editing_artist_id = None; st.rerun()
                    
                    # --- 通常表示モード ---
                    else:
                        # ★追加: DBの保存値を読み込んで表示
                        s = getattr(a, 'crop_scale', 1.0) or 1.0
                        cx = getattr(a, 'crop_x', 0) or 0
                        cy = getattr(a, 'crop_y', 0) or 0
                        
                        thumb = get_processed_thumbnail(a.image_filename, s, cx, cy)
                        st.image(thumb, use_container_width=True)
                        
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
