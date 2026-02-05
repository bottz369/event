import streamlit as st
import uuid
import os
import time
from PIL import Image
# ★修正: TimetableRow を追加インポート
from database import get_db, Artist, TimetableRow, upload_image_to_supabase, get_image_url

# 画像処理ロジックの読み込み
try:
    from logic_grid import (
        load_image_from_url, crop_smart, create_no_image_placeholder
    )
    HAS_LOGIC = True
except ImportError:
    HAS_LOGIC = False

# --- ★追加: 手動トリミング用の関数 (縮小・黒背景対応版) ---
def apply_manual_crop(img, scale=1.0, x_off=0, y_off=0, target_w=400, target_h=225):
    """
    画像を中心からトリミング・リサイズ・配置する関数
    scale: 1.0=基準サイズ, <1.0=縮小, >1.0=拡大
    x_off: 正=右へ移動, 負=左へ移動 (ピクセル)
    y_off: 正=下へ移動, 負=上へ移動 (ピクセル)
    余白は黒塗り(0,0,0)で埋めます。
    """
    if not img: 
        # インポート失敗時のフォールバック
        if 'create_no_image_placeholder' in globals():
            return create_no_image_placeholder(target_w, target_h)
        else:
            return Image.new("RGB", (target_w, target_h), (50, 50, 50))

    # 1. 基準サイズ(Cover)の計算
    # ターゲット領域を「隙間なく埋める最小サイズ」を計算
    img_ratio = img.width / img.height
    target_ratio = target_w / target_h

    if img_ratio > target_ratio:
        # 画像の方が横長 -> 高さを合わせる
        base_h = target_h
        base_w = int(base_h * img_ratio)
    else:
        # 画像の方が縦長 -> 幅を合わせる
        base_w = target_w
        base_h = int(base_w / img_ratio)

    # 2. スケール適用 (縮小も許可)
    # scale が小さすぎるとエラーになるのを防ぐ (最低1px)
    final_w = max(1, int(base_w * scale))
    final_h = max(1, int(base_h * scale))

    resized_img = img.resize((final_w, final_h), Image.LANCZOS)

    # 3. 黒背景のキャンバス作成
    canvas = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 255))

    # 4. 配置位置の計算
    # キャンバス中心 (target_w/2, target_h/2) に 画像中心 (final_w/2, final_h/2) を合わせる
    # そこにオフセット (x_off, y_off) を加算
    paste_x = int((target_w - final_w) / 2 + x_off)
    paste_y = int((target_h - final_h) / 2 + y_off)

    # 5. 貼り付け (透過情報も考慮)
    if resized_img.mode != "RGBA":
        resized_img = resized_img.convert("RGBA")
    
    # 画像を黒背景の上に重ねる
    canvas.paste(resized_img, (paste_x, paste_y), resized_img)

    return canvas.convert("RGB")


# 画像処理をキャッシュ化して高速化
@st.cache_data(show_spinner=False)
def get_processed_thumbnail(image_filename, scale=1.0, x=0, y=0):
    """
    画像を読み込み、アー写グリッドと同じ比率(16:9)で処理する。
    """
    target_w, target_h = 400, 225

    if not HAS_LOGIC:
        return Image.new("RGB", (target_w, target_h), (50, 50, 50))

    if image_filename:
        url = get_image_url(image_filename)
        if url:
            img = load_image_from_url(url)
            if img:
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
                            # 新規登録時は crop設定はデフォルト
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
                        
                        current_scale = getattr(a, 'crop_scale', 1.0) or 1.0
                        current_x = getattr(a, 'crop_x', 0) or 0
                        current_y = getattr(a, 'crop_y', 0) or 0

                        col_slide1, col_slide2 = st.columns(2)
                        with col_slide1:
                            new_scale = st.slider("ズーム/縮小", 0.1, 3.0, float(current_scale), 0.1, key=f"sc_{a.id}")
                        with col_slide2:
                            if st.button("位置リセット", key=f"rst_{a.id}"):
                                # 初期値に戻す
                                a.crop_scale = 1.0
                                a.crop_x = 0
                                a.crop_y = 0
                                db.commit()
                                
                                # ★修正: 値を代入せず、キーを削除してリセットする
                                target_keys = [f"sc_{a.id}", f"sx_{a.id}", f"sy_{a.id}"]
                                for k in target_keys:
                                    if k in st.session_state:
                                        del st.session_state[k]
                                
                                st.rerun()

                        # ★修正: step=1 にして 1ピクセル単位で動かせるように変更
                        new_x = st.slider("左右 (X)", -200, 200, int(current_x), 1, key=f"sx_{a.id}")
                        new_y = st.slider("上下 (Y)", -112, 112, int(current_y), 1, key=f"sy_{a.id}")

                        # プレビュー表示
                        preview_filename = a.image_filename
                        
                        preview_img = get_processed_thumbnail(preview_filename, new_scale, new_x, new_y)
                        st.image(preview_img, caption="プレビュー (余白は黒塗り)", use_container_width=True)

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
                                    
                                    # 調整値の保存
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
        
        st.divider()

        # ==================================================
        # ★追加: アーティスト統合 (名寄せ) 機能
        # ==================================================
        with st.expander("🔄 アーティストデータの統合 (名寄せ)"):
            st.info("""
            **重複して登録されたアーティストを統合します。**
            1. 「残す方」と「統合・削除する方」を選んでください。
            2. 過去のタイムテーブルデータで使用されている名前も自動的に「残す方」の名前に書き換わります。
            3. 「統合・削除する方」は削除されます。この操作は取り消せません。
            """)

            # 選択肢の作成 (ID付きで重複名も区別可能に)
            artist_options = {f"{ar.name} (ID: {ar.id})": ar.id for ar in artists}
            
            c_merge1, c_merge2 = st.columns(2)
            with c_merge1:
                winner_id = st.selectbox("✅ 残すアーティスト (正)", options=list(artist_options.values()), format_func=lambda x: [k for k, v in artist_options.items() if v == x][0], key="merge_winner")
            
            with c_merge2:
                # デフォルトでwinnerと違うものを選んでおく
                default_loser = list(artist_options.values())[1] if len(artist_options) > 1 else list(artist_options.values())[0]
                loser_id = st.selectbox("🗑️ 統合・削除するアーティスト (誤)", options=list(artist_options.values()), format_func=lambda x: [k for k, v in artist_options.items() if v == x][0], index=1 if len(artist_options) > 1 else 0, key="merge_loser")

            if st.button("⚠️ 統合を実行する", type="primary", use_container_width=True):
                if winner_id == loser_id:
                    st.error("同じアーティスト同士は統合できません。")
                else:
                    winner_obj = db.query(Artist).get(winner_id)
                    loser_obj = db.query(Artist).get(loser_id)
                    
                    if winner_obj and loser_obj:
                        try:
                            # 1. TimetableRowテーブルの名前を書き換え
                            rows_to_update = db.query(TimetableRow).filter(TimetableRow.artist_name == loser_obj.name).all()
                            count = len(rows_to_update)
                            
                            for r in rows_to_update:
                                r.artist_name = winner_obj.name
                            
                            # 2. 敗者を削除 (名前も変更して衝突回避)
                            loser_obj.is_deleted = True
                            loser_obj.name = f"{loser_obj.name}_merged_{int(time.time())}"
                            
                            db.commit()
                            st.toast(f"統合完了！ 過去データの {count} 箇所を修正しました。", icon="✅")
                            time.sleep(1)
                            st.rerun()
                        except Exception as e:
                            st.error(f"統合エラー: {e}")
                            db.rollback()
                    else:
                        st.error("データが見つかりません。")

    finally:
        db.close()
