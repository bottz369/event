import os
import re
import requests
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont, ImageFilter

from constants import FONT_DIR

# ==========================================
# 1. ヘルパー関数 (画像読み込みなど)
# ==========================================
def load_image(source):
    """パスまたはURLから画像を読み込む"""
    if not source: return None
    try:
        if isinstance(source, Image.Image):
            return source.convert("RGBA")
            
        if isinstance(source, str):
            if source.startswith("http://") or source.startswith("https://"):
                response = requests.get(source, timeout=10)
                if response.status_code == 200:
                    return Image.open(BytesIO(response.content)).convert("RGBA")
            elif os.path.exists(source):
                return Image.open(source).convert("RGBA")
    except Exception as e:
        print(f"Image Load Error: {e}")
    return None

# ==========================================
# 2. 描画・フォントロジック (コアエンジン)
# ==========================================

def contains_japanese(text):
    """テキストに日本語（ひらがな、カタカナ、漢字）が含まれているか判定"""
    if not text: return False
    return bool(re.search(r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]', str(text)))

def is_glyph_available(font, char):
    """フォントに特定の文字(グリフ)が含まれているか判定"""
    if char.isspace() or ord(char) < 32: return True
    
    if not hasattr(font, "getmask"):
        return True

    try:
        mask = font.getmask(char)
        return not (mask.size[0] == 0 or mask.size[1] == 0)
    except: return True 

def draw_text_mixed(draw, xy, text, primary_font, fallback_font, fill):
    """メインフォントとフォールバックフォント(日本語用)を文字ごとに切り替えて描画・計測"""
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
        
        if draw:
            draw.text((current_x, y), char, font=use_font, fill=fill)
        
        try: advance = use_font.getlength(char)
        except: advance = char_w
        
        current_x += advance
        total_w += advance
        if char_h > max_h: max_h = char_h
        
    return total_w, max_h

def draw_text_with_shadow(base_img, text, x, y, font_path, font_size_px, max_width, fill_color, 
                          anchor="ma", # ★変更: デフォルトを中央揃え(ma)に
                          shadow_on=False, shadow_color="#000000", shadow_blur=0, shadow_off_x=5, shadow_off_y=5,
                          fallback_font_path=None, measure_only=False):
    if not text: return 0
    text_str = str(text)
    
    current_size = int(font_size_px)
    min_size = 10
    
    def load_fonts(size):
        try:
            p_font = ImageFont.truetype(font_path, size) if font_path and os.path.exists(font_path) else ImageFont.load_default()
        except:
            p_font = ImageFont.load_default()
        
        f_font = p_font 
        if fallback_font_path and os.path.exists(fallback_font_path):
            try:
                f_font = ImageFont.truetype(fallback_font_path, size)
            except:
                pass
        return p_font, f_font

    primary_font, fallback_font = load_fonts(current_size)
    dummy_draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    
    can_resize = True

    # Autoscaling Loop
    while can_resize and current_size > min_size:
        w, h = draw_text_mixed(dummy_draw, (0, 0), text_str, primary_font, fallback_font, fill_color)
        margin_est = max(shadow_blur * 3, abs(shadow_off_x), abs(shadow_off_y)) + 10
        
        if w + (margin_est * 2) <= max_width:
            break
            
        current_size -= 2
        primary_font, fallback_font = load_fonts(current_size)

    # 最終計測
    text_w, text_h = draw_text_mixed(dummy_draw, (0, 0), text_str, primary_font, fallback_font, fill_color)
    margin = int(max(shadow_blur * 3, abs(shadow_off_x), abs(shadow_off_y)) + 20)
    
    if measure_only:
        return int(text_h + margin + current_size * 0.2) 

    # 本番描画
    canvas_w = int(text_w + margin * 2)
    canvas_h = int(text_h + margin * 2 + current_size * 0.5) 
    
    txt_img = Image.new("RGBA", (canvas_w, canvas_h), (0,0,0,0))
    txt_draw = ImageDraw.Draw(txt_img)
    draw_x, draw_y = margin, margin
    
    draw_text_mixed(txt_draw, (draw_x, draw_y), text_str, primary_font, fallback_font, fill_color)
    
    final_layer = Image.new("RGBA", (canvas_w, canvas_h), (0,0,0,0))
    
    if shadow_on:
        alpha = txt_img.getchannel("A")
        shadow_solid = Image.new("RGBA", (canvas_w, canvas_h), shadow_color)
        shadow_solid.putalpha(alpha)
        if shadow_blur > 0:
            shadow_solid = shadow_solid.filter(ImageFilter.GaussianBlur(shadow_blur))
        final_layer.paste(shadow_solid, (shadow_off_x, shadow_off_y), shadow_solid)
        
    final_layer.paste(txt_img, (0, 0), txt_img)
    
    content_w, content_h = canvas_w, canvas_h
    effective_text_w = text_w + (max(abs(shadow_off_x), shadow_blur*2)) 
    
    if effective_text_w > max_width:
        ratio = max_width / effective_text_w
        new_w = int(content_w * ratio)
        new_h = int(content_h * ratio)
        final_layer = final_layer.resize((new_w, new_h), Image.LANCZOS)
        content_w, content_h = new_w, new_h

    # 配置計算 (Anchor処理)
    paste_x = x - int(margin * (content_w / canvas_w))
    paste_y = y - margin
    
    if anchor == "ra":
        paste_x = x - content_w + int(margin * (content_w / canvas_w))
    elif anchor == "ma": # Middle/Center
        paste_x = x - (content_w // 2)
    elif anchor == "la":
        paste_x = x - int(margin * (content_w / canvas_w))

    if base_img:
        base_img.paste(final_layer, (int(paste_x), int(paste_y)), final_layer)
        
    return content_h - margin

def draw_time_row_aligned(base_img, label, time_str, x, y, font, font_size_px, max_width, fill_color,
                          shadow_on, shadow_color, shadow_blur, shadow_off_x, shadow_off_y, fallback_font_path,
                          tri_visible=True, tri_scale=1.0, tri_color=None,
                          alignment="center", fixed_label_w=0, measure_only=False): # ★変更: デフォルト center
    
    try: primary_font = font
    except: primary_font = ImageFont.load_default()
        
    fallback_font = primary_font
    if fallback_font_path and os.path.exists(fallback_font_path):
        try: fallback_font = ImageFont.truetype(fallback_font_path, int(font_size_px))
        except: pass

    dummy = ImageDraw.Draw(Image.new("RGBA", (1,1)))
    
    w_label, h_label = draw_text_mixed(dummy, (0,0), label, primary_font, fallback_font, fill_color)
    w_time, h_time = draw_text_mixed(dummy, (0,0), time_str, primary_font, fallback_font, fill_color)
    
    tri_h = font_size_px * 0.6 * tri_scale
    tri_w = tri_h * 0.8
    tri_padding = font_size_px * 0.3
    
    if alignment == "triangle":
        total_w_content = fixed_label_w + (tri_w + tri_padding * 2 if tri_visible else tri_padding) + w_time
    else:
        total_w_content = w_label + (tri_w + tri_padding * 2 if tri_visible else tri_padding) + w_time
        
    margin = int(max(shadow_blur * 3, abs(shadow_off_x), abs(shadow_off_y)) + 20)
    canvas_h = int(max(h_label, h_time, tri_h) + margin * 2 + font_size_px * 0.5)
    
    if measure_only:
        return canvas_h - (margin * 2)

    canvas_w = int(total_w_content + margin * 2)
    txt_img = Image.new("RGBA", (canvas_w, canvas_h), (0,0,0,0))
    draw = ImageDraw.Draw(txt_img)
    
    cur_x, draw_y = margin, margin
    
    if alignment == "triangle":
        label_draw_x = cur_x + (fixed_label_w - w_label)
        draw_text_mixed(draw, (label_draw_x, draw_y), label, primary_font, fallback_font, fill_color)
        cur_x += fixed_label_w
    else:
        draw_text_mixed(draw, (cur_x, draw_y), label, primary_font, fallback_font, fill_color)
        cur_x += w_label
    
    if tri_visible:
        cur_x += tri_padding
        cy = draw_y + (font_size_px * 0.5)
        draw.polygon([(cur_x, cy - tri_h/2), (cur_x, cy + tri_h/2), (cur_x + tri_w, cy)], fill=tri_color or fill_color)
        cur_x += tri_w + tri_padding
    else:
        cur_x += tri_padding

    draw_text_mixed(draw, (cur_x, draw_y), time_str, primary_font, fallback_font, fill_color)
    
    final_layer = Image.new("RGBA", (canvas_w, canvas_h), (0,0,0,0))
    if shadow_on:
        alpha = txt_img.getchannel("A")
        shadow_solid = Image.new("RGBA", (canvas_w, canvas_h), shadow_color)
        shadow_solid.putalpha(alpha)
        if shadow_blur > 0:
            shadow_solid = shadow_solid.filter(ImageFilter.GaussianBlur(shadow_blur))
        final_layer.paste(shadow_solid, (shadow_off_x, shadow_off_y), shadow_solid)
        
    final_layer.paste(txt_img, (0, 0), txt_img)
    
    # 配置
    # x は常に中心座標として扱われるように修正 (Center Align Logic)
    paste_x = x - (canvas_w // 2) + margin
    paste_y = y - margin
    
    # もし右揃え・左揃えが指定されたとしても、この関数自体は「指定されたxを中心」として描画するように統一
    # (呼び出し元で x を調整する設計)
    
    if base_img:
        base_img.paste(final_layer, (int(paste_x), int(paste_y)), final_layer)
        
    return max(h_label, h_time)

# ==========================================
# 3. フライヤー生成関数 (メインロジック)
# ==========================================
def create_flyer_image_shadow(db, bg_source, logo_source, main_source, styles,
                              date_text, venue_text, subtitle_text,
                              open_time, start_time,
                              ticket_info_list, common_notes_list,
                              system_fallback_filename="keifont.ttf"):
    
    # --- 1. 背景の準備 ---
    CANVAS_W, CANVAS_H = 1080, 1350
    
    bg_img = load_image(bg_source)
    if bg_img:
        bg_ratio = bg_img.width / bg_img.height
        canvas_ratio = CANVAS_W / CANVAS_H
        if bg_ratio > canvas_ratio:
            new_h = CANVAS_H
            new_w = int(new_h * bg_ratio)
        else:
            new_w = CANVAS_W
            new_h = int(new_w / bg_ratio)
        bg_resized = bg_img.resize((new_w, new_h), Image.LANCZOS)
        left = (new_w - CANVAS_W) // 2
        top = (new_h - CANVAS_H) // 2
        bg_final = bg_resized.crop((left, top, left + CANVAS_W, top + CANVAS_H))
    else:
        bg_final = Image.new("RGBA", (CANVAS_W, CANVAS_H), (30, 30, 30, 255))

    canvas = bg_final.convert("RGBA")
    
    # --- 2. 共通フォントパスの解決 ---
    def get_font_path(fname):
        candidates = [
            fname,
            os.path.join(FONT_DIR, fname),
            os.path.join("assets", "fonts", fname),
            "keifont.ttf"
        ]
        for c in candidates:
            if c and os.path.exists(c): return c
        return None

    fallback_path = get_font_path(system_fallback_filename)

    # --- 3. メイン画像 (Grid/TT) の配置 ---
    main_img = load_image(main_source)

    if main_img:
        scale_w_pct = styles.get("content_scale_w", 100)
        scale_h_pct = styles.get("content_scale_h", 100)
        pos_y_off = styles.get("content_pos_y", 0)
        
        target_w = int(CANVAS_W * (scale_w_pct / 100))
        target_h = int(main_img.height * (target_w / main_img.width) * (scale_h_pct/scale_w_pct))
        
        main_resized = main_img.resize((target_w, target_h), Image.LANCZOS)
        
        # 中央基準
        main_x = (CANVAS_W - target_w) // 2
        # ★修正: Y軸反転 (+で上へ -> 基準Y - オフセット)
        # 基準は中央
        main_y = (CANVAS_H - target_h) // 2 - pos_y_off
        
        canvas.paste(main_resized, (main_x, main_y), main_resized)

    # --- 4. ロゴ配置 ---
    logo_img = load_image(logo_source)
    if logo_img:
        l_scale = styles.get("logo_scale", 1.0)
        l_off_x = styles.get("logo_pos_x", 0.0)
        l_off_y = styles.get("logo_pos_y", 0.0)
        
        base_w = CANVAS_W * 0.4 * l_scale
        l_ratio = logo_img.height / logo_img.width
        l_w = int(base_w)
        l_h = int(l_w * l_ratio)
        
        logo_resized = logo_img.resize((l_w, l_h), Image.LANCZOS)
        
        # 基準位置: 上部中央
        base_x = (CANVAS_W - l_w) // 2
        base_y = 50
        
        # オフセット適用
        final_x = base_x + int(CANVAS_W * (l_off_x / 100))
        # ★修正: Y軸反転
        final_y = base_y - int(CANVAS_H * (l_off_y / 100))
        
        canvas.paste(logo_resized, (final_x, final_y), logo_resized)

    # --- 5. テキスト描画 ---
    
    # 基準Y座標 (フッター開始位置)
    # ★修正: Y軸反転ロジック
    footer_base_y = CANVAS_H - 450 - styles.get("footer_pos_y", 0)
    current_y = footer_base_y

    def get_s(key_prefix):
        return {
            "font_path": get_font_path(styles.get(f"{key_prefix}_font")),
            "font_size_px": styles.get(f"{key_prefix}_size", 40),
            "fill_color": styles.get(f"{key_prefix}_color", "#FFFFFF"),
            "shadow_on": styles.get(f"{key_prefix}_shadow_on", False),
            "shadow_color": styles.get(f"{key_prefix}_shadow_color", "#000000"),
            "shadow_blur": styles.get(f"{key_prefix}_shadow_blur", 0),
            "shadow_off_x": styles.get(f"{key_prefix}_shadow_off_x", 5),
            "shadow_off_y": styles.get(f"{key_prefix}_shadow_off_y", 5),
            "pos_x": styles.get(f"{key_prefix}_pos_x", 0),
            "pos_y": styles.get(f"{key_prefix}_pos_y", 0)
        }

    # (0) サブタイトル
    if subtitle_text:
        s = get_s("subtitle")
        h = draw_text_with_shadow(
            canvas, subtitle_text,
            # ★修正: Xは中央基準、Yは「現在位置 - オフセット」
            CANVAS_W // 2 + s["pos_x"], current_y - s["pos_y"],
            s["font_path"], s["font_size_px"], CANVAS_W - 40, s["fill_color"],
            anchor="ma", # 中央揃え
            shadow_on=s["shadow_on"], shadow_color=s["shadow_color"],
            shadow_blur=s["shadow_blur"], shadow_off_x=s["shadow_off_x"], shadow_off_y=s["shadow_off_y"],
            fallback_font_path=fallback_path
        )
        current_y += h + styles.get("subtitle_date_gap", 10)

    # (1) 日付
    if date_text:
        s = get_s("date")
        h = draw_text_with_shadow(
            canvas, date_text, 
            # ★修正: Xは中央基準、Yは「現在位置 - オフセット」
            CANVAS_W // 2 + s["pos_x"], current_y - s["pos_y"],
            s["font_path"], s["font_size_px"], CANVAS_W - 40, s["fill_color"],
            anchor="ma", # 中央揃え
            shadow_on=s["shadow_on"], shadow_color=s["shadow_color"],
            shadow_blur=s["shadow_blur"], shadow_off_x=s["shadow_off_x"], shadow_off_y=s["shadow_off_y"],
            fallback_font_path=fallback_path
        )
        current_y += h + styles.get("date_venue_gap", 10)

    # (2) 会場
    if venue_text:
        s = get_s("venue")
        h = draw_text_with_shadow(
            canvas, venue_text, 
            # ★修正: Xは中央基準、Yは「現在位置 - オフセット」
            CANVAS_W // 2 + s["pos_x"], current_y - s["pos_y"],
            s["font_path"], s["font_size_px"], CANVAS_W - 40, s["fill_color"],
            anchor="ma", # 中央揃え
            shadow_on=s["shadow_on"], shadow_color=s["shadow_color"],
            shadow_blur=s["shadow_blur"], shadow_off_x=s["shadow_off_x"], shadow_off_y=s["shadow_off_y"],
            fallback_font_path=fallback_path
        )
        current_y += h + 30 

    # (3) 時間 (OPEN/START)
    s = get_s("time")
    try: time_font = ImageFont.truetype(s["font_path"], int(s["font_size_px"]))
    except: time_font = ImageFont.load_default()
    
    tri_visible = styles.get("time_tri_visible", True)
    tri_scale = styles.get("time_tri_scale", 1.0)
    line_gap = styles.get("time_line_gap", 0)
    
    # ★修正: 強制的に中央配置として扱う
    center_x = CANVAS_W // 2 + s["pos_x"]
    start_y = current_y - s["pos_y"]
    
    # ラベル幅計測
    dummy_draw = ImageDraw.Draw(Image.new("RGBA",(1,1)))
    w_open, _ = draw_text_mixed(dummy_draw, (0,0), "OPEN", time_font, None, None)
    w_start, _ = draw_text_mixed(dummy_draw, (0,0), "START", time_font, None, None)
    fixed_label_w = max(w_open, w_start)

    h1 = draw_time_row_aligned(
        canvas, "OPEN", open_time, center_x, start_y,
        time_font, s["font_size_px"], CANVAS_W, s["fill_color"],
        s["shadow_on"], s["shadow_color"], s["shadow_blur"], s["shadow_off_x"], s["shadow_off_y"], fallback_path,
        tri_visible, tri_scale, s["fill_color"], "center", fixed_label_w
    )
    
    h2 = draw_time_row_aligned(
        canvas, "START", start_time, center_x, start_y + h1 + line_gap,
        time_font, s["font_size_px"], CANVAS_W, s["fill_color"],
        s["shadow_on"], s["shadow_color"], s["shadow_blur"], s["shadow_off_x"], s["shadow_off_y"], fallback_path,
        tri_visible, tri_scale, s["fill_color"], "center", fixed_label_w
    )
    
    current_y = start_y + h1 + line_gap + h2 + styles.get("area_gap", 40)

    # (4) チケット情報
    s = get_s("ticket_name")
    t_gap = styles.get("ticket_gap", 20)
    
    for t in ticket_info_list:
        if not t.get("name") and not t.get("price"): continue
        line_text = f"{t.get('name')} {t.get('price')}"
        if t.get("note"): line_text += f" ({t.get('note')})"
        
        h = draw_text_with_shadow(
            canvas, line_text, 
            # ★修正: X中央、Y反転
            CANVAS_W // 2 + s["pos_x"], current_y - s["pos_y"],
            s["font_path"], s["font_size_px"], CANVAS_W - 60, s["fill_color"],
            anchor="ma", # 中央揃え
            shadow_on=s["shadow_on"], shadow_color=s["shadow_color"],
            shadow_blur=s["shadow_blur"], shadow_off_x=s["shadow_off_x"], shadow_off_y=s["shadow_off_y"],
            fallback_font_path=fallback_path
        )
        current_y += h + t_gap

    # (5) 共通備考
    s = get_s("ticket_note")
    n_gap = styles.get("note_gap", 15)
    current_y += 10 
    
    for note in common_notes_list:
        if not note: continue
        h = draw_text_with_shadow(
            canvas, note, 
            # ★修正: X中央、Y反転
            CANVAS_W // 2 + s["pos_x"], current_y - s["pos_y"],
            s["font_path"], s["font_size_px"], CANVAS_W - 60, s["fill_color"],
            anchor="ma", # 中央揃え
            shadow_on=s["shadow_on"], shadow_color=s["shadow_color"],
            shadow_blur=s["shadow_blur"], shadow_off_x=s["shadow_off_x"], shadow_off_y=s["shadow_off_y"],
            fallback_font_path=fallback_path
        )
        current_y += h + n_gap

    return canvas
