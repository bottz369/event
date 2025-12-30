import streamlit as st
from PIL import Image, ImageDraw, ImageFont
import io
import os
import requests  # ★追加: URLから画像を読み込むために必要
from constants import FONT_DIR
from database import get_db, TimetableProject, Asset, get_image_url
from utils import create_font_specimen_img

# --- ヘルパー関数: 画像読み込みの強化 ---
def load_image_from_source(source):
    """
    パス(str), URL(str), Imageオブジェクト, アップロードファイルなど
    あらゆる形式から PIL.Image を生成する万能関数
    """
    if source is None:
        return None

    try:
        # 1. すでにPIL画像の場合
        if isinstance(source, Image.Image):
            return source.convert("RGBA")
        
        # 2. 文字列（パス または URL）の場合
        if isinstance(source, str):
            # URLの場合 (Supabase対応)
            if source.startswith("http"):
                response = requests.get(source, timeout=10)
                response.raise_for_status()
                return Image.open(io.BytesIO(response.content)).convert("RGBA")
            # ローカルパスの場合
            else:
                return Image.open(source).convert("RGBA")

        # 3. アップロードされたファイル (BytesIO) の場合
        return Image.open(source).convert("RGBA")

    except Exception as e:
        print(f"Image Load Error: {e}")
        return None

# --- 描画ヘルパー関数 ---
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

# --- フライヤー画像合成ロジック ---
def create_flyer_image(
    bg_source, logo_source, main_source, 
    sub_title, input_1, bottom_left, bottom_right, 
    font_path, text_color, stroke_color
):
    # 背景読み込み (URL対応版)
    base_img = load_image_from_source(bg_source)
    if base_img is None:
        return None
        
    width, height = base_img.size
    draw = ImageDraw.Draw(base_img)
    
    # フォント設定
    try:
        font_sub = ImageFont.truetype(font_path, int(width * 0.08))
        font_in1 = ImageFont.truetype(font_path, int(width * 0.04))
        font_btm = ImageFont.truetype(font_path, int(width * 0.05))
        font_ticket = ImageFont.truetype(font_path, int(width * 0.045))
        font_free = ImageFont.truetype(font_path, int(width * 0.025))
    except:
        font_sub = font_in1 = font_btm = font_ticket = font_free = ImageFont.load_default()
    
    current_y = height * 0.05
    center_x = width / 2
    stroke_w = int(width * 0.003)

    # 1. ロゴ配置 (URL対応版)
    logo_img = load_image_from_source(logo_source)
    if logo_img:
        try:
            logo_img = resize_image_to_fit(logo_img, width * 0.8, height * 0.2)
            logo_x = int((width - logo_img.width) / 2)
            base_img.paste(logo_img, (logo_x, int(current_y)), logo_img)
            current_y += logo_img.height + (height * 0.02)
        except: pass
    else:
        current_y += height * 0.1

    # 2. 上部テキスト
    if sub_title:
        draw_text_centered(draw, sub_title, center_x, current_y, font_sub, text_color, stroke_w, stroke_color)
        bbox = draw.textbbox((0, 0), sub_title, font=font_sub)
        current_y += (bbox[3] - bbox[1]) + (height * 0.01)
    
    if input_1:
        draw_text_centered(draw, input_1, center_x, current_y, font_in1, text_color, stroke_w, stroke_color)
        bbox = draw.textbbox((0, 0), input_1, font=font_in1)
        current_y += (bbox[3] - bbox[1]) + (height * 0.02)

    time_str = f"{bottom_left}   {bottom_right}"
    if time_str.strip():
        draw_text_centered(draw, time_str, center_x, current_y, font_btm, text_color, stroke_w, stroke_color)
        bbox = draw.textbbox((0, 0), time_str, font=font_btm)
        current_y += (bbox[3] - bbox[1]) + (height * 0.03)

    # 3. メイン画像 (URL対応版)
    main_img = load_image_from_source(main_source)
    if main_img:
        try:
            available_height = (height * 0.95) - current_y - (height * 0.25)
            if available_height > 100:
                main_img = resize_image_to_fit(main_img, width * 0.95, available_height)
                main_x = int((width - main_img.width) / 2)
                base_img.paste(main_img, (main_x, int(current_y)), main_img)
                current_y += main_img.height + (height * 0.03)
        except: pass

    # 4. 下部情報
    ticket_str = ""
    if "proj_tickets" in st.session_state:
        lines = []
        for t in st.session_state.proj_tickets:
            line = f"{t.get('name','')} {t.get('price','')}"
            if t.get("note"): line += f" ({t.get('note')})"
            if line.strip(): lines.append(line)
        ticket_str = "\n".join(lines)

    notes_str = ""
    if "proj_free_text" in st.session_state:
        lines = []
        for f in st.session_state.proj_free_text:
            if f.get("title"): lines.append(f"【{f.get('title')}】")
            if f.get("content"): lines.append(f.get("content"))
        notes_str = "\n".join(lines)

    if ticket_str:
        current_y = draw_multiline_text_centered(draw, ticket_str, center_x, current_y, font_ticket, text_color, 1.2, stroke_w, stroke_color)
        current_y += height * 0.02
    
    if notes_str:
        draw_multiline_text_centered(draw, notes_str, center_x, current_y, font_free, text_color, 1.3, 0, None)

    return base_img

# --- 画面描画 ---
def render_flyer_editor(project_id):
    db = next(get_db())
    
    proj = db.query(TimetableProject).filter(TimetableProject.id == project_id).first()
    logos = db.query(Asset).filter(Asset.asset_type == "logo", Asset.is_deleted == False).all()
    bgs = db.query(Asset).filter(Asset.asset_type == "background", Asset.is_deleted == False).all()
    
    if not proj:
        st.error("プロジェクトが見つかりません")
        db.close()
        return

    st.subheader("📑 フライヤーセット生成")
    
    if not bgs:
        st.warning("⚠️ 「素材アーカイブ」で背景画像を登録してください。")
        db.close()
        return

    # --- セッション初期化（生成済み画像保持用） ---
    if "flyer_result_grid" not in st.session_state: st.session_state.flyer_result_grid = None
    if "flyer_result_tt" not in st.session_state: st.session_state.flyer_result_tt = None
    if "flyer_result_custom" not in st.session_state: st.session_state.flyer_result_custom = None

    # --- レイアウト ---
    c_conf, c_prev = st.columns([1, 1])

    with c_conf:
        with st.expander("1. 素材選択 (共通)", expanded=True):
            logo_opts = {0: "(なし)"}
            for a in logos: logo_opts[a.id] = a.name
            current_logo_id = st.session_state.get("flyer_logo_id", 0)
            if current_logo_id not in logo_opts: current_logo_id = 0
            st.selectbox("ロゴ画像", options=logo_opts.keys(), format_func=lambda x: logo_opts[x], key="flyer_logo_id")
            
            bg_opts = {a.id: a.name for a in bgs}
            current_bg_id = st.session_state.get("flyer_bg_id")
            if current_bg_id not in bg_opts and bg_opts:
                st.session_state.flyer_bg_id = list(bg_opts.keys())[0]
            st.selectbox("背景画像", options=bg_opts.keys(), format_func=lambda x: bg_opts[x], key="flyer_bg_id")

        with st.expander("2. テキスト情報 (共通)", expanded=True):
            st.text_input("サブタイトル", key="flyer_sub_title")
            st.text_input("入力1", key="flyer_input_1")
            c1, c2 = st.columns(2)
            with c1: st.text_input("左下", key="flyer_bottom_left")
            with c2: st.text_input("右下", key="flyer_bottom_right")

        with st.expander("3. デザイン (共通)", expanded=False):
            all_fonts = [f for f in os.listdir(FONT_DIR) if f.lower().endswith(".ttf")]
            if not all_fonts: all_fonts = ["keifont.ttf"]
            
            if "flyer_font" not in st.session_state or st.session_state.flyer_font not in all_fonts:
                st.session_state.flyer_font = all_fonts[0]
            
            st.selectbox("フォント", all_fonts, key="flyer_font")
            st.color_picker("文字色", key="flyer_text_color")
            st.color_picker("縁取り色", key="flyer_stroke_color")
            
        st.divider()
        
        # --- ★ここがポイント: 生成ボタン ---
        if st.button("🚀 画像を生成する", type="primary", use_container_width=True):
            bg_id = st.session_state.get("flyer_bg_id")
            logo_id = st.session_state.get("flyer_logo_id")
            
            # URLを取得 (ローカルファイルパスではなくURL)
            bg_url = None
            if bg_id:
                bg_asset = db.query(Asset).filter(Asset.id == bg_id).first()
                if bg_asset: bg_url = get_image_url(bg_asset.image_filename)
            
            logo_url = None
            if logo_id and logo_id != 0:
                logo_asset = db.query(Asset).filter(Asset.id == logo_id).first()
                if logo_asset: logo_url = get_image_url(logo_asset.image_filename)
            
            font_path = os.path.join(FONT_DIR, st.session_state.get("flyer_font", "keifont.ttf"))
            
            if not bg_url:
                st.error("背景画像のURL取得に失敗しました")
            else:
                common_args = {
                    "bg_source": bg_url, # ★URLを渡す
                    "logo_source": logo_url, # ★URLを渡す
                    "sub_title": st.session_state.get("flyer_sub_title", ""),
                    "input_1": st.session_state.get("flyer_input_1", ""),
                    "bottom_left": st.session_state.get("flyer_bottom_left", ""),
                    "bottom_right": st.session_state.get("flyer_bottom_right", ""),
                    "font_path": font_path,
                    "text_color": st.session_state.get("flyer_text_color", "#FFFFFF"),
                    "stroke_color": st.session_state.get("flyer_stroke_color", "#000000")
                }

                with st.spinner("画像をダウンロード & 生成中..."):
                    # 1. Grid
                    grid_source = st.session_state.get("last_generated_grid_image")
                    if grid_source:
                        st.session_state.flyer_result_grid = create_flyer_image(main_source=grid_source, **common_args)
                    
                    # 2. TT
                    tt_source = st.session_state.get("last_generated_tt_image")
                    if tt_source:
                        st.session_state.flyer_result_tt = create_flyer_image(main_source=tt_source, **common_args)
                    
                    # 3. Custom (もしファイルがあれば)
                    custom_file = st.session_state.get("flyer_custom_file_uploader")
                    if custom_file:
                        st.session_state.flyer_result_custom = create_flyer_image(main_source=custom_file, **common_args)
                
                st.success("生成完了！右側で確認・ダウンロードできます 👉")

    # --- プレビュー & ダウンロードエリア ---
    with c_prev:
        st.markdown("##### 生成結果 & ダウンロード")
        
        tab_grid, tab_tt, tab_custom = st.tabs(["🖼️ アー写グリッド", "⏱️ タイムテーブル", "📁 カスタム"])

        with tab_grid:
            if st.session_state.flyer_result_grid:
                st.image(st.session_state.flyer_result_grid, use_container_width=True)
                buf = io.BytesIO()
                st.session_state.flyer_result_grid.save(buf, format="PNG")
                st.download_button("画像をダウンロード", buf.getvalue(), "flyer_grid.png", "image/png", type="primary", use_container_width=True, key="dl_grid")
            else:
                st.info("左側の「画像を生成する」ボタンを押してください。")

        with tab_tt:
            if st.session_state.flyer_result_tt:
                st.image(st.session_state.flyer_result_tt, use_container_width=True)
                buf = io.BytesIO()
                st.session_state.flyer_result_tt.save(buf, format="PNG")
                st.download_button("画像をダウンロード", buf.getvalue(), "flyer_tt.png", "image/png", type="primary", use_container_width=True, key="dl_tt")
            else:
                st.info("左側の「画像を生成する」ボタンを押してください。")

        with tab_custom:
            st.file_uploader("手動画像 (任意)", type=['png','jpg'], key="flyer_custom_file_uploader")
            if st.session_state.flyer_result_custom:
                st.image(st.session_state.flyer_result_custom, use_container_width=True)
                buf = io.BytesIO()
                st.session_state.flyer_result_custom.save(buf, format="PNG")
                st.download_button("画像をダウンロード", buf.getvalue(), "flyer_custom.png", "image/png", type="primary", use_container_width=True, key="dl_custom")

    db.close()
