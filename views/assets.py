import streamlit as st
import uuid
import os
from PIL import Image, ImageDraw, ImageFont # ★追加: フォントプレビュー生成用
from database import get_db, Asset, upload_image_to_supabase, get_image_url, IMAGE_DIR
from constants import FONT_DIR # ★追加: constantsからインポート

# ディレクトリの確実な作成
os.makedirs(IMAGE_DIR, exist_ok=True)
os.makedirs(FONT_DIR, exist_ok=True)

# --- ヘルパー関数: フォントプレビュー画像の生成 ---
def create_font_thumbnail(font_path, text="あいうABC", width=300, height=100):
    try:
        img = Image.new("RGB", (width, height), (240, 242, 246)) # 薄いグレー背景
        draw = ImageDraw.Draw(img)
        try:
            # 高さに合わせたフォントサイズ
            font_size = int(height * 0.6)
            font = ImageFont.truetype(font_path, font_size)
        except:
            return None # フォント読み込み失敗
        
        # 中央配置
        bbox = draw.textbbox((0, 0), text, font=font)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        x = (width - w) // 2
        y = (height - h) // 2 - bbox[1]
        
        draw.text((x, y), text, font=font, fill=(50, 50, 50))
        return img
    except:
        return None

def render_assets_page():
    st.title("🗂️ 素材・フォント管理")
    st.caption("フライヤー作成で使用する画像素材やフォントを登録します。")
    
    db = next(get_db())
    # ★拡張子を追加
    ALLOWED_EXTENSIONS = ['jpg', 'jpeg', 'png', 'webp', 'gif', 'ttf', 'otf']

    # --- 新規登録 ---
    with st.expander("➕ 新規素材を追加", expanded=False):
        with st.form("new_asset"):
            c1, c2 = st.columns(2)
            with c1:
                name = st.text_input("素材名 (例: メインロゴ, ポップ体フォント)")
                # ★選択肢にフォントを追加
                a_type = st.selectbox(
                    "種類", 
                    ["logo", "background", "font"], 
                    format_func=lambda x: {"logo":"ロゴ", "background":"背景", "font":"フォント"}.get(x, x)
                )
            with c2:
                f = st.file_uploader("ファイル", type=ALLOWED_EXTENSIONS)
            
            if st.form_submit_button("アーカイブに保存"):
                if name and f:
                    # 1. 拡張子チェックとファイル名決定
                    ext = os.path.splitext(f.name)[1].lower()
                    fname = f"asset_{uuid.uuid4()}{ext}"
                    
                    # 簡易バリデーション
                    if a_type == "font" and ext not in ['.ttf', '.otf']:
                        st.error("フォントには .ttf または .otf ファイルを選択してください")
                    elif a_type != "font" and ext in ['.ttf', '.otf']:
                        st.error("画像素材には画像ファイルを選択してください")
                    else:
                        # 2. 保存先の決定 (画像はIMAGE_DIR, フォントはFONT_DIR)
                        if a_type == "font":
                            save_dir = FONT_DIR
                        else:
                            save_dir = IMAGE_DIR
                        
                        local_path = os.path.join(save_dir, fname)

                        # 3. ローカル保存 (必須)
                        try:
                            f.seek(0)
                            with open(local_path, "wb") as local_f:
                                local_f.write(f.read())
                        except Exception as e:
                            st.error(f"ローカル保存エラー: {e}")
                            st.stop()

                        # 4. Supabaseへアップロード (バックアップ用)
                        # ※フォントもStorageに入れておくとPCが変わっても復元できます
                        try:
                            f.seek(0)
                            upload_image_to_supabase(f, fname)
                        except:
                            # データベース側のContent-Type制限でエラーになる場合がありますが
                            # ローカルにあれば動くのでここは警告のみにして続行させます
                            pass 

                        # 5. DB登録
                        new_asset = Asset(name=name, asset_type=a_type, image_filename=fname)
                        db.add(new_asset)
                        db.commit()
                        st.success(f"{name} を保存しました")
                        st.rerun()
                else:
                    st.error("素材名とファイルは必須です")

    st.divider()

    # --- 一覧表示 ---
    # ★タブを3つに増やす
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
                    with st.container(border=True):
                        u = get_image_url(asset.image_filename)
                        if u:
                            st.image(u, use_container_width=True)
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
                            # 縦横比固定で表示
                            st.markdown(f"""
                            <div style="width:100%; aspect-ratio:210/297; background:#333; overflow:hidden; border-radius:4px; margin-bottom:8px;">
                                <img src="{u}" style="width:100%; height:100%; object-fit:cover;">
                            </div>
                            """, unsafe_allow_html=True)
                        st.caption(asset.name)
                        if st.button("削除", key=f"del_bg_{asset.id}"):
                            asset.is_deleted = True
                            db.commit()
                            st.rerun()

    # 3. ★追加: フォント一覧
    with tabs[2]:
        assets = db.query(Asset).filter(Asset.asset_type == "font", Asset.is_deleted == False).all()
        if not assets:
            st.info("登録されているフォントはありません")
        else:
            cols = st.columns(3)
            for idx, asset in enumerate(assets):
                with cols[idx % 3]:
                    with st.container(border=True):
                        # フォントファイルのパス
                        font_path = os.path.join(FONT_DIR, asset.image_filename)
                        
                        # プレビュー生成
                        if os.path.exists(font_path):
                            thumb = create_font_thumbnail(font_path, text="Design 123") 
                            if thumb:
                                st.image(thumb, use_container_width=True)
                            else:
                                st.warning("プレビュー生成失敗")
                        else:
                            st.error("ファイル未検出")

                        st.caption(f"🅰️ {asset.name}")
                        st.caption(f"📄 {asset.image_filename}")
                        
                        if st.button("削除", key=f"del_font_{asset.id}"):
                            asset.is_deleted = True
                            db.commit()
                            st.rerun()
    
    db.close()
