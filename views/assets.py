import streamlit as st
import uuid
import os
import requests
import html
import math
from PIL import Image, ImageDraw, ImageFont
from database import get_db, Asset, FavoriteFont, SystemFontConfig, upload_image_to_supabase, get_image_url, IMAGE_DIR
from constants import FONT_DIR
from services import asset_thumbnails, font_service

# ディレクトリの確実な作成
os.makedirs(IMAGE_DIR, exist_ok=True)
os.makedirs(FONT_DIR, exist_ok=True)

# --- ヘルパー関数: フォント同期 (Supabase -> ローカル) ---
def sync_fonts_from_storage(db):
    """
    DBにはあるがローカル(FONT_DIR)にないフォントを
    SupabaseのURLからダウンロードして復元する
    """
    # 削除されていないフォントを全て取得
    fonts = db.query(Asset).filter(Asset.asset_type == "font", Asset.is_deleted == False).all()

    restored_count = 0
    error_logs = []

    for font in fonts:
        local_path = os.path.join(FONT_DIR, font.image_filename)

        # ローカルにファイルがない場合のみダウンロードを試行
        if not os.path.exists(local_path):
            url = get_image_url(font.image_filename)

            if url:
                try:
                    # ★日本語ファイル名対策: URLに日本語が含まれる場合の安全策
                    # get_image_urlがすでにエンコード済みなら良いですが、念のため
                    # URL自体が無効でないかチェックしつつリクエストを送ります
                    response = requests.get(url, timeout=10)

                    if response.status_code == 200:
                        with open(local_path, "wb") as f:
                            f.write(response.content)
                        restored_count += 1
                    else:
                        # 404などのエラー詳細を記録
                        error_logs.append(f"❌ 取得失敗: {font.name} (Status: {response.status_code})")
                except Exception as e:
                    error_logs.append(f"❌ エラー: {font.name} ({str(e)})")
            else:
                 error_logs.append(f"❌ URL不明: {font.name}")

    # 結果の表示
    if restored_count > 0:
        st.toast(f"✅ {restored_count}個のフォントをクラウドから復元しました")

    # エラーがあった場合、デバッグ用に表示（原因特定のため）
    if error_logs:
        with st.expander("⚠️ フォント復元エラー（クリックして詳細を確認）", expanded=True):
            st.caption("以下のフォントがダウンロードできませんでした。Supabaseのバケット設定やファイル名を確認してください。")
            for log in error_logs:
                st.write(log)

# --- ヘルパー関数: フォントプレビュー画像の生成 (個別カード用) ---
@st.cache_data(show_spinner=False, max_entries=128)
def create_font_thumbnail(font_path, text="あいうABC", width=300, height=100, modified=0):
    try:
        img = Image.new("RGB", (width, height), (240, 242, 246)) # 薄いグレー背景
        draw = ImageDraw.Draw(img)
        try:
            font_size = int(height * 0.6)
            font = ImageFont.truetype(font_path, font_size)
        except Exception:
            return None

        bbox = draw.textbbox((0, 0), text, font=font)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        x = (width - w) // 2
        y = (height - h) // 2 - bbox[1]

        draw.text((x, y), text, font=font, fill=(50, 50, 50))
        return img
    except Exception:
        return None

# --- ヘルパー関数: 素材カードの描画 (共通化) ---
def render_asset_card(asset, db, is_font=False, show_font=False):
    with st.container(border=True):
        # 1. プレビュー表示
        if is_font:
            font_path = os.path.join(FONT_DIR, asset.image_filename)
            if show_font and os.path.exists(font_path):
                thumb = create_font_thumbnail(font_path, text="Design 123", modified=os.path.getmtime(font_path))
                if thumb: st.image(thumb, width='stretch')
                else: st.warning("プレビュー生成失敗")
            else:
                st.caption("見本は下のボタンで表示できます")
        else:
            u = html.escape((get_image_url(asset_thumbnails.filename(asset.image_filename)) if asset.image_filename else '') or '', quote=True)
            if u:
                st.markdown(f"""
                <div style="width:100%; height:150px; background:#f0f2f6; display:flex; align-items:center; justify-content:center; overflow:hidden; border-radius:4px; margin-bottom:8px;">
                    <img loading="lazy" decoding="async" src="{u}" style="max-width:100%; max-height:100%; object-fit:contain;">
                </div>
                """, unsafe_allow_html=True)

            original_url = get_image_url(asset.image_filename) if asset.image_filename else None
            if original_url: st.link_button('原寸画像を開く', original_url)
            if st.button('プレビュー再作成', key=f'btn_asset_thumb_{asset.id}'):
                try:
                    asset_thumbnails.ensure(asset.image_filename)
                    st.success('縮小プレビューを更新しました。')
                except Exception:
                    st.error('縮小画像を作れませんでした。元画像を確認してください。')

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
        if st.button("🗑️ 削除", key=f"del_{asset.id}", type="secondary", width='stretch'):
            asset.is_deleted = True
            db.commit()
            st.rerun()

def _render_upload(db):
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
                            if a_type != "font":
                                try: asset_thumbnails.store(f.getvalue(), fname)
                                except Exception: st.warning("素材は保存済みですが、縮小プレビューの保存に失敗しました。")
                            st.rerun()
                        except Exception as e:
                            st.error(f"DB登録エラー: {e}")
                else:
                    st.error("ファイルを選択してください")

    st.divider()



def _render_font_settings(db, font_assets_all):
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


def _asset_page(db, kind, query, page, size=12):
    source = db.query(Asset).filter(Asset.asset_type == kind, Asset.is_deleted == False)
    if query:
        pattern = '%' + query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        from sqlalchemy import or_
        source = source.filter(or_(Asset.name.ilike(pattern, escape='\\'), Asset.image_filename.ilike(pattern, escape='\\')))
    count = source.count()
    pages = max(1, math.ceil(count / size))
    page = min(max(1, page), pages)
    return source.order_by(Asset.id.desc()).offset((page-1)*size).limit(size).all(), count, page, pages


def _reset_asset_page():
    st.session_state['assets_page'] = 1
    st.session_state.pop('assets_font_previews', None)


def _turn_asset_page(delta):
    st.session_state['assets_page'] = max(1, st.session_state.get('assets_page', 1) + delta)
    st.session_state.pop('assets_font_previews', None)


def render_assets_page():
    st.title("🗂️ 素材・フォント管理")
    st.caption("選択中の種類だけを12件ずつ表示します。画像は縮小プレビュー、原寸はクリックで開きます。")
    db = next(get_db())
    try:
        _render_upload(db)
        kind = st.radio('素材の種類', ['logo', 'background', 'font'], horizontal=True,
                        format_func=lambda value:{'logo':'ロゴ','background':'背景','font':'フォント'}[value],
                        key='assets_kind', on_change=_reset_asset_page)
        query = st.text_input('名前・ファイル名で検索', key='assets_search', on_change=_reset_asset_page).strip()
        assets, count, page, pages = _asset_page(db, kind, query, st.session_state.get('assets_page', 1))
        st.session_state['assets_page'] = page
        st.caption(f'{count}件 · {page} / {pages} ページ')
        show_font = False
        if kind == 'font':
            with st.expander('フォント設定・復元'):
                font_assets_all = db.query(Asset).filter(Asset.asset_type == 'font', Asset.is_deleted == False).all()
                _render_font_settings(db, font_assets_all)
                if st.button('全フォントをクラウドから復元', key='btn_restore_fonts'):
                    sync_fonts_from_storage(db)
            signature = (query, page, tuple(a.id for a in assets))
            if st.button('このページのフォント見本を表示', key='btn_assets_font_preview'):
                for asset in assets:
                    font_service.ensure_font_path(asset.image_filename)
                st.session_state['assets_font_previews'] = signature
            show_font = st.session_state.get('assets_font_previews') == signature
        if not assets: st.info('該当する素材はありません。')
        for start in range(0, len(assets), 4):
            cols = st.columns(4)
            for col, asset in zip(cols, assets[start:start+4]):
                with col: render_asset_card(asset, db, is_font=kind=='font', show_font=show_font)
        prev, label, following = st.columns(3)
        prev.button('前のページ', key='btn_assets_prev', disabled=page<=1, on_click=_turn_asset_page, args=(-1,))
        label.caption(f'{page} / {pages} ページ · 1ページ12件')
        following.button('次のページ', key='btn_assets_next', disabled=page>=pages, on_click=_turn_asset_page, args=(1,))
    finally:
        db.close()
