import streamlit as st
from PIL import Image, ImageDraw, ImageFont
import io
import os
import json
from constants import FONT_DIR
from database import get_db, TimetableProject, Asset, get_image_url

# --- 描画ロジック ---
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

def create_flyer_image(
    bg_path, logo_path, main_bytes, 
    sub_title, input_1, bottom_left, bottom_right, 
    font_path, text_color, stroke_color
):
    try: base_img = Image.open(bg_path).convert("RGBA")
    except: return None
    width, height = base_img.size
    draw = ImageDraw.Draw(base_img)
    
    try:
        # フォントサイズ設定 (比率は適宜調整)
        font_sub = ImageFont.truetype(font_path, int(width * 0.08))   # サブタイトル
        font_in1 = ImageFont.truetype(font_path, int(width * 0.04))   # 入力1
        font_btm = ImageFont.truetype(font_path, int(width * 0.05))   # 左下/右下
        font_ticket = ImageFont.truetype(font_path, int(width * 0.045))
        font_free = ImageFont.truetype(font_path, int(width * 0.025))
    except:
        font_sub = font_in1 = font_btm = font_ticket = font_free = ImageFont.load_default()
    
    current_y = height * 0.05
    center_x = width / 2
    stroke_w = int(width * 0.003)

    # 1. ロゴ (存在する場合のみ描画)
    if logo_path:
        try:
            logo_img = Image.open(logo_path).convert("RGBA")
            logo_img = resize_image_to_fit(logo_img, width * 0.8, height * 0.2)
            logo_x = int((width - logo_img.width) / 2)
            base_img.paste(logo_img, (logo_x, int(current_y)), logo_img)
            current_y += logo_img.height + (height * 0.02)
        except: pass
    else:
        # ロゴがない場合もスペースを少し空ける（お好みで調整）
        current_y += height * 0.1

    # 2. サブタイトル (旧 Date)
    if sub_title:
        draw_text_centered(draw, sub_title, center_x, current_y, font_sub, text_color, stroke_w, stroke_color)
        bbox = draw.textbbox((0, 0), sub_title, font=font_sub)
        current_y += (bbox[3] - bbox[1]) + (height * 0.01)
    
    # 3. 入力1 (旧 Venue)
    if input_1:
        draw_text_centered(draw, input_1, center_x, current_y, font_in1, text_color, stroke_w, stroke_color)
        bbox = draw.textbbox((0, 0), input_1, font=font_in1)
        current_y += (bbox[3] - bbox[1]) + (height * 0.02)

    # 4. 左下 / 右下 (旧 OPEN / START)
    time_str = f"{bottom_left}   {bottom_right}"
    if time_str.strip():
        draw_text_centered(draw, time_str, center_x, current_y, font_btm, text_color, stroke_w, stroke_color)
        bbox = draw.textbbox((0, 0), time_str, font=font_btm)
        current_y += (bbox[3] - bbox[1]) + (height * 0.03)

    # 5. メイン画像 (存在する場合のみ描画)
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
    else:
        # 画像がない場合はスペースだけ確保するならここに追加
        pass

    # 6. チケット情報・自由記述 (Overviewタブのセッションデータから生成)
    ticket_str = ""
    if "proj_tickets" in st.session_state:
        lines = []
        for t in st.session_state.proj_tickets:
            # "チケット名 ¥金額 (備考)" の形式で結合
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

# --- コンポーネント化 ---
def render_flyer_editor(project_id):
    db = next(get_db())
    proj = db.query(TimetableProject).filter(TimetableProject.id == project_id).first()
    
    if not proj:
        st.error("プロジェクトが見つかりません")
        return

    st.subheader("📑 フライヤーセット作成")
    
    logos = db.query(Asset).filter(Asset.asset_type == "logo", Asset.is_deleted == False).all()
    bgs = db.query(Asset).filter(Asset.asset_type == "background", Asset.is_deleted == False).all()
    
    if not bgs:
        st.warning("⚠️ 「素材アーカイブ」メニューで、少なくとも1つの『背景画像』を登録してください。")
        return

    c_conf, c_prev = st.columns([1, 1])

    with c_conf:
        with st.expander("1. 素材選択", expanded=True):
            # ロゴ選択（任意）
            logo_opts = {0: "(なし)"}
            for a in logos: logo_opts[a.id] = a.name
            
            l_idx = 0
            current_logo_id = st.session_state.get("flyer_logo_id", 0)
            if current_logo_id in logo_opts:
                l_idx = list(logo_opts.keys()).index(current_logo_id)
            
            st.selectbox("ロゴ画像", options=logo_opts.keys(), format_func=lambda x: logo_opts[x], key="flyer_logo_id", index=l_idx)
            
            # 背景選択（必須）
            bg_opts = {a.id: a.name for a in bgs}
            b_idx = 0
            current_bg_id = st.session_state.get("flyer_bg_id")
            # セッションに無い、または削除されたIDの場合は先頭を選択
            if not current_bg_id or current_bg_id not in bg_opts:
                if bg_opts:
                    first_id = list(bg_opts.keys())[0]
                    st.session_state.flyer_bg_id = first_id
                    current_bg_id = first_id
            
            if current_bg_id in bg_opts:
                b_idx = list(bg_opts.keys()).index(current_bg_id)
            
            st.selectbox("背景画像", options=bg_opts.keys(), format_func=lambda x: bg_opts[x], key="flyer_bg_id", index=b_idx)
            
            st.caption("メイン画像 (タイムテーブル/グリッド)")
            main_file = st.file_uploader("画像をアップロード", type=['png','jpg','webp'])
            if main_file:
                st.session_state.flyer_main_image_cache = main_file

        with st.expander("2. テキスト情報 (その他はイベント概要タブ)", expanded=True):
            # 項目名を変更
            st.text_input("サブタイトル", key="flyer_sub_title")
            st.text_input("入力1 (会場など)", key="flyer_input_1")
            c1, c2 = st.columns(2)
            with c1: st.text_input("左下 (OPENなど)", key="flyer_bottom_left")
            with c2: st.text_input("右下 (STARTなど)", key="flyer_bottom_right")
            
            st.info("ℹ️ チケット情報や注意事項は「イベント概要」タブで入力してください")

        with st.expander("3. デザイン", expanded=False):
            all_fonts = [f for f in os.listdir(FONT_DIR) if f.lower().endswith(".ttf")]
            if not all_fonts: all_fonts = ["keifont.ttf"]
            f_idx = 0
            if "flyer_font" in st.session_state and st.session_state.flyer_font in all_fonts:
                f_idx = all_fonts.index(st.session_state.flyer_font)
            st.selectbox("フォント", all_fonts, index=f_idx, key="flyer_font")
            st.color_picker("文字色", key="flyer_text_color")
            st.color_picker("縁取り色", key="flyer_stroke_color")

        # プレビュー更新ボタン
        if st.button("🔄 プレビューを更新", type="primary", use_container_width=True):
            pass 

    with c_prev:
        st.markdown("##### プレビュー")
        
        # --- 描画実行の判定ロジック ---
        # 背景IDさえあれば生成を試みる
        bg_id = st.session_state.get("flyer_bg_id")
        
        if bg_id:
            # 必要な変数の準備
            bg_asset = db.query(Asset).filter(Asset.id == bg_id).first()
            bg_path = get_image_url(bg_asset.image_filename) if bg_asset else None
            
            # ロゴ (任意)
            logo_id = st.session_state.get("flyer_logo_id")
            logo_path = None
            if logo_id and logo_id != 0:
                logo_asset = db.query(Asset).filter(Asset.id == logo_id).first()
                if logo_asset:
                    logo_path = get_image_url(logo_asset.image_filename)
            
            # メイン画像 (任意)
            main_img_bytes = main_file if main_file else st.session_state.get("flyer_main_image_cache")
            
            if bg_path:
                try:
                    font_path = os.path.join(FONT_DIR, st.session_state.get("flyer_font", "keifont.ttf"))
                    
                    img = create_flyer_image(
                        bg_path, logo_path, main_img_bytes,
                        st.session_state.get("flyer_sub_title", ""), 
                        st.session_state.get("flyer_input_1", ""),
                        st.session_state.get("flyer_bottom_left", ""), 
                        st.session_state.get("flyer_bottom_right", ""),
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
                st.error("背景画像ファイルの読み込みに失敗しました")
        else:
            st.info("👈 背景画像を選択するとプレビューが表示されます")
    
    db.close()
