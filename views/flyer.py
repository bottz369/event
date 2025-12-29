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
    # ベース
    base_img = Image.open(bg_path).convert("RGBA")
    width, height = base_img.size
    draw = ImageDraw.Draw(base_img)
    
    # フォント設定
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

    # ロゴ
    if logo_path:
        logo_img = Image.open(logo_path).convert("RGBA")
        logo_img = resize_image_to_fit(logo_img, width * 0.8, height * 0.2)
        logo_x = int((width - logo_img.width) / 2)
        base_img.paste(logo_img, (logo_x, int(current_y)), logo_img)
        current_y += logo_img.height + (height * 0.02)

    # 日時・会場
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

    # メイン画像
    if main_bytes:
        main_img = Image.open(main_bytes).convert("RGBA")
        available_height = (height * 0.95) - current_y - (height * 0.25)
        if available_height > 100:
            main_img = resize_image_to_fit(main_img, width * 0.9, available_height)
            main_x = int((width - main_img.width) / 2)
            base_img.paste(main_img, (main_x, int(current_y)), main_img)
            current_y += main_img.height + (height * 0.03)

    # チケット・注意
    current_y = draw_multiline_text_centered(draw, ticket_info, center_x, current_y, font_ticket, text_color, 1.2, stroke_w, stroke_color)
    current_y += height * 0.02
    draw_multiline_text_centered(draw, notes, center_x, current_y, font_note, text_color, 1.3, 0, None)

    return base_img

# --- コンポーネント化 ---
def render_flyer_editor(project_id):
    """プロジェクトIDを指定して呼び出すエディタコンポーネント"""
    db = next(get_db())
    proj = db.query(TimetableProject).filter(TimetableProject.id == project_id).first()
    
    if not proj:
        st.error("プロジェクトが見つかりません")
        return

    st.subheader("📑 フライヤーセット作成")
    
    # 保存済み設定のロード
    settings = {}
    if proj.flyer_json:
        try: settings = json.loads(proj.flyer_json)
        except: pass

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
            sel_logo_id = st.selectbox("ロゴ画像", options=logo_opts.keys(), format_func=lambda x: logo_opts[x], 
                                     index=list(logo_opts.keys()).index(settings.get("logo_id")) if settings.get("logo_id") in logo_opts else 0)
            
            # 背景選択
            bg_opts = {a.id: a.name for a in bgs}
            sel_bg_id = st.selectbox("背景画像", options=bg_opts.keys(), format_func=lambda x: bg_opts[x],
                                   index=list(bg_opts.keys()).index(settings.get("bg_id")) if settings.get("bg_id") in bg_opts else 0)
            
            # メイン画像 (アップロード)
            st.caption("メイン画像 (タイムテーブル/グリッド)")
            main_file = st.file_uploader("画像をアップロード", type=['png','jpg','webp'])

        with st.expander("2. テキスト情報", expanded=True):
            # 初期値はプロジェクト情報から
            d_val = settings.get("date_str", proj.event_date or "")
            v_val = settings.get("venue_str", proj.venue_name or "")
            o_val = settings.get("open_time", proj.open_time or "")
            s_val = settings.get("start_time", proj.start_time or "")
            
            date_str = st.text_input("開催日表記", value=d_val)
            venue_str = st.text_input("会場表記", value=v_val)
            c1, c2 = st.columns(2)
            with c1: open_time = st.text_input("OPEN", value=o_val)
            with c2: start_time = st.text_input("START", value=s_val)
            
            ticket_info = st.text_area("チケット情報", value=settings.get("ticket_info", "Sチケット ¥..."), height=100)
            notes = st.text_area("注意事項", value=settings.get("notes", "※ドリンク代別..."), height=80)

        with st.expander("3. デザイン", expanded=False):
            all_fonts = [f for f in os.listdir(FONT_DIR) if f.lower().endswith(".ttf")]
            if not all_fonts: all_fonts = ["keifont.ttf"]
            f_idx = all_fonts.index(settings.get("font", all_fonts[0])) if settings.get("font") in all_fonts else 0
            
            selected_font = st.selectbox("フォント", all_fonts, index=f_idx)
            text_color = st.color_picker("文字色", settings.get("text_color", "#FFFFFF"))
            stroke_color = st.color_picker("縁取り色", settings.get("stroke_color", "#000000"))

        if st.button("💾 設定を保存 & プレビュー更新", type="primary"):
            # 設定保存
            new_settings = {
                "logo_id": sel_logo_id, "bg_id": sel_bg_id,
                "date_str": date_str, "venue_str": venue_str,
                "open_time": open_time, "start_time": start_time,
                "ticket_info": ticket_info, "notes": notes,
                "font": selected_font, "text_color": text_color, "stroke_color": stroke_color
            }
            proj.flyer_json = json.dumps(new_settings, ensure_ascii=False)
            db.commit()
            st.session_state.flyer_main_image = main_file # 画像は一時保持
            st.success("保存しました")
            st.rerun()

    with c_prev:
        st.markdown("##### プレビュー")
        # 描画処理
        bg_asset = db.query(Asset).filter(Asset.id == sel_bg_id).first()
        logo_asset = db.query(Asset).filter(Asset.id == sel_logo_id).first()
        
        main_img_bytes = main_file if main_file else st.session_state.get("flyer_main_image")

        if bg_asset and logo_asset and main_img_bytes:
            bg_path = get_image_url(bg_asset.image_filename)
            logo_path = get_image_url(logo_asset.image_filename)
            
            if bg_path and logo_path:
                try:
                    font_path = os.path.join(FONT_DIR, selected_font)
                    img = create_flyer_image(
                        bg_path, logo_path, main_img_bytes,
                        date_str, venue_str, open_time, start_time,
                        ticket_info, notes, font_path, text_color, stroke_color
                    )
                    st.image(img, use_container_width=True)
                    
                    buf = io.BytesIO()
                    img.save(buf, format="PNG")
                    st.download_button("画像をダウンロード", buf.getvalue(), "flyer.png", "image/png", type="primary")
                except Exception as e:
                    st.error(f"生成エラー: {e}")
        else:
            st.info("👈 設定を保存するか、メイン画像をアップロードしてください")
    
    db.close()
