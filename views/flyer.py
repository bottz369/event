import streamlit as st
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageFilter
import io
import os
import requests
import json
import zipfile
from datetime import datetime, date
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm

from constants import FONT_DIR
from database import get_db, TimetableProject, Asset, get_image_url, SystemFontConfig
from utils import get_sorted_font_list, create_font_specimen_img

# ==========================================
# 1. ヘルパー関数群
# ==========================================

def load_image_from_source(source):
    if source is None: return None
    try:
        if isinstance(source, Image.Image): return source.convert("RGBA")
        if isinstance(source, str):
            if source.startswith("http"):
                response = requests.get(source, timeout=10)
                response.raise_for_status()
                return Image.open(io.BytesIO(response.content)).convert("RGBA")
            else:
                return Image.open(source).convert("RGBA")
        return Image.open(source).convert("RGBA")
    except Exception as e:
        print(f"Image Load Error: {e}")
        return None

def ensure_font_file_exists(db, filename):
    """
    指定されたフォントファイルがローカル(FONT_DIR)にあるか確認し、
    なければDB(Asset)からURLを取得してダウンロードする。
    """
    if not filename: return None
    local_path = os.path.join(FONT_DIR, filename)
    if os.path.exists(local_path):
        return local_path
    asset = db.query(Asset).filter(Asset.image_filename == filename).first()
    if asset:
        url = get_image_url(asset.image_filename)
        if url:
            try:
                response = requests.get(url, timeout=10)
                if response.status_code == 200:
                    with open(local_path, "wb") as f:
                        f.write(response.content)
                    return local_path
            except Exception as e:
                print(f"Font download error: {e}")
    return None

def crop_center_to_a4(img):
    if not img: return None
    A4_RATIO = 1.4142
    img_w, img_h = img.size
    current_ratio = img_h / img_w
    if current_ratio > A4_RATIO:
        new_h = int(img_w * A4_RATIO)
        top = (img_h - new_h) // 2
        img = img.crop((0, top, img_w, top + new_h))
    else:
        new_w = int(img_h / A4_RATIO)
        left = (img_w - new_w) // 2
        img = img.crop((left, 0, left + new_w, img_h))
    return img

def resize_image_contain(img, max_w, max_h):
    if not img: return None
    ratio = min(max_w / img.width, max_h / img.height)
    new_w = int(img.width * ratio)
    new_h = int(img.height * ratio)
    return img.resize((new_w, new_h), Image.LANCZOS)

def format_event_date(dt_obj, mode="EN"):
    if not dt_obj: return ""
    target_date = dt_obj
    if isinstance(dt_obj, str):
        try:
            for fmt in ["%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"]:
                try:
                    target_date = datetime.strptime(dt_obj, fmt).date()
                    break
                except ValueError:
                    continue
        except:
            return str(dt_obj)
    try:
        if mode == "JP":
            weekdays_jp = ["月", "火", "水", "木", "金", "土", "日"]
            wd = weekdays_jp[target_date.weekday()]
            return f"{target_date.year}年{target_date.month}月{target_date.day}日 ({wd})"
        else:
            weekdays_en = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
            wd = weekdays_en[target_date.weekday()]
            return f"{target_date.year}.{target_date.month}.{target_date.day}.{wd}"
    except Exception:
        return str(dt_obj)

def format_time_str(t_val):
    if not t_val or t_val == 0 or t_val == "0": return ""
    if isinstance(t_val, str): return t_val[:5]
    try: return t_val.strftime("%H:%M")
    except: return str(t_val)

# --- ★フォント描画ロジック ---

def is_glyph_available(font, char):
    if char.isspace() or ord(char) < 32: return True
    try:
        mask = font.getmask(char)
        if mask.size[0] == 0 or mask.size[1] == 0:
            return False
        return True
    except:
        return True 

def draw_text_mixed(draw, xy, text, primary_font, fallback_font, fill):
    x, y = xy
    total_w = 0
    max_h = 0
    current_x = x
    for char in text:
        use_font = primary_font
        if not is_glyph_available(primary_font, char):
            if fallback_font:
                use_font = fallback_font
        bbox = draw.textbbox((0, 0), char, font=use_font)
        char_w = bbox[2] - bbox[0]
        char_h = bbox[3] - bbox[1] 
        draw.text((current_x, y), char, font=use_font, fill=fill)
        try:
            advance = use_font.getlength(char)
        except:
            advance = char_w
        current_x += advance
        total_w += advance
        if char_h > max_h:
            max_h = char_h
    return total_w, max_h

def draw_text_with_shadow(base_img, text, x, y, font, font_size_px, max_width, fill_color, 
                          anchor="la", 
                          shadow_on=False, shadow_color="#000000", shadow_blur=0, shadow_off_x=5, shadow_off_y=5,
                          fallback_font_path=None):
    if not text: return 0
    fallback_font = None
    if fallback_font_path and os.path.exists(fallback_font_path):
        try:
            fallback_font = ImageFont.truetype(fallback_font_path, int(font_size_px))
        except:
            fallback_font = font
    else:
        fallback_font = font

    # 計測
    dummy_img = Image.new("RGBA", (1, 1))
    dummy_draw = ImageDraw.Draw(dummy_img)
    text_w, text_h = draw_text_mixed(dummy_draw, (0, 0), text, font, fallback_font, fill_color)
    
    margin = int(max(shadow_blur * 3, abs(shadow_off_x), abs(shadow_off_y)) + 20)
    canvas_w = int(text_w + margin * 2)
    canvas_h = int(text_h + margin * 2 + font_size_px * 0.5) 
    
    txt_img = Image.new("RGBA", (canvas_w, canvas_h), (0,0,0,0))
    txt_draw = ImageDraw.Draw(txt_img)
    
    draw_x = margin
    draw_y = margin
    
    draw_text_mixed(txt_draw, (draw_x, draw_y), text, font, fallback_font, fill_color)
    
    final_layer = Image.new("RGBA", (canvas_w, canvas_h), (0,0,0,0))
    if shadow_on:
        alpha = txt_img.getchannel("A")
        shadow_solid = Image.new("RGBA", (canvas_w, canvas_h), shadow_color)
        shadow_solid.putalpha(alpha)
        if shadow_blur > 0:
            shadow_solid = shadow_solid.filter(ImageFilter.GaussianBlur(shadow_blur))
        final_layer.paste(shadow_solid, (shadow_off_x, shadow_off_y), shadow_solid)
        
    final_layer.paste(txt_img, (0, 0), txt_img)
    
    content_w = canvas_w
    content_h = canvas_h
    effective_text_w = text_w
    
    if effective_text_w > max_width:
        ratio = max_width / effective_text_w
        new_w = int(content_w * ratio)
        final_layer = final_layer.resize((new_w, content_h), Image.LANCZOS)
        content_w = new_w
    
    paste_x = x - int(margin * (content_w / canvas_w))
    paste_y = y - margin
    
    if anchor == "ra":
        paste_x = x - content_w + int(margin * (content_w / canvas_w))
    elif anchor == "ma":
        paste_x = x - (content_w // 2)

    base_img.paste(final_layer, (int(paste_x), int(paste_y)), final_layer)
    return text_h

# --- ★カスタム時間描画 (三角形対応) ---
def draw_time_row(base_img, label, time_str, x, y, font, font_size_px, max_width, fill_color,
                  shadow_on, shadow_color, shadow_blur, shadow_off_x, shadow_off_y, fallback_font_path,
                  tri_visible=True, tri_scale=1.0, tri_color=None):
    
    # フォント準備
    fallback_font = font
    if fallback_font_path and os.path.exists(fallback_font_path):
        try: fallback_font = ImageFont.truetype(fallback_font_path, int(font_size_px))
        except: pass

    # コンポーネント計測
    dummy = ImageDraw.Draw(Image.new("RGBA", (1,1)))
    
    # 1. Label (OPEN/START)
    w_label, h_label = draw_text_mixed(dummy, (0,0), label, font, fallback_font, fill_color)
    
    # 2. Time
    w_time, h_time = draw_text_mixed(dummy, (0,0), time_str, font, fallback_font, fill_color)
    
    # 3. Triangle
    tri_h = font_size_px * 0.6 * tri_scale
    tri_w = tri_h * 0.8
    tri_padding = font_size_px * 0.3
    
    total_w_content = w_label + w_time
    if tri_visible:
        total_w_content += tri_w + (tri_padding * 2)
    else:
        total_w_content += tri_padding # 三角形なしでも少し隙間
        
    # キャンバス準備
    margin = int(max(shadow_blur * 3, abs(shadow_off_x), abs(shadow_off_y)) + 20)
    canvas_w = int(total_w_content + margin * 2)
    canvas_h = int(max(h_label, h_time, tri_h) + margin * 2 + font_size_px * 0.5)
    
    txt_img = Image.new("RGBA", (canvas_w, canvas_h), (0,0,0,0))
    draw = ImageDraw.Draw(txt_img)
    
    # 描画開始位置
    cur_x = margin
    draw_y = margin
    
    # Draw Label
    draw_text_mixed(draw, (cur_x, draw_y), label, font, fallback_font, fill_color)
    cur_x += w_label
    
    # Draw Triangle
    if tri_visible:
        cur_x += tri_padding
        # 三角形の座標 (右向き)
        # 上下中央揃え
        cy = draw_y + (font_size_px * 0.5) # フォントサイズの半分くらいを仮の中心に
        # 実際には文字の高さの中心を取りたいが、簡易的に
        ty = cy - (tri_h / 2)
        by = cy + (tri_h / 2)
        lx = cur_x
        rx = cur_x + tri_w
        
        # 三角形描画
        t_col = tri_color if tri_color else fill_color
        draw.polygon([(lx, ty), (lx, by), (rx, cy)], fill=t_col)
        
        cur_x += tri_w + tri_padding
    else:
        cur_x += tri_padding

    # Draw Time
    draw_text_mixed(draw, (cur_x, draw_y), time_str, font, fallback_font, fill_color)
    
    # --- 影と統合 ---
    final_layer = Image.new("RGBA", (canvas_w, canvas_h), (0,0,0,0))
    if shadow_on:
        alpha = txt_img.getchannel("A")
        shadow_solid = Image.new("RGBA", (canvas_w, canvas_h), shadow_color)
        shadow_solid.putalpha(alpha)
        if shadow_blur > 0:
            shadow_solid = shadow_solid.filter(ImageFilter.GaussianBlur(shadow_blur))
        final_layer.paste(shadow_solid, (shadow_off_x, shadow_off_y), shadow_solid)
        
    final_layer.paste(txt_img, (0, 0), txt_img)
    
    # 配置計算 (右寄せ前提)
    paste_x = x - canvas_w + margin # Right Align
    paste_y = y - margin
    
    base_img.paste(final_layer, (int(paste_x), int(paste_y)), final_layer)
    return max(h_label, h_time)

# ==========================================
# 2. UI コンポーネント
# ==========================================

def render_visual_selector(label, assets, key_prefix, current_id, allow_none=False):
    st.markdown(f"**{label}**")
    if allow_none:
        is_none = (not current_id or current_id == 0)
        if st.button(f"🚫 {label}なし", key=f"btn_none_{key_prefix}", type="primary" if is_none else "secondary"):
            st.session_state[key_prefix] = 0
            st.rerun()

    if not assets:
        st.info("画像が見つかりません。")
        return

    cols = st.columns(4)
    for i, asset in enumerate(assets):
        with cols[i % 4]:
            img_url = get_image_url(asset.image_filename)
            st.image(img_url, use_container_width=True) 
            is_sel = (asset.id == current_id)
            if st.button("選択", key=f"btn_{key_prefix}_{asset.id}", type="primary" if is_sel else "secondary", use_container_width=True):
                st.session_state[key_prefix] = asset.id
                st.rerun()

# ==========================================
# 3. フライヤー生成ロジック
# ==========================================

def create_flyer_image_shadow(
    db, bg_source, logo_source, main_source,
    styles,
    date_text, venue_text, open_time, start_time,
    ticket_info_list, common_notes_list,
    system_fallback_filename=None
):
    # フォント準備
    for k in ["date", "venue", "time", "ticket_name", "ticket_note"]:
        fname = styles.get(f"{k}_font", "keifont.ttf")
        ensure_font_file_exists(db, fname)
    
    fallback_font_path = None
    if system_fallback_filename:
        fallback_font_path = ensure_font_file_exists(db, system_fallback_filename)

    # 背景
    raw_bg = load_image_from_source(bg_source)
    if raw_bg is None:
        W, H = 2480, 3508
        base_img = Image.new("RGBA", (W, H), (20, 20, 30, 255))
    else:
        base_img = crop_center_to_a4(raw_bg)
        if base_img.width < 1200:
            scale = 1200 / base_img.width
            base_img = base_img.resize((1200, int(base_img.height * scale)), Image.LANCZOS)
    
    W, H = base_img.size
    
    # スタイル取得
    def get_style(key, default_size=50, default_color="#FFFFFF"):
        f_name = styles.get(f"{key}_font", "keifont.ttf")
        f_size_val = styles.get(f"{key}_size", default_size)
        scale_factor = W / 1200.0
        final_size_px = int(f_size_val * scale_factor)
        
        path = os.path.join(FONT_DIR, f_name)
        try: font = ImageFont.truetype(path, final_size_px)
        except: font = ImageFont.load_default()
        
        return {
            "font": font, "size": final_size_px,
            "color": styles.get(f"{key}_color", default_color),
            "shadow_on": styles.get(f"{key}_shadow_on", False),
            "shadow_color": styles.get(f"{key}_shadow_color", "#000000"),
            "shadow_blur": styles.get(f"{key}_shadow_blur", 0),
            "shadow_off_x": int(styles.get(f"{key}_shadow_off_x", 5) * scale_factor),
            "shadow_off_y": int(styles.get(f"{key}_shadow_off_y", 5) * scale_factor),
            "pos_x": int(styles.get(f"{key}_pos_x", 0) * scale_factor), # 追加
            "pos_y": int(styles.get(f"{key}_pos_y", 0) * scale_factor)  # 追加
        }

    s_date = get_style("date", 90)
    s_venue = get_style("venue", 50)
    s_time = get_style("time", 60) 
    s_ticket = get_style("ticket_name", 45)
    s_note = get_style("ticket_note", 30)

    padding_x = int(W * 0.05)
    current_y = int(H * 0.03)

    # A. ロゴ
    logo_img = load_image_from_source(logo_source)
    if logo_img:
        logo_scale = styles.get("logo_scale", 1.0)
        logo_pos_x = styles.get("logo_pos_x", 0)
        logo_pos_y = styles.get("logo_pos_y", 0)
        base_logo_w = int(W * 0.5 * logo_scale)
        logo_img = resize_image_to_width(logo_img, base_logo_w)
        base_x = (W - logo_img.width) // 2
        base_y = current_y
        offset_x = int(W * (logo_pos_x / 100.0))
        offset_y = int(H * (logo_pos_y / 100.0))
        base_img.paste(logo_img, (base_x + offset_x, base_y + offset_y), logo_img)
        current_y = base_y + offset_y + logo_img.height

    header_y = current_y + int(H * 0.02)
    
    # B. Header info
    left_x = padding_x
    right_x = W - padding_x
    left_max_w = int(W * 0.55)
    right_max_w = int(W * 0.35)

    # 左側 (日付・会場)
    h_date = draw_text_with_shadow(
        base_img, str(date_text), left_x + s_date["pos_x"], header_y + s_date["pos_y"], 
        s_date["font"], s_date["size"], left_max_w, s_date["color"], "la",
        s_date["shadow_on"], s_date["shadow_color"], s_date["shadow_blur"], s_date["shadow_off_x"], s_date["shadow_off_y"],
        fallback_font_path=fallback_font_path
    )
    
    date_venue_gap_px = int(styles.get("date_venue_gap", 10) * (W / 1200.0))
    venue_y = header_y + h_date + date_venue_gap_px
    
    h_venue = draw_text_with_shadow(
        base_img, str(venue_text), left_x + s_venue["pos_x"], venue_y + s_venue["pos_y"], 
        s_venue["font"], s_venue["size"], left_max_w, s_venue["color"], "la",
        s_venue["shadow_on"], s_venue["shadow_color"], s_venue["shadow_blur"], s_venue["shadow_off_x"], s_venue["shadow_off_y"],
        fallback_font_path=fallback_font_path
    )
    
    # 右側 (時間)
    o_str = str(open_time) if open_time else "TBA"
    s_str = str(start_time) if start_time else "TBA"
    
    # 時間設定取得
    line_h_time = s_time["size"] * 1.3 
    time_line_gap = int(styles.get("time_line_gap", 0) * (W / 1200.0)) # 追加: 行間設定
    
    tri_vis = styles.get("time_tri_visible", True)
    tri_scale = styles.get("time_tri_scale", 1.0)
    
    # OPEN
    draw_time_row(
        base_img, "OPEN", o_str, right_x + s_time["pos_x"], header_y + s_time["pos_y"],
        s_time["font"], s_time["size"], right_max_w, s_time["color"],
        s_time["shadow_on"], s_time["shadow_color"], s_time["shadow_blur"], s_time["shadow_off_x"], s_time["shadow_off_y"],
        fallback_font_path,
        tri_visible=tri_vis, tri_scale=tri_scale
    )
    
    # START
    start_y = header_y + line_h_time + time_line_gap
    draw_time_row(
        base_img, "START", s_str, right_x + s_time["pos_x"], start_y + s_time["pos_y"],
        s_time["font"], s_time["size"], right_max_w, s_time["color"],
        s_time["shadow_on"], s_time["shadow_color"], s_time["shadow_blur"], s_time["shadow_off_x"], s_time["shadow_off_y"],
        fallback_font_path,
        tri_visible=tri_vis, tri_scale=tri_scale
    )
    
    right_bottom_y = start_y + line_h_time
    header_bottom = max(venue_y + h_venue, right_bottom_y) + int(H * 0.02)

    # C. Footer
    footer_lines = []
    
    note_gap_px = int(styles.get("note_gap", 15) * (W / 1200.0))
    ticket_gap_px = int(styles.get("ticket_gap", 20) * (W / 1200.0))
    area_gap_px = int(styles.get("area_gap", 40) * (W / 1200.0))

    # Notes
    for note in reversed(common_notes_list):
        if note and str(note).strip():
            footer_lines.append({"text": str(note).strip(), "style": s_note, "gap": note_gap_px})
    
    # Tickets
    is_first_ticket = True
    for ticket in reversed(ticket_info_list):
        name = ticket.get('name', '')
        price = ticket.get('price', '')
        t_note = ticket.get('note', '')
        main_txt = f"{name} {price}"
        if t_note: main_txt += f" ({t_note})"
        
        current_gap = ticket_gap_px
        if is_first_ticket and footer_lines:
            current_gap += area_gap_px
            is_first_ticket = False
            
        footer_lines.append({"text": main_txt, "style": s_ticket, "gap": current_gap})

    footer_h = int(H * 0.05)
    processed_footer = []
    for item in footer_lines:
        dummy_draw = ImageDraw.Draw(Image.new("RGBA",(1,1)))
        bbox = dummy_draw.textbbox((0,0), item["text"], font=item["style"]["font"])
        h = bbox[3] - bbox[1]
        processed_footer.append({**item, "h": h})
        footer_h += h + item["gap"]

    footer_start_y = H - footer_h
    curr_fy = footer_start_y
    for item in reversed(processed_footer):
        st_obj = item["style"]
        draw_text_with_shadow(
            base_img, item["text"], W//2 + st_obj["pos_x"], curr_fy + st_obj["pos_y"], 
            st_obj["font"], st_obj["size"], int(W*0.9), st_obj["color"], "ma",
            st_obj["shadow_on"], st_obj["shadow_color"], st_obj["shadow_blur"], st_obj["shadow_off_x"], st_obj["shadow_off_y"],
            fallback_font_path=fallback_font_path
        )
        curr_fy += item["h"] + item["gap"]

    # D. Main Image
    available_top = header_bottom
    available_bottom = footer_start_y - int(H * 0.02)
    available_h = available_bottom - available_top
    
    main_img = load_image_from_source(main_source)
    if main_img and available_h > 100:
        scale_w = styles.get("content_scale_w", 95) / 100.0
        scale_h = styles.get("content_scale_h", 100) / 100.0
        target_w = int(W * scale_w)
        target_h = int(available_h * scale_h)
        
        main_resized = resize_image_contain(main_img, target_w, target_h)
        if main_resized:
            paste_x = (W - main_resized.width) // 2
            paste_y = available_top + (available_h - main_resized.height) // 2
            base_img.paste(main_resized, (paste_x, int(paste_y)), main_resized)

    return base_img

# ==========================================
# 4. メイン画面描画
# ==========================================

def render_flyer_editor(project_id):
    db = next(get_db())
    proj = db.query(TimetableProject).filter(TimetableProject.id == project_id).first()
    
    logos = db.query(Asset).filter(Asset.asset_type == "logo", Asset.is_deleted == False).all()
    bgs = db.query(Asset).filter(Asset.asset_type == "background", Asset.is_deleted == False).all()
    
    font_list_data = get_sorted_font_list(db)
    font_options = [f["filename"] for f in font_list_data]
    font_map = {f["filename"]: f["name"] for f in font_list_data}
    if not font_options: font_options = ["keifont.ttf"]

    if not proj:
        st.error("プロジェクトエラー")
        return

    st.subheader("📑 フライヤー生成 (Custom V4)")

    saved_config = {}
    if getattr(proj, "flyer_json", None):
        try: saved_config = json.loads(proj.flyer_json)
        except: pass

    # Session State
    if "flyer_bg_id" not in st.session_state: st.session_state.flyer_bg_id = int(saved_config.get("bg_id", 0))
    if "flyer_logo_id" not in st.session_state: st.session_state.flyer_logo_id = int(saved_config.get("logo_id", 0))
    if "flyer_date_format" not in st.session_state: st.session_state.flyer_date_format = saved_config.get("date_format", "EN")
    
    if "flyer_logo_scale" not in st.session_state: st.session_state.flyer_logo_scale = saved_config.get("logo_scale", 1.0)
    if "flyer_logo_pos_x" not in st.session_state: st.session_state.flyer_logo_pos_x = saved_config.get("logo_pos_x", 0.0)
    if "flyer_logo_pos_y" not in st.session_state: st.session_state.flyer_logo_pos_y = saved_config.get("logo_pos_y", 0.0)

    # Resize & Gap Config
    if "flyer_content_scale_w" not in st.session_state: st.session_state.flyer_content_scale_w = saved_config.get("content_scale_w", 95)
    if "flyer_content_scale_h" not in st.session_state: st.session_state.flyer_content_scale_h = saved_config.get("content_scale_h", 100)
    
    if "flyer_date_venue_gap" not in st.session_state: st.session_state.flyer_date_venue_gap = saved_config.get("date_venue_gap", 10)
    if "flyer_ticket_gap" not in st.session_state: st.session_state.flyer_ticket_gap = saved_config.get("ticket_gap", 20)
    if "flyer_area_gap" not in st.session_state: st.session_state.flyer_area_gap = saved_config.get("area_gap", 40)
    if "flyer_note_gap" not in st.session_state: st.session_state.flyer_note_gap = saved_config.get("note_gap", 15)
    
    # Time settings
    if "flyer_time_tri_visible" not in st.session_state: st.session_state.flyer_time_tri_visible = saved_config.get("time_tri_visible", True)
    if "flyer_time_tri_scale" not in st.session_state: st.session_state.flyer_time_tri_scale = saved_config.get("time_tri_scale", 1.0)
    if "flyer_time_line_gap" not in st.session_state: st.session_state.flyer_time_line_gap = saved_config.get("time_line_gap", 0)

    # Fallback
    if "flyer_fallback_font" not in st.session_state:
        sys_conf = db.query(SystemFontConfig).first()
        def_sys = sys_conf.filename if sys_conf else "keifont.ttf"
        st.session_state.flyer_fallback_font = saved_config.get("fallback_font", def_sys)

    def render_style_editor_full(label, key_prefix):
        def_font = "keifont.ttf"
        def_size = 50
        def_color = "#FFFFFF"
        
        # Init states
        if f"flyer_{key_prefix}_font" not in st.session_state: st.session_state[f"flyer_{key_prefix}_font"] = saved_config.get(f"{key_prefix}_font", def_font)
        if f"flyer_{key_prefix}_size" not in st.session_state: st.session_state[f"flyer_{key_prefix}_size"] = saved_config.get(f"{key_prefix}_size", def_size)
        if f"flyer_{key_prefix}_color" not in st.session_state: st.session_state[f"flyer_{key_prefix}_color"] = saved_config.get(f"{key_prefix}_color", def_color)
        if f"flyer_{key_prefix}_shadow_on" not in st.session_state: st.session_state[f"flyer_{key_prefix}_shadow_on"] = saved_config.get(f"{key_prefix}_shadow_on", False)
        if f"flyer_{key_prefix}_shadow_color" not in st.session_state: st.session_state[f"flyer_{key_prefix}_shadow_color"] = saved_config.get(f"{key_prefix}_shadow_color", "#000000")
        if f"flyer_{key_prefix}_shadow_blur" not in st.session_state: st.session_state[f"flyer_{key_prefix}_shadow_blur"] = saved_config.get(f"{key_prefix}_shadow_blur", 2)
        if f"flyer_{key_prefix}_shadow_off_x" not in st.session_state: st.session_state[f"flyer_{key_prefix}_shadow_off_x"] = saved_config.get(f"{key_prefix}_shadow_off_x", 5)
        if f"flyer_{key_prefix}_shadow_off_y" not in st.session_state: st.session_state[f"flyer_{key_prefix}_shadow_off_y"] = saved_config.get(f"{key_prefix}_shadow_off_y", 5)
        
        # Position adjustments
        if f"flyer_{key_prefix}_pos_x" not in st.session_state: st.session_state[f"flyer_{key_prefix}_pos_x"] = saved_config.get(f"{key_prefix}_pos_x", 0)
        if f"flyer_{key_prefix}_pos_y" not in st.session_state: st.session_state[f"flyer_{key_prefix}_pos_y"] = saved_config.get(f"{key_prefix}_pos_y", 0)

        with st.expander(f"📝 {label} スタイル", expanded=False):
            c1, c2 = st.columns([2, 1])
            with c1:
                st.selectbox("フォント", font_options, key=f"flyer_{key_prefix}_font", format_func=lambda x: font_map.get(x, x))
            with c2:
                st.color_picker("文字色", key=f"flyer_{key_prefix}_color")
            st.slider("サイズ", 10, 200, step=5, key=f"flyer_{key_prefix}_size")
            
            st.markdown("**配置微調整**")
            cp1, cp2 = st.columns(2)
            with cp1: st.number_input("X移動 (横)", -500, 500, step=5, key=f"flyer_{key_prefix}_pos_x")
            with cp2: st.number_input("Y移動 (縦)", -500, 500, step=5, key=f"flyer_{key_prefix}_pos_y")

            st.markdown("---")
            sc1, sc2 = st.columns([1, 2])
            with sc1:
                st.checkbox("影をつける", key=f"flyer_{key_prefix}_shadow_on")
                if st.session_state[f"flyer_{key_prefix}_shadow_on"]:
                    st.color_picker("影の色", key=f"flyer_{key_prefix}_shadow_color")
            with sc2:
                if st.session_state[f"flyer_{key_prefix}_shadow_on"]:
                    st.slider("ぼかし", 0, 20, step=1, key=f"flyer_{key_prefix}_shadow_blur")
                    c1, c2 = st.columns(2)
                    with c1: st.number_input("影X", -50, 50, key=f"flyer_{key_prefix}_shadow_off_x")
                    with c2: st.number_input("影Y", -50, 50, key=f"flyer_{key_prefix}_shadow_off_y")
            
            # 時間専用設定
            if key_prefix == "time":
                st.markdown("---")
                st.markdown("**時間表示オプション**")
                st.checkbox("三角形(▶)を表示", key="flyer_time_tri_visible")
                if st.session_state.flyer_time_tri_visible:
                    st.slider("三角形サイズ", 0.1, 2.0, step=0.1, key="flyer_time_tri_scale")
                st.slider("OPEN/STARTの行間", 0, 100, step=1, key="flyer_time_line_gap")

    c_conf, c_prev = st.columns([1, 1.2])

    with c_conf:
        with st.expander("🖼️ 基本設定", expanded=True):
            render_visual_selector("背景画像", bgs, "flyer_bg_id", st.session_state.flyer_bg_id)
            st.markdown("---")
            render_visual_selector("ロゴ画像", logos, "flyer_logo_id", st.session_state.flyer_logo_id, allow_none=True)
            if st.session_state.flyer_logo_id:
                st.markdown("**ロゴ微調整**")
                c_l1, c_l2, c_l3 = st.columns(3)
                with c_l1: st.slider("サイズ", 0.1, 2.0, step=0.1, key="flyer_logo_scale")
                with c_l2: st.slider("X位置", -100.0, 100.0, step=1.0, key="flyer_logo_pos_x")
                with c_l3: st.slider("Y位置", -100.0, 100.0, step=1.0, key="flyer_logo_pos_y")
            
            st.markdown("---")
            date_opts = ["EN (例: 2025.2.15.SUN)", "JP (例: 2025年2月15日 (日))"]
            if "flyer_date_format_radio" not in st.session_state:
                if st.session_state.flyer_date_format == "EN":
                    st.session_state.flyer_date_format_radio = date_opts[0]
                else:
                    st.session_state.flyer_date_format_radio = date_opts[1]
            st.radio("📅 日付表示形式", date_opts, key="flyer_date_format_radio")
            st.session_state.flyer_date_format = "EN" if st.session_state.flyer_date_format_radio.startswith("EN") else "JP"
            
            st.markdown("---")
            st.selectbox("🇯🇵 日本語用フォント (補助)", font_options, 
                         key="flyer_fallback_font", 
                         format_func=lambda x: font_map.get(x, x),
                         help="英字フォントで日本語が表示できない場合に、このフォントを使用します。")

        with st.expander("🔤 フォント一覧見本を表示"):
            with st.container(height=300):
                specimen_img = create_font_specimen_img(db, font_list_data)
                if specimen_img: st.image(specimen_img, use_container_width=True)
                else: st.info("フォントが見つかりません")

        with st.expander("📐 コンテンツ・余白調整", expanded=False):
            st.markdown("**メイン画像サイズ**")
            c1, c2 = st.columns(2)
            with c1: st.slider("横幅 (%)", 50, 100, step=1, key="flyer_content_scale_w")
            with c2: st.slider("高さ (%)", 50, 100, step=1, key="flyer_content_scale_h")
            
            st.markdown("---")
            st.markdown("**間隔設定**")
            st.slider("日付と会場の間隔", 0, 100, step=1, key="flyer_date_venue_gap")
            st.slider("チケット行間", 0, 100, step=1, key="flyer_ticket_gap")
            st.slider("チケットエリアと備考エリアの行間", 0, 200, step=5, key="flyer_area_gap")
            st.slider("備考行間", 0, 100, step=1, key="flyer_note_gap")

        st.markdown("#### 🎨 各要素のスタイル")
        render_style_editor_full("日付 (DATE)", "date")
        render_style_editor_full("会場名 (VENUE)", "venue")
        render_style_editor_full("時間 (OPEN/START)", "time")
        render_style_editor_full("チケット情報 (List)", "ticket_name")
        render_style_editor_full("チケット共通備考 (Notes)", "ticket_note")

        if st.button("💾 設定を保存", use_container_width=True):
            save_data = {
                "bg_id": st.session_state.flyer_bg_id,
                "logo_id": st.session_state.flyer_logo_id,
                "date_format": st.session_state.flyer_date_format,
                "logo_scale": st.session_state.flyer_logo_scale,
                "logo_pos_x": st.session_state.flyer_logo_pos_x,
                "logo_pos_y": st.session_state.flyer_logo_pos_y,
                "content_scale_w": st.session_state.flyer_content_scale_w,
                "content_scale_h": st.session_state.flyer_content_scale_h,
                "date_venue_gap": st.session_state.flyer_date_venue_gap,
                "ticket_gap": st.session_state.flyer_ticket_gap,
                "area_gap": st.session_state.flyer_area_gap,
                "note_gap": st.session_state.flyer_note_gap,
                "fallback_font": st.session_state.flyer_fallback_font,
                "time_tri_visible": st.session_state.flyer_time_tri_visible,
                "time_tri_scale": st.session_state.flyer_time_tri_scale,
                "time_line_gap": st.session_state.flyer_time_line_gap
            }
            target_keys = ["date", "venue", "time", "ticket_name", "ticket_note"]
            style_params = ["font", "size", "color", "shadow_on", "shadow_color", "shadow_blur", "shadow_off_x", "shadow_off_y", "pos_x", "pos_y"]
            for k in target_keys:
                for p in style_params:
                    val = st.session_state.get(f"flyer_{k}_{p}")
                    save_data[f"{k}_{p}"] = val

            if hasattr(proj, "flyer_json"):
                proj.flyer_json = json.dumps(save_data)
                db.commit()
                st.success("設定を保存しました")

    with c_prev:
        st.markdown("### 🚀 生成プレビュー")
        if st.button("画像を生成する", type="primary", use_container_width=True):
            bg_url = None
            if st.session_state.flyer_bg_id:
                asset = db.query(Asset).get(st.session_state.flyer_bg_id)
                if asset: bg_url = get_image_url(asset.image_filename)
            
            logo_url = None
            if st.session_state.flyer_logo_id:
                asset = db.query(Asset).get(st.session_state.flyer_logo_id)
                if asset: logo_url = get_image_url(asset.image_filename)

            style_dict = {
                "logo_scale": st.session_state.flyer_logo_scale,
                "logo_pos_x": st.session_state.flyer_logo_pos_x,
                "logo_pos_y": st.session_state.flyer_logo_pos_y,
                "content_scale_w": st.session_state.flyer_content_scale_w,
                "content_scale_h": st.session_state.flyer_content_scale_h,
                "date_venue_gap": st.session_state.flyer_date_venue_gap,
                "ticket_gap": st.session_state.flyer_ticket_gap,
                "area_gap": st.session_state.flyer_area_gap,
                "note_gap": st.session_state.flyer_note_gap,
                "time_tri_visible": st.session_state.flyer_time_tri_visible,
                "time_tri_scale": st.session_state.flyer_time_tri_scale,
                "time_line_gap": st.session_state.flyer_time_line_gap
            }
            target_keys = ["date", "venue", "time", "ticket_name", "ticket_note"]
            style_params = ["font", "size", "color", "shadow_on", "shadow_color", "shadow_blur", "shadow_off_x", "shadow_off_y", "pos_x", "pos_y"]
            for k in target_keys:
                for p in style_params:
                    style_dict[f"{k}_{p}"] = st.session_state.get(f"flyer_{k}_{p}")

            tickets = []
            if getattr(proj, "tickets_json", None):
                try: tickets = json.loads(proj.tickets_json)
                except: pass
            
            notes = []
            if getattr(proj, "ticket_notes_json", None):
                try: notes = json.loads(proj.ticket_notes_json)
                except: pass
            
            v_text = getattr(proj, "venue_name", "") or getattr(proj, "venue", "") or ""
            d_text = format_event_date(proj.event_date, st.session_state.flyer_date_format)

            fallback_filename = st.session_state.get("flyer_fallback_font")

            args = {
                "db": db, 
                "bg_source": bg_url, "logo_source": logo_url, "styles": style_dict,
                "date_text": d_text, "venue_text": v_text,
                "open_time": format_time_str(proj.open_time),
                "start_time": format_time_str(proj.start_time),
                "ticket_info_list": tickets, "common_notes_list": notes,
                "system_fallback_filename": fallback_filename 
            }

            with st.spinner("生成中..."):
                grid_src = st.session_state.get("last_generated_grid_image")
                if grid_src:
                    st.session_state.flyer_result_grid = create_flyer_image_shadow(main_source=grid_src, **args)
                tt_src = st.session_state.get("last_generated_tt_image")
                if tt_src:
                    st.session_state.flyer_result_tt = create_flyer_image_shadow(main_source=tt_src, **args)

        t1, t2, t3 = st.tabs(["アー写グリッド版", "タイムテーブル版", "📥 一括ダウンロード"])
        with t1:
            if st.session_state.get("flyer_result_grid"):
                st.image(st.session_state.flyer_result_grid, use_container_width=True)
            else: st.info("生成ボタンを押してください")
        with t2:
            if st.session_state.get("flyer_result_tt"):
                st.image(st.session_state.flyer_result_tt, use_container_width=True)
            else: st.info("生成ボタンを押してください")
        
        # --- ZIP ダウンロードタブ ---
        with t3:
            st.markdown("生成された画像と素材をまとめてダウンロードします。")
            if st.button("📦 ZIPファイルを生成", type="primary"):
                if not st.session_state.get("flyer_result_grid") or not st.session_state.get("last_generated_grid_image"):
                    st.error("先に画像を生成してください。")
                else:
                    try:
                        zip_buffer = io.BytesIO()
                        with zipfile.ZipFile(zip_buffer, 'w') as zip_file:
                            # 1. Flyer Grid
                            buf = io.BytesIO()
                            st.session_state.flyer_result_grid.save(buf, format="PNG")
                            zip_file.writestr("Flyer_Grid.png", buf.getvalue())
                            
                            # 2. Flyer TT
                            if st.session_state.get("flyer_result_tt"):
                                buf = io.BytesIO()
                                st.session_state.flyer_result_tt.save(buf, format="PNG")
                                zip_file.writestr("Flyer_Timetable.png", buf.getvalue())
                            
                            # 3. Source Grid (Transparent)
                            if st.session_state.get("last_generated_grid_image"):
                                buf = io.BytesIO()
                                st.session_state.last_generated_grid_image.save(buf, format="PNG")
                                zip_file.writestr("Source_Grid_Transparent.png", buf.getvalue())
                            
                            # 4. Source TT (Transparent)
                            if st.session_state.get("last_generated_tt_image"):
                                buf = io.BytesIO()
                                st.session_state.last_generated_tt_image.save(buf, format="PNG")
                                zip_file.writestr("Source_Timetable_Transparent.png", buf.getvalue())
                            
                            # 5. Simple PDFs using ReportLab
                            # Event Outline
                            pdf_buf = io.BytesIO()
                            c = canvas.Canvas(pdf_buf, pagesize=A4)
                            c.setFont("Helvetica-Bold", 16)
                            c.drawString(20*mm, 280*mm, f"Event: {proj.title}")
                            c.setFont("Helvetica", 12)
                            c.drawString(20*mm, 270*mm, f"Date: {format_event_date(proj.event_date)}")
                            c.drawString(20*mm, 260*mm, f"Venue: {proj.venue}")
                            c.save()
                            zip_file.writestr("Event_Outline.pdf", pdf_buf.getvalue())
                            
                            # Timetable PDF (Embed Image)
                            if st.session_state.get("last_generated_tt_image"):
                                pdf_buf = io.BytesIO()
                                c = canvas.Canvas(pdf_buf, pagesize=A4)
                                # Save TT image to temp to draw in PDF
                                tt_img = st.session_state.last_generated_tt_image
                                temp_tt_path = "temp_tt_for_pdf.png"
                                tt_img.save(temp_tt_path)
                                # Draw stretched to A4 width
                                c.drawImage(temp_tt_path, 10*mm, 10*mm, width=190*mm, preserveAspectRatio=True)
                                c.save()
                                zip_file.writestr("Timetable.pdf", pdf_buf.getvalue())
                                try: os.remove(temp_tt_path)
                                except: pass

                        st.download_button(
                            label="⬇️ ZIPをダウンロード",
                            data=zip_buffer.getvalue(),
                            file_name=f"flyer_assets_{proj.id}.zip",
                            mime="application/zip"
                        )
                    except Exception as e:
                        st.error(f"ZIP生成エラー: {e}")

    db.close()
