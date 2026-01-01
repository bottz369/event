import os
from PIL import Image, ImageDraw, ImageFont

from constants import FONT_DIR
# Step 1, 2で作ったファイルをインポート
from utils.flyer_helpers import (
    load_image_from_source, ensure_font_file_exists, crop_center_to_a4,
    resize_image_contain, resize_image_to_width, format_time_str
)
from utils.flyer_drawing import (
    draw_text_with_shadow, draw_time_row_aligned, draw_text_mixed, contains_japanese
)

def create_flyer_image_shadow(
    db, bg_source, logo_source, main_source,
    styles,
    date_text, venue_text, open_time, start_time,
    ticket_info_list, common_notes_list,
    subtitle_text="", # ★追加: サブタイトル引数
    system_fallback_filename=None
):
    # 1. フォントファイルの存在確認・準備
    # ★追加: "subtitle" もチェック対象に追加
    for k in ["date", "venue", "time", "ticket_name", "ticket_note", "subtitle"]:
        fname = styles.get(f"{k}_font", "keifont.ttf")
        ensure_font_file_exists(db, fname)
    
    # 日本語用補助フォントの準備
    fallback_fname = system_fallback_filename if system_fallback_filename else "keifont.ttf"
    fallback_font_path = ensure_font_file_exists(db, fallback_fname)

    # 2. 背景画像の準備
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
    scale_f = W / 1200.0 # 基準サイズ(1200px)からのスケール係数

    # スタイル取得用内部関数
    def get_style_config(key, default_size=50, default_color="#FFFFFF"):
        f_name = styles.get(f"{key}_font", "keifont.ttf")
        f_size_val = styles.get(f"{key}_size", default_size)
        final_size_px = int(f_size_val * scale_f)
        
        path = os.path.join(FONT_DIR, f_name)
        
        return {
            "font_path": path,
            "size": final_size_px,
            "color": styles.get(f"{key}_color", default_color),
            "shadow_on": styles.get(f"{key}_shadow_on", False),
            "shadow_color": styles.get(f"{key}_shadow_color", "#000000"),
            "shadow_blur": styles.get(f"{key}_shadow_blur", 0),
            "shadow_off_x": int(styles.get(f"{key}_shadow_off_x", 5) * scale_f),
            "shadow_off_y": int(styles.get(f"{key}_shadow_off_y", 5) * scale_f),
            "pos_x": int(styles.get(f"{key}_pos_x", 0) * scale_f),
            "pos_y": int(styles.get(f"{key}_pos_y", 0) * scale_f)
        }

    s_date = get_style_config("date", 90)
    s_venue = get_style_config("venue", 50)
    s_time = get_style_config("time", 60) 
    s_ticket = get_style_config("ticket_name", 45)
    s_note = get_style_config("ticket_note", 30)
    # ★追加: サブタイトル用スタイル
    s_subtitle = get_style_config("subtitle", 40)

    # --------------------------------------------------------------------------------
    # 3. レイアウト計算 (シミュレーション)
    # --------------------------------------------------------------------------------
    
    current_y = int(H * 0.03)
    logo_img_obj = load_image_from_source(logo_source)
    if logo_img_obj:
        logo_w_scaled = int(W * 0.5 * styles.get("logo_scale", 1.0))
        logo_h_scaled = int(logo_img_obj.height * (logo_w_scaled / logo_img_obj.width))
        current_y += logo_h_scaled + int(H * styles.get("logo_pos_y", 0) / 100.0)
    
    # ★追加: サブタイトルの高さ分を計算に含める
    if subtitle_text:
        # 簡易計算 (実際の高さはフォント依存だが、概算でスペース確保)
        sub_h = s_subtitle["size"] * 1.2
        current_y += int(sub_h + s_subtitle["pos_y"])

    header_start_y = current_y + int(H * 0.02)
    current_sim_y = header_start_y
    
    # 日付 (シミュレーション)
    date_str = str(date_text)
    use_font_date = fallback_font_path if contains_japanese(date_str) and fallback_font_path else s_date["font_path"]
    
    h_date_sim = draw_text_with_shadow(
        None, date_str, 0, 0, use_font_date, s_date["size"], int(W*0.55), "#000",
        fallback_font_path=fallback_font_path, measure_only=True
    )
    current_sim_y += h_date_sim + s_date["pos_y"]
    
    # 会場 (シミュレーション)
    current_sim_y += int(styles.get("date_venue_gap", 10) * scale_f)
    venue_str = str(venue_text)
    use_font_venue = fallback_font_path if contains_japanese(venue_str) and fallback_font_path else s_venue["font_path"]
    
    h_venue_sim = draw_text_with_shadow(
        None, venue_str, 0, 0, use_font_venue, s_venue["size"], int(W*0.55), "#000",
        fallback_font_path=fallback_font_path, measure_only=True
    )
    current_sim_y += h_venue_sim + s_venue["pos_y"]
    
    # 時間エリア
    time_line_gap = int(styles.get("time_line_gap", 0) * scale_f)
    h_time_row_sim = int(s_time["size"] * 1.5)
    header_bottom_y = max(current_sim_y, header_start_y + (h_time_row_sim * 2 + time_line_gap) + s_time["pos_y"])
    
    # --------------------------------------------------------------------------------
    # 4. メイン画像 (アー写) の描画
    # --------------------------------------------------------------------------------
    
    available_top = header_bottom_y + int(H * 0.02)
    available_bottom = H - int(H * 0.25)
    available_h = available_bottom - available_top
    
    main_img = load_image_from_source(main_source)
    if main_img and available_h > 100:
        target_w = int(W * styles.get("content_scale_w", 95) / 100.0)
        target_h = int(available_h * styles.get("content_scale_h", 100) / 100.0)
        
        main_resized = resize_image_contain(main_img, target_w, target_h)
        if main_resized:
            paste_x = (W - main_resized.width) // 2
            offset_y = int(styles.get("content_pos_y", 0) * scale_f)
            paste_y = available_top + (available_h - main_resized.height) // 2 + offset_y
            
            base_img.paste(main_resized, (paste_x, int(paste_y)), main_resized)

    # --------------------------------------------------------------------------------
    # 5. テキスト等の描画 (前面レイヤー)
    # --------------------------------------------------------------------------------
    
    # A. ロゴ
    logo_img = load_image_from_source(logo_source)
    current_y = int(H * 0.03)
    if logo_img:
        logo_img = resize_image_to_width(logo_img, int(W * 0.5 * styles.get("logo_scale", 1.0)))
        lx = (W - logo_img.width) // 2 + int(W * styles.get("logo_pos_x", 0) / 100.0)
        ly = int(H * 0.03) + int(H * styles.get("logo_pos_y", 0) / 100.0)
        base_img.paste(logo_img, (lx, ly), logo_img)
        current_y = ly + logo_img.height

    # ★追加: サブタイトル (ロゴの下)
    if subtitle_text:
        sub_str = str(subtitle_text)
        use_font_sub = fallback_font_path if contains_japanese(sub_str) and fallback_font_path else s_subtitle["font_path"]
        
        # ロゴと日付の間隔を考慮して配置 (ロゴのすぐ下)
        sub_y = current_y + s_subtitle["pos_y"]
        
        h_sub = draw_text_with_shadow(
            base_img, sub_str, W//2 + s_subtitle["pos_x"], sub_y, 
            use_font_sub, s_subtitle["size"], int(W*0.9), s_subtitle["color"], 
            anchor="ma", # 中央揃え (Middle Anchor)
            shadow_on=s_subtitle["shadow_on"], 
            shadow_color=s_subtitle["shadow_color"], 
            shadow_blur=s_subtitle["shadow_blur"], 
            shadow_off_x=s_subtitle["shadow_off_x"], 
            shadow_off_y=s_subtitle["shadow_off_y"],
            fallback_font_path=fallback_font_path
        )
        current_y += h_sub

    header_y = current_y + int(H * 0.02)
    padding_x = int(W * 0.05)
    left_x = padding_x
    right_x = W - padding_x
    left_max_w = int(W * 0.55)
    right_max_w = int(W * 0.35)

    # 日付 (描画)
    h_date = draw_text_with_shadow(
        base_img, date_str, left_x + s_date["pos_x"], header_y + s_date["pos_y"], 
        use_font_date, s_date["size"], left_max_w, s_date["color"], "la",
        s_date["shadow_on"], s_date["shadow_color"], s_date["shadow_blur"], s_date["shadow_off_x"], s_date["shadow_off_y"],
        fallback_font_path=fallback_font_path
    )
    
    venue_y = header_y + h_date + int(styles.get("date_venue_gap", 10) * scale_f)
    
    # 会場 (描画)
    draw_text_with_shadow(
        base_img, venue_str, left_x + s_venue["pos_x"], venue_y + s_venue["pos_y"], 
        use_font_venue, s_venue["size"], left_max_w, s_venue["color"], "la",
        s_venue["shadow_on"], s_venue["shadow_color"], s_venue["shadow_blur"], s_venue["shadow_off_x"], s_venue["shadow_off_y"],
        fallback_font_path=fallback_font_path
    )
    
    # 時間 (OPEN/START)
    try:
        t_font_obj = ImageFont.truetype(s_time["font_path"], s_time["size"])
    except:
        t_font_obj = ImageFont.load_default()

    align_mode = styles.get("time_alignment", "right")
    base_time_x = (W - padding_x if align_mode in ["right", "triangle"] else int(W*0.6) if align_mode=="left" else int(W*0.775)) + s_time["pos_x"]
    
    fixed_label_w = 0
    if align_mode == "triangle":
        d_draw = ImageDraw.Draw(Image.new("RGBA",(1,1)))
        try: fb_font = ImageFont.truetype(fallback_font_path, s_time["size"]) if fallback_font_path else t_font_obj
        except: fb_font = t_font_obj
        w1, _ = draw_text_mixed(d_draw, (0,0), "OPEN", t_font_obj, fb_font, (0,0,0))
        w2, _ = draw_text_mixed(d_draw, (0,0), "START", t_font_obj, fb_font, (0,0,0))
        fixed_label_w = max(w1, w2)

    draw_time_row_aligned(
        base_img, "OPEN", str(open_time or "TBA"), base_time_x, header_y + s_time["pos_y"],
        t_font_obj, s_time["size"], int(W*0.35), s_time["color"],
        s_time["shadow_on"], s_time["shadow_color"], s_time["shadow_blur"], s_time["shadow_off_x"], s_time["shadow_off_y"],
        fallback_font_path,
        styles.get("time_tri_visible", True), styles.get("time_tri_scale", 1.0), None,
        align_mode, fixed_label_w
    )
    
    start_y = header_y + int(s_time["size"]*1.3) + time_line_gap
    draw_time_row_aligned(
        base_img, "START", str(start_time or "TBA"), base_time_x, start_y + s_time["pos_y"],
        t_font_obj, s_time["size"], int(W*0.35), s_time["color"],
        s_time["shadow_on"], s_time["shadow_color"], s_time["shadow_blur"], s_time["shadow_off_x"], s_time["shadow_off_y"],
        fallback_font_path,
        styles.get("time_tri_visible", True), styles.get("time_tri_scale", 1.0), None,
        align_mode, fixed_label_w
    )

    # C. フッター (チケット・備考)
    footer_lines = []
    
    note_gap = int(styles.get("note_gap", 15) * scale_f)
    ticket_gap = int(styles.get("ticket_gap", 20) * scale_f)
    area_gap = int(styles.get("area_gap", 40) * scale_f)
    footer_pos_y = int(styles.get("footer_pos_y", 0) * scale_f)

    for n in reversed(common_notes_list):
        if n and str(n).strip():
            footer_lines.append({"text": f"※{str(n).strip()}", "style": s_note, "gap": note_gap})
    
    is_first = True
    for t in reversed(ticket_info_list):
        name = t.get('name', '')
        price = t.get('price', '')
        t_note = t.get('note', '')
        txt = f"{name} {price}"
        if t_note: txt += f" ({t_note})"
        
        gap = ticket_gap + (area_gap if is_first and footer_lines else 0)
        footer_lines.append({"text": txt, "style": s_ticket, "gap": gap})
        is_first = False

    # フッター高さ計算 (安全策付き)
    ft_h = int(H * 0.05)
    processed_footer = []
    
    def get_calc_font(style_obj):
        try: return ImageFont.truetype(style_obj["font_path"], style_obj["size"])
        except: return ImageFont.load_default()
    
    def get_fallback_calc_font(style_obj):
        if fallback_font_path:
            try: return ImageFont.truetype(fallback_font_path, style_obj["size"])
            except: pass
        return ImageFont.load_default()

    f_note_obj = get_calc_font(s_note)
    f_ticket_obj = get_calc_font(s_ticket)
    f_fb_note = get_fallback_calc_font(s_note)
    f_fb_ticket = get_fallback_calc_font(s_ticket)

    for item in footer_lines:
        has_jp = contains_japanese(item["text"])
        
        if item["style"] == s_ticket:
            u_font = f_fb_ticket if has_jp else f_ticket_obj
        else:
            u_font = f_fb_note if has_jp else f_note_obj
        
        dummy_draw = ImageDraw.Draw(Image.new("RGBA",(1,1)))
        bbox = dummy_draw.textbbox((0,0), item["text"], font=u_font)
        h = bbox[3] - bbox[1]
        processed_footer.append({**item, "h": h})
        ft_h += h + item["gap"]

    footer_start_y = H - ft_h + footer_pos_y
    curr_fy = footer_start_y
    
    for item in reversed(processed_footer):
        st_obj = item["style"]
        
        use_font_path = st_obj["font_path"]
        if contains_japanese(item["text"]) and fallback_font_path:
            use_font_path = fallback_font_path
        
        actual_h = draw_text_with_shadow(
            base_img, item["text"], W//2 + st_obj["pos_x"], curr_fy + st_obj["pos_y"], 
            use_font_path, 
            st_obj["size"], int(W*0.9), st_obj["color"], "ma",
            st_obj["shadow_on"], st_obj["shadow_color"], st_obj["shadow_blur"], st_obj["shadow_off_x"], st_obj["shadow_off_y"],
            fallback_font_path=fallback_font_path
        )
        curr_fy += item["h"] + item["gap"]

    return base_img
