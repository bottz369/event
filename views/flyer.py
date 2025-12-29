import streamlit as st
from PIL import Image, ImageDraw, ImageFont
import io
import os
import json
from constants import FONT_DIR
from database import get_db, TimetableProject, Asset, get_image_url

# --- 描画ロジック (変更なし) ---
def draw_text_centered(draw, text, x, y, font, fill, stroke_width=0, stroke_fill=None, anchor="ma"):
    draw.text((x, y), text, font=font, fill=fill, stroke_width=stroke_width, stroke_fill=stroke_fill, anchor=anchor)

def draw_multiline_text_centered(draw, text, x, y, font, fill, line_spacing_ratio=1.2, stroke_width=0, stroke_fill=None, anchor="ma"):
    lines = text.split('\n')
    bbox = draw.textbbox((0, 0), "A", font=font)
    line_height = (bbox[3] - bbox[1]) * line_spacing_ratio
    current_y = y
    for line in lines:
        draw_text_centered(draw, line, x, current_y, font, fill, stroke_width, stroke_fill, anchor)
        current_y += line_height
    return current_y

def resize_image_to_fit(img, max_width, max_height):
    width_ratio = max_width / img.width
    height_ratio = max_height / img.height
    ratio = min(width_ratio, height_ratio)
    new_size = (int(img.width * ratio), int(img.height * ratio))
    return img.resize(new_size, Image.LANCZOS)

def create_flyer_image(bg_path, logo_path, main_bytes, date_str, venue_str, open_time, start_time, ticket_info, notes, font_path, text_color, stroke_color):
    try: base_img = Image.open(bg_path).convert("RGBA")
    except: return None
    width, height = base_img.size
    draw = ImageDraw.Draw(base_img)
    
    try:
        font_date = ImageFont.truetype(font_path, int(width * 0.08))
        font_time = ImageFont.truetype(font_path, int(width * 0.05))
        font_venue = ImageFont.truetype(font_path, int(width * 0.04))
        font_ticket = ImageFont.truetype(font_path, int(width * 0.045))
        font_note = ImageFont.truetype(font_path, int(width * 0.025))
    except:
        font_date = ImageFont.load_default()
    
    current_y = height * 0.05
    center_x = width / 2
    stroke_w = int(width * 0.003)

    if logo_path:
        try:
            logo_img = Image.open(logo_path).convert("RGBA")
            logo_img = resize_image_to_fit(logo_img, width * 0.8, height * 0.2)
            logo_x = int((width - logo_img.width) / 2)
            base_img.paste(logo_img, (logo_x, int(current_y)), logo_img)
            current_y += logo_img.height + (height * 0.02)
        except: pass

    draw_text_centered(draw, date_str, center_x, current_y, font_date, text_color, stroke_w, stroke_color)
    bbox = draw.textbbox((0, 0), date_str, font=font_date)
    current_y += (bbox[3] - bbox[1]) + (height * 0.01)
    
    draw_text_centered(draw, venue_str, center_x, current_y, font_venue, text_color, stroke_w, stroke_color)
    bbox = draw.textbbox((0, 0), venue_str, font=font_venue)
    current_y += (bbox[3] - bbox[1]) + (height * 0.02)

    time_str = f"OPEN {open_time} ▶ START {start_time}"
    draw_text_centered(draw, time_str, center_x, current_y, font_time, text_color, stroke_w, stroke_color)
    bbox = draw.textbbox((0, 0), time_str, font=font_time)
    current_y += (bbox[3] - bbox[1]) + (height * 0.03)

    if main_bytes:
        try:
            main_img = Image.open(main_bytes).convert("RGBA")
            available_height = (height * 0.95) - current_y - (height * 0.25)
            if available_height > 100:
                main_img = resize_image_to_fit(main_img, width * 0.9, available_height)
                main_x = int((width - main_img.width) / 2)
                base_img.paste(main_img, (main_x, int(current_y)), main_img)
                current_y += main_img.height + (height * 0.03)
        except: pass

    current_y = draw_multiline_text_centered(draw, ticket_info, center_x, current_y, font_ticket, text_color, 1.2, stroke_w, stroke_color)
    current_y += height * 0.02
    draw_multiline_text_centered(draw, notes, center_x, current_y, font_note, text_color, 1.3, 0, None)

    return base_img

# --- コンポーネント化 ---
def render_flyer_editor(project_id):
    db = next(get_db())
    proj = db.query(TimetableProject).filter(TimetableProject.id == project_id).first()
    
    if not proj:
        st.error("プロジェクトが見つかりません")
        return

    st.subheader("📑 フライヤーセット作成")
    
    # アーカイブから素材を取得
    logos = db.query(Asset).filter(Asset.asset_type == "logo", Asset.is_deleted == False).all()
    bgs = db.query(Asset).filter(Asset.asset_type == "background", Asset.is_deleted == False).all()
    
    if not logos or not bgs:
        st.warning("⚠️ 先に「素材アーカイブ」メニューでロゴと背景を登録してください")
        return

    c_conf, c_prev = st.columns([1, 1])

    with c_conf:
        with st.expander("1. 素材選択 (アーカイブより)", expanded=True):
            # ロゴ選択
            logo_opts = {a.id: a.name for a in logos}
            l_idx = 0
            if "flyer_logo_id" in st.session_state and st.session_state.flyer_logo_id in logo_opts:
                l_idx = list(logo_opts.keys()).index(st.session_state.flyer_logo_id)
            st.selectbox("ロゴ画像", options=logo_opts.keys(), format_func=lambda x: logo_opts[x], key="flyer_logo_id", index=l_idx)
            
            # 背景選択
            bg_opts = {a.id: a.name for a in bgs}
            b_idx = 0
            if "flyer_bg_id" in st.session_state and st.session_state.flyer_bg_id in bg_opts:
                b_idx = list(bg_opts.keys()).index(st.session_state.flyer_bg_id)
            st.selectbox("背景画像", options=bg_opts.keys(), format_func=lambda x: bg_opts[x], key="flyer_bg_id", index=b_idx)
            
            # メイン画像 (アップロード: キャッシュなしで直接変数で受ける)
            st.caption("メイン画像 (タイムテーブル/グリッド)")
            main_file = st.file_uploader("画像をアップロード", type=['png','jpg','webp'])
            if main_file:
                st.session_state.flyer_main_image_cache = main_file

        with st.expander("2. テキスト情報", expanded=True):
            # キーを指定してバインド (workspace.pyで初期値ロード済み)
            st.text_input("開催日表記", key="flyer_date_str")
            st.text_input("会場表記", key="flyer_venue_str")
            c1, c2 = st.columns(2)
            with c1: st.text_input("OPEN", key="flyer_open_time")
            with c2: st.text_input("START", key="flyer_start_time")
            st.text_area("チケット情報", height=100, key="flyer_ticket_info")
            st.text_area("注意事項", height=80, key="flyer_notes")

        with st.expander("3. デザイン", expanded=False):
            all_fonts = [f for f in os.listdir(FONT_DIR) if f.lower().endswith(".ttf")]
            if not all_fonts: all_fonts = ["keifont.ttf"]
            f_idx = 0
            if "flyer_font" in st.session_state and st.session_state.flyer_font in all_fonts:
                f_idx = all_fonts.index(st.session_state.flyer_font)
            st.selectbox("フォント", all_fonts, index=f_idx, key="flyer_font")
            st.color_picker("文字色", key="flyer_text_color")
            st.color_picker("縁取り色", key="flyer_stroke_color")

        # ★修正: 保存ボタン削除 (ワークスペースの「上書き保存」で保存されます)
        
        # プレビュー更新ボタン
        if st.button("🔄 プレビューを更新", type="primary", use_container_width=True):
            pass # rerunがかかるので更新される

    with c_prev:
        st.markdown("##### プレビュー")
        
        # 画像データの準備
        main_img_bytes = main_file if main_file else st.session_state.get("flyer_main_image_cache")
        
        if "flyer_bg_id" in st.session_state and "flyer_logo_id" in st.session_state and main_img_bytes:
            bg_asset = db.query(Asset).filter(Asset.id == st.session_state.flyer_bg_id).first()
            logo_asset = db.query(Asset).filter(Asset.id == st.session_state.flyer_logo_id).first()
            
            if bg_asset and logo_asset:
                bg_path = get_image_url(bg_asset.image_filename)
                logo_path = get_image_url(logo_asset.image_filename)
                
                if bg_path and logo_path:
                    try:
                        # セッションステートの値を使って生成
                        font_path = os.path.join(FONT_DIR, st.session_state.get("flyer_font", "keifont.ttf"))
                        img = create_flyer_image(
                            bg_path, logo_path, main_img_bytes,
                            st.session_state.get("flyer_date_str", ""), 
                            st.session_state.get("flyer_venue_str", ""),
                            st.session_state.get("flyer_open_time", ""), 
                            st.session_state.get("flyer_start_time", ""),
                            st.session_state.get("flyer_ticket_info", ""), 
                            st.session_state.get("flyer_notes", ""),
                            font_path, 
                            st.session_state.get("flyer_text_color", "#FFFFFF"), 
                            st.session_state.get("flyer_stroke_color", "#000000")
                        )
                        
                        if img:
                            st.image(img, use_container_width=True)
                            buf = io.BytesIO()
                            img.save(buf, format="PNG")
                            st.download_button("画像をダウンロード", buf.getvalue(), "flyer.png", "image/png", type="primary", use_container_width=True)
                    except Exception as e:
                        st.error(f"生成エラー: {e}")
        else:
            st.info("👈 設定を入力し、メイン画像をアップロードするとプレビューが表示されます")
    
    db.close()
