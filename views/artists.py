import streamlit as st
import uuid
import os
import time
import pandas as pd
from PIL import Image
from database import get_image_url
from services import artist_service

# 画像処理ロジックの読み込み
try:
    from logic_grid import (
        load_image_from_url, crop_smart, create_no_image_placeholder
    )
    HAS_LOGIC = True
except ImportError:
    HAS_LOGIC = False

# --- 手動トリミング用の関数 ---
def apply_manual_crop(img, scale=1.0, x_off=0, y_off=0, target_w=400, target_h=225):
    """画像を中心からトリミング・リサイズ・配置する関数"""
    if not img: 
        if 'create_no_image_placeholder' in globals():
            return create_no_image_placeholder(target_w, target_h)
        else:
            return Image.new("RGB", (target_w, target_h), (50, 50, 50))

    img_ratio = img.width / img.height
    target_ratio = target_w / target_h

    if img_ratio > target_ratio:
        base_h = target_h
        base_w = int(base_h * img_ratio)
    else:
        base_w = target_w
        base_h = int(base_w / img_ratio)

    final_w = max(1, int(base_w * scale))
    final_h = max(1, int(base_h * scale))

    resized_img = img.resize((final_w, final_h), Image.LANCZOS)
    canvas = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 255))

    paste_x = int((target_w - final_w) / 2 + x_off)
    paste_y = int((target_h - final_h) / 2 + y_off)

    if resized_img.mode != "RGBA":
        resized_img = resized_img.convert("RGBA")
    
    canvas.paste(resized_img, (paste_x, paste_y), resized_img)
    return canvas.convert("RGB")

# 画像処理をキャッシュ化
@st.cache_data(show_spinner=False)
def get_processed_thumbnail(image_filename, scale=1.0, x=0, y=0):
    target_w, target_h = 400, 225
    if not HAS_LOGIC:
        return Image.new("RGB", (target_w, target_h), (50, 50, 50))

    if image_filename:
        url = get_image_url(image_filename)
        if url:
            img = load_image_from_url(url)
            if img:
                is_manual = (scale != 1.0) or (x != 0) or (y != 0)
                if is_manual:
                    return apply_manual_crop(img, scale, x, y, target_w, target_h)
                else:
                    cropped = crop_smart(img)
                    return cropped.resize((target_w, target_h), Image.LANCZOS)
    
    return create_no_image_placeholder(target_w, target_h)

def render_artists_page():
    st.title("🎤 アーティスト管理")
    
    ALLOWED_EXTENSIONS = ['jpg', 'jpeg', 'png', 'webp', 'gif', 'bmp', 'tiff', 'tif']

    # ==========================================
    # 1. 新規登録エリア
    # ==========================================
    with st.expander("➕ 新規アーティスト登録", expanded=False):
        with st.form("new_artist"):
            n = st.text_input("名前")
            f = st.file_uploader("画像", type=ALLOWED_EXTENSIONS)
            if st.form_submit_button("登録"):
                if n:
                    _view, status = artist_service.create_artist(n, f)
                    if status == "restored":
                        st.success("復元しました")
                        time.sleep(1)
                        st.rerun()
                    elif status == "exists":
                        st.error("登録済み")
                    elif status == "created":
                        st.success("登録しました")
                        time.sleep(1)
                        st.rerun()
                    else:  # error
                        st.error("登録に失敗しました")
                else: st.error("名前必須")

    st.divider()

    # ==========================================
    # 2. 編集・削除エリア (高速化対応)
    # ==========================================
    st.subheader("📝 登録済みアーティストの編集")
    
    # 全リストを取得 (service 経由: ArtistView 一覧を名前昇順で返す)
    all_artists = artist_service.list_artists()
    
    if not all_artists:
        st.info("登録されているアーティストはいません。")
    else:
        # 選択ボックス (検索可能)
        # format_funcを使って名前を表示し、実体としてIDを扱う
        artist_map = {a.id: a for a in all_artists}
        selected_id = st.selectbox(
            "編集するアーティストを選択・検索してください",
            options=[0] + [a.id for a in all_artists],
            format_func=lambda x: "👇 (選択してください)" if x == 0 else artist_map[x].name
        )

        # 選択された場合のみ詳細を表示 (これで高速化)
        if selected_id != 0:
            target_artist = artist_map[selected_id]
            
            with st.container(border=True):
                c_img, c_edit = st.columns([1, 1.5])
                
                # 左カラム: 画像プレビュー (ここで初めて画像処理が走る)
                with c_img:
                    s = getattr(target_artist, 'crop_scale', 1.0) or 1.0
                    cx = getattr(target_artist, 'crop_x', 0) or 0
                    cy = getattr(target_artist, 'crop_y', 0) or 0
                    
                    thumb = get_processed_thumbnail(target_artist.image_filename, s, cx, cy)
                    st.image(thumb, caption="現在の表示 (黒背景)", width='stretch')

                # 右カラム: 編集コントロール
                with c_edit:
                    st.markdown(f"### {target_artist.name}")
                    
                    with st.expander("✏️ 名前・画像を変更", expanded=False):
                        new_name = st.text_input("名前変更", value=target_artist.name)
                        new_file = st.file_uploader("画像変更", type=ALLOWED_EXTENSIONS, key=f"up_{selected_id}")
                        if st.button("基本情報を更新", type="primary"):
                            if new_name:
                                artist_service.update_artist(selected_id, new_name, new_file)
                                st.success("更新しました")
                                time.sleep(0.5)
                                st.rerun()

                    st.markdown("#### 🖼️ 位置調整")
                    
                    col_slide1, col_slide2 = st.columns(2)
                    with col_slide1:
                        new_scale = st.slider("ズーム/縮小", 0.1, 3.0, float(s), 0.1, key=f"sc_{selected_id}")
                    with col_slide2:
                        # リセットボタン
                        if st.button("位置リセット", key=f"rst_{selected_id}"):
                            artist_service.update_artist_crop(selected_id, 1.0, 0, 0)
                            # セッション削除してリロード
                            for k in [f"sc_{selected_id}", f"sx_{selected_id}", f"sy_{selected_id}"]:
                                if k in st.session_state: del st.session_state[k]
                            st.rerun()

                    new_x = st.slider("左右 (X)", -200, 200, int(cx), 1, key=f"sx_{selected_id}")
                    new_y = st.slider("上下 (Y)", -112, 112, int(cy), 1, key=f"sy_{selected_id}")

                    # 変更検知して保存ボタン
                    has_changed = (new_scale != s) or (new_x != cx) or (new_y != cy)
                    if has_changed:
                        st.warning("⚠️ 変更されています")
                        if st.button("位置調整を保存", type="primary", key="save_pos"):
                            artist_service.update_artist_crop(selected_id, new_scale, new_x, new_y)
                            st.success("保存しました！")
                            time.sleep(0.5)
                            st.rerun()

                    st.divider()
                    
                    # 削除ボタン
                    if st.button("🗑️ このアーティストを削除", type="secondary"):
                        artist_service.soft_delete_artist(selected_id)
                        st.success("削除しました")
                        time.sleep(1)
                        st.rerun()

        # --- 全リスト確認用 (テキストのみ) ---
        with st.expander("📋 登録リスト一覧を表示 (テキストのみ)"):
            data = [{"ID": a.id, "名前": a.name, "画像": "あり" if a.image_filename else "なし"} for a in all_artists]
            st.dataframe(pd.DataFrame(data), width='stretch', hide_index=True)

    st.divider()

    # ==================================================
    # 3. アーティストデータの統合 (名寄せ) 機能
    # ==================================================
    with st.expander("🔄 アーティストデータの統合 (名寄せ)"):
        st.info("""
            **重複して登録されたアーティストを統合します。**
            1. 「残す方」と「統合・削除する方」を選んでください。
            2. 過去のタイムテーブルデータで使用されている名前も自動的に「残す方」の名前に書き換わります。
            3. 「統合・削除する方」は削除されます。この操作は取り消せません。
            """)

        # 選択肢の作成
        artist_options = {f"{ar.name} (ID: {ar.id})": ar.id for ar in all_artists}
        
        c_merge1, c_merge2 = st.columns(2)
        with c_merge1:
            winner_id = st.selectbox("✅ 残すアーティスト (正)", options=list(artist_options.values()), format_func=lambda x: [k for k, v in artist_options.items() if v == x][0], key="merge_winner")
        
        with c_merge2:
            # デフォルトでwinnerと違うものを選んでおく
            default_index = 1 if len(artist_options) > 1 else 0
            loser_id = st.selectbox("🗑️ 統合・削除するアーティスト (誤)", options=list(artist_options.values()), format_func=lambda x: [k for k, v in artist_options.items() if v == x][0], index=default_index, key="merge_loser")

        if st.button("⚠️ 統合を実行する", type="primary", width='stretch'):
            if winner_id == loser_id:
                st.error("同じアーティスト同士は統合できません。")
            else:
                # Phase 5-⑤a: ORM 直叩き → service へ移譲(bit-parity)。
                # commit/rollback・付け替え順序は service が所有。
                rows_count, grid_count, status = artist_service.merge_artists(winner_id, loser_id)
                if status == "merged":
                    st.toast(f"統合完了！ TT {rows_count} 箇所 / グリッド並び順 {grid_count} プロジェクトを修正しました。", icon="✅")
                    time.sleep(1)
                    st.rerun()
                elif status == "not_found":
                    st.error("データが見つかりません。")
                else:  # error
                    st.error("統合エラー: 処理に失敗しました")

