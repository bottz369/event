import streamlit as st
import uuid
import os
from PIL import Image, ImageDraw, ImageFont
# ★ SystemFontConfig, FavoriteFont を追加インポート
from database import get_db, Asset, FavoriteFont, SystemFontConfig, upload_image_to_supabase, get_image_url, IMAGE_DIR
from constants import FONT_DIR

# ディレクトリの確実な作成
os.makedirs(IMAGE_DIR, exist_ok=True)
os.makedirs(FONT_DIR, exist_ok=True)

# --- ヘルパー関数: フォントプレビュー画像の生成 ---
def create_font_thumbnail(font_path, text="あいうABC", width=300, height=100):
    try:
        img = Image.new("RGB", (width, height), (240, 242, 246)) # 薄いグレー背景
        draw = ImageDraw.Draw(img)
        try:
            font_size = int(height * 0.6)
            font = ImageFont.truetype(font_path, font_size)
        except:
            return None
        
        bbox = draw.textbbox((0, 0), text, font=font)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        x = (width - w) // 2
        y = (height - h) // 2 - bbox[1]
        
        draw.text((x, y), text, font=font, fill=(50, 50, 50))
        return img
    except:
        return None

# --- ヘルパー関数: 素材カードの描画 (共通化) ---
def render_asset_card(asset, db, is_font=False):
    with st.container(border=True):
        # 1. プレビュー表示
        if is_font:
            font_path = os.path.join(FONT_DIR, asset.image_filename)
            if os.path.exists(font_path):
                thumb = create_font_thumbnail(font_path, text="Design 123")
                if thumb: st.image(thumb, use_container_width=True)
                else: st.warning("プレビュー生成失敗")
            else:
                st.error("ファイル未検出")
        else:
            u = get_image_url(asset.image_filename)
            if u:
                st.markdown(f"""
                <div style="width:100%; height:150px; background:#f0f2f6; display:flex; align-items:center; justify-content:center; overflow:hidden; border-radius:4px; margin-bottom:8px;">
                    <img src="{u}" style="max-width:100%; max-height:100%; object-fit:contain;">
                </div>
                """, unsafe_allow_html=True)

        # 2. ファイル名などの情報
        st.markdown(f"**{asset.name}**")
        st.caption(f"📄 {asset.image_filename}")

        # 3. 素材名の変更
        with st.expander("✏️ 名称変更"):
            new_name = st.text_input("新しい名前", value=asset.name, key=f"rename_input_{asset.id}")
            if st.button("更新", key=f"rename_btn_{asset.id}"):
                if new_name:
                    asset.name = new_name
                    db.commit()
                    st.success("更新しました")
                    st.rerun()

        # 4. 削除ボタン
        if st.button("🗑️ 削除", key=f"del_{asset.id}", type="secondary", use_container_width=True):
            asset.is_deleted = True
            db.commit()
            st.rerun()

def render_assets_page():
    st.title("🗂️ 素材・フォント管理")
    st.caption("フライヤー作成で使用する画像素材やフォントを登録します。")
    
    db = next(get_db())
    ALLOWED_EXTENSIONS = ['jpg', 'jpeg', 'png', 'webp', 'gif', 'ttf', 'otf']

    # --- 新規登録 ---
    with st.expander("➕ 新規素材を追加", expanded=False):
        with st.form("new_asset"):
            c1, c2 = st.columns(2)
            with c1:
                name = st.text_input("素材名 (未入力の場合はファイル名になります)")
                a_type = st.selectbox(
                    "種類", 
                    ["logo", "background", "font"], 
                    format_func=lambda x: {"logo":"ロゴ", "background":"背景", "font":"フォント"}.get(x, x)
                )
            with c2:
                f = st.file_uploader("ファイル", type=ALLOWED_EXTENSIONS)
            
            if st.form_submit_button("アーカイブに保存"):
                if f:
                    if not name:
                        name = os.path.splitext(f.name)[0]

                    # 1. ファイル名の決定
                    if a_type == "font":
                        fname = f.name
                    else:
                        ext = os.path.splitext(f.name)[1].lower()
                        fname = f"asset_{uuid.uuid4()}{ext}"
                    
                    # 簡易バリデーション
                    ext_check = os.path.splitext(f.name)[1].lower()
                    if a_type == "font" and ext_check not in ['.ttf', '.otf']:
                        st.error("フォントには .ttf または .otf ファイルを選択してください")
                    elif a_type != "font" and ext_check in ['.ttf', '.otf']:
                        st.error("画像素材には画像ファイルを選択してください")
                    else:
                        # 2. 保存先の決定
                        if a_type == "font":
                            save_dir = FONT_DIR
                        else:
                            save_dir = IMAGE_DIR
                        
                        local_path = os.path.join(save_dir, fname)

                        # 3. ローカル保存
                        try:
                            f.seek(0)
                            with open(local_path, "wb") as local_f:
                                local_f.write(f.read())
                        except Exception as e:
                            st.error(f"ローカル保存エラー: {e}")
                            st.stop()

                        # 4. Supabaseへアップロード
                        try:
                            f.seek(0)
                            upload_image_to_supabase(f, fname)
                        except:
                            pass 

                        # 5. DB登録
                        new_asset = Asset(name=name, asset_type=a_type, image_filename=fname)
                        db.add(new_asset)
                        db.commit()
                        st.success(f"保存しました: {fname}")
                        st.rerun()
                else:
                    st.error("ファイルを選択してください")

    st.divider()

    # --- 一覧表示 ---
    tabs = st.tabs(["ロゴ一覧", "背景一覧", "フォント一覧"])
    
    # 1. ロゴ一覧
    with tabs[0]:
        assets = db.query(Asset).filter(Asset.asset_type == "logo", Asset.is_deleted == False).all()
        if not assets:
            st.info("登録されているロゴはありません")
        else:
            cols = st.columns(4)
            for idx, asset in enumerate(assets):
                with cols[idx % 4]:
                    render_asset_card(asset, db, is_font=False)

    # 2. 背景一覧
    with tabs[1]:
        assets = db.query(Asset).filter(Asset.asset_type == "background", Asset.is_deleted == False).all()
        if not assets:
            st.info("登録されている背景素材はありません")
        else:
            cols = st.columns(4)
            for idx, asset in enumerate(assets):
                with cols[idx % 4]:
                    render_asset_card(asset, db, is_font=False)

    # 3. フォント一覧 (★ここを機能強化)
    with tabs[2]:
        # --- 自動同期処理 ---
        if os.path.exists(FONT_DIR):
            db_filenames = [a.image_filename for a in db.query(Asset).filter(Asset.asset_type == "font", Asset.is_deleted == False).all()]
            local_fonts = [f for f in os.listdir(FONT_DIR) if f.lower().endswith((".ttf", ".otf"))]
            
            new_found = False
            for fname in local_fonts:
                if fname not in db_filenames:
                    new_asset = Asset(name=fname, asset_type="font", image_filename=fname)
                    db.add(new_asset)
                    new_found = True
            
            if new_found:
                db.commit()
                st.rerun()

        # --- ★標準・お気に入りフォント設定エリア ---
        st.markdown("### ⚙️ フォント設定")
        st.caption("見本画像の「ファイル名」表示や、システム全体で標準的に使用するフォントを設定します。")
        
        # 全フォント取得
        font_assets = db.query(Asset).filter(Asset.asset_type == "font", Asset.is_deleted == False).all()
        # ファイル名 -> 表示名のマップ
        font_options_map = {f.image_filename: f.name for f in font_assets}
        font_filenames = list(font_options_map.keys())
        
        if font_filenames:
            # DBから現状の設定を取得
            current_sys = db.query(SystemFontConfig).first()
            current_sys_val = current_sys.filename if current_sys and current_sys.filename in font_filenames else (font_filenames[0] if font_filenames else None)
            
            current_favs = db.query(FavoriteFont).all()
            current_fav_vals = [f.filename for f in current_favs if f.filename in font_filenames]

            c_sys, c_fav = st.columns([1, 2])
            
            # 標準フォント設定 (シングルセレクト)
            with c_sys:
                st.caption("標準フォント (システムデフォルト)")
                new_sys_val = st.selectbox(
                    "標準フォント", font_filenames, 
                    index=font_filenames.index(current_sys_val) if current_sys_val in font_filenames else 0,
                    format_func=lambda x: font_options_map.get(x, x),
                    key="sys_font_select", label_visibility="collapsed"
                )
            
            # お気に入りフォント設定 (マルチセレクト)
            with c_fav:
                st.caption("お気に入りフォント (リスト上位に表示)")
                new_fav_vals = st.multiselect(
                    "お気に入り", font_filenames,
                    default=current_fav_vals,
                    format_func=lambda x: font_options_map.get(x, x),
                    key="fav_font_select", label_visibility="collapsed"
                )

            # 保存ボタン
            if st.button("設定を保存", type="primary", key="save_font_conf"):
                # 1. 標準フォント保存
                db.query(SystemFontConfig).delete()
                db.add(SystemFontConfig(filename=new_sys_val))
                
                # 2. お気に入り保存 (全削除して追加)
                db.query(FavoriteFont).delete()
                for f_name in new_fav_vals:
                    db.add(FavoriteFont(filename=f_name))
                
                db.commit()
                st.success("フォント設定を更新しました！")
                st.rerun()
        else:
            st.warning("フォントが登録されていません")

        st.divider()

        # --- フォント一覧カード表示 ---
        if not font_assets:
            st.info("登録されているフォントはありません")
        else:
            cols = st.columns(3)
            for idx, asset in enumerate(font_assets):
                with cols[idx % 3]:
                    render_asset_card(asset, db, is_font=True)
    
    db.close()
