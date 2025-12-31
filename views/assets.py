import streamlit as st
import uuid
import os
import requests
from PIL import Image, ImageDraw, ImageFont
from database import get_db, Asset, FavoriteFont, SystemFontConfig, upload_image_to_supabase, get_image_url, IMAGE_DIR
from constants import FONT_DIR
# utilsからのインポートは不要になったため削除、または残していても問題ありません
# from utils import create_font_specimen_img 

# ディレクトリの確実な作成
os.makedirs(IMAGE_DIR, exist_ok=True)
os.makedirs(FONT_DIR, exist_ok=True)

# --- ヘルパー関数: フォント同期 (Supabase -> ローカル) ---
def sync_fonts_from_storage(db):
    """
    DBにはあるがローカル(FONT_DIR)にないフォントを
    SupabaseのURLからダウンロードして復元する
    """
    fonts = db.query(Asset).filter(Asset.asset_type == "font", Asset.is_deleted == False).all()
    restored_count = 0
    
    for font in fonts:
        local_path = os.path.join(FONT_DIR, font.image_filename)
        if not os.path.exists(local_path):
            # ファイルがない場合、URLから取得を試みる
            url = get_image_url(font.image_filename)
            if url:
                try:
                    response = requests.get(url, timeout=10)
                    if response.status_code == 200:
                        with open(local_path, "wb") as f:
                            f.write(response.content)
                        restored_count += 1
                except Exception as e:
                    print(f"Font download failed: {font.image_filename} / {e}")
    
    if restored_count > 0:
        st.toast(f"{restored_count}個のフォントをクラウドから復元しました")

# --- ヘルパー関数: フォントプレビュー画像の生成 ---
def create_font_thumbnail(font_path, text="Sample 123", width=300, height=150):
    try:
        # 背景色を白っぽく、少しリッチに
        img = Image.new("RGB", (width, height), (250, 250, 252)) 
        draw = ImageDraw.Draw(img)
        try:
            # フォントサイズを高さに合わせて調整
            font_size = int(height * 0.5)
            font = ImageFont.truetype(font_path, font_size)
        except:
            return None
        
        # 中央揃え計算
        bbox = draw.textbbox((0, 0), text, font=font)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        x = (width - w) // 2
        y = (height - h) // 2 - bbox[1]
        
        draw.text((x, y), text, font=font, fill=(60, 60, 70))
        
        # 枠線を少し描く（オプション）
        draw.rectangle([(0,0), (width-1, height-1)], outline="#e0e0e0", width=1)
        
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
                thumb = create_font_thumbnail(font_path, text="AaBb 012")
                if thumb: st.image(thumb, use_container_width=True)
                else: st.warning("プレビュー生成失敗")
            else:
                st.warning("📥 未ダウンロード")
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
    
    # ★ページを開いたタイミングで、足りないフォントがあればダウンロードする
    sync_fonts_from_storage(db)

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
                    fname = f.name # デフォルトはそのまま
                    if a_type != "font":
                        # 画像のみUUID化 (フォントはファイル名を変えると内部名とずれる可能性があるのでそのまま推奨)
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
                        except Exception as e:
                            print(f"Upload warning: {e}") 

                        # 5. DB登録
                        try:
                            # 既に同じファイル名で登録があるかチェック(削除済み含む)
                            existing_asset = db.query(Asset).filter(Asset.image_filename == fname).first()
                            
                            if existing_asset:
                                # 存在する場合は情報を更新して復活させる
                                existing_asset.name = name
                                existing_asset.asset_type = a_type
                                existing_asset.is_deleted = False # 削除フラグを解除
                                st.success(f"更新・再有効化しました: {fname}")
                            else:
                                # 新規作成
                                new_asset = Asset(name=name, asset_type=a_type, image_filename=fname)
                                db.add(new_asset)
                                st.success(f"保存しました: {fname}")
                            
                            db.commit()
                            st.rerun()
                        except Exception as e:
                            st.error(f"DB登録エラー: {e}")
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

    # 3. フォント一覧
    with tabs[2]:
        # フォントアセット取得
        font_assets_all = db.query(Asset).filter(Asset.asset_type == "font", Asset.is_deleted == False).all()
        
        # --- 見本画像表示 (グリッド形式に変更) ---
        st.markdown("### 🔠 フォント一覧見本")
        if font_assets_all:
            sorted_fonts = sorted(
                font_assets_all, 
                key=lambda x: x.image_filename.lower() if x.image_filename else ""
            )
            
            # グリッド表示 (4列)
            cols = st.columns(4)
            for idx, font_asset in enumerate(sorted_fonts):
                with cols[idx % 4]:
                    font_path = os.path.join(FONT_DIR, font_asset.image_filename)
                    if os.path.exists(font_path):
                        # サムネイル生成（見本用のテキスト）
                        thumb = create_font_thumbnail(font_path, text="12:30\nLIVE", width=400, height=200)
                        
                        with st.container(border=True):
                            if thumb:
                                st.image(thumb, use_container_width=True)
                            else:
                                st.error("No Preview")
                            # フォント名を表示
                            st.caption(f"**{font_asset.name}**")
                    else:
                        st.warning(f"File Not Found: {font_asset.image_filename}")
        else:
            st.info("フォントが登録されていません。")

        st.divider()

        # --- 標準・お気に入りフォント設定エリア ---
        st.markdown("### ⚙️ フォント設定")
        st.caption("システム全体で標準的に使用するフォントなどを設定します。")
        
        font_options_map = {f.image_filename: f.name for f in font_assets_all}
        font_filenames = list(font_options_map.keys())
        
        if font_filenames:
            current_sys = db.query(SystemFontConfig).first()
            current_sys_val = current_sys.filename if current_sys and current_sys.filename in font_filenames else (font_filenames[0] if font_filenames else None)
            
            current_favs = db.query(FavoriteFont).all()
            current_fav_vals = [f.filename for f in current_favs if f.filename in font_filenames]

            c_sys, c_fav = st.columns([1, 2])
            
            # 標準フォント設定
            with c_sys:
                st.caption("標準フォント (システムデフォルト)")
                new_sys_val = st.selectbox(
                    "標準フォント", font_filenames, 
                    index=font_filenames.index(current_sys_val) if current_sys_val in font_filenames else 0,
                    format_func=lambda x: font_options_map.get(x, x),
                    key="sys_font_select", label_visibility="collapsed"
                )
            
            # お気に入りフォント設定
            with c_fav:
                st.caption("お気に入りフォント (メニュー上位に表示)")
                new_fav_vals = st.multiselect(
                    "お気に入り", font_filenames,
                    default=current_fav_vals,
                    format_func=lambda x: font_options_map.get(x, x),
                    key="fav_font_select", label_visibility="collapsed"
                )

            if st.button("設定を保存", type="primary", key="save_font_conf"):
                db.query(SystemFontConfig).delete()
                db.add(SystemFontConfig(filename=new_sys_val))
                
                db.query(FavoriteFont).delete()
                for f_name in new_fav_vals:
                    db.add(FavoriteFont(filename=f_name))
                
                db.commit()
                st.success("フォント設定を更新しました！")
                st.rerun()

        st.divider()

        # --- フォント一覧カード表示 (個別管理用) ---
        if not font_assets_all:
            st.info("登録されているフォントはありません")
        else:
            st.markdown("### 🛠️ 個別管理")
            cols = st.columns(3)
            for idx, asset in enumerate(font_assets_all):
                with cols[idx % 3]:
                    render_asset_card(asset, db, is_font=True)
    
    db.close()
