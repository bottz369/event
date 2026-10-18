import logging
import os
import re
import requests
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageColor, ImageChops

from constants import FONT_DIR

logger = logging.getLogger(__name__)

# §5: 素材(背景 / ロゴ)取得失敗の可観測化。
# ログは failures の有無に関わらず常に出す。failures は任意 out-param(既定 None)で、
# None のときは従来と完全に同一挙動(描画・レイアウトは一切変更していない)。
# main_source は呼び出し側(generation_service)が PIL を渡すのでここでは判定しない。

# ==========================================
# 1. ヘルパー関数 (画像読み込みなど)
# ==========================================
def load_image(source):
    """パスまたはURLから画像を読み込む。失敗は None(挙動不変)だが §5 で WARNING を出す。"""
    if not source: return None  # 空は失敗ではない(ログも出さない)
    try:
        if isinstance(source, Image.Image):
            return source.convert("RGBA")
        if isinstance(source, str):
            if source.startswith("http://") or source.startswith("https://"):
                response = requests.get(source, timeout=10)
                if response.status_code == 200:
                    return Image.open(BytesIO(response.content)).convert("RGBA")
                logger.warning(
                    "flyer asset fetch failed: url=%r reason=http_%s",
                    source, response.status_code,
                )
                return None
            elif os.path.exists(source):
                return Image.open(source).convert("RGBA")
            logger.warning("flyer asset load failed: path=%r reason=not_found", source)
            return None
    except Exception as e:
        # 旧実装は print だった。§5 で module logger に統一(print は Railway で追いにくい)。
        logger.warning(
            "flyer asset load failed: src=%r reason=%s: %s", source, type(e).__name__, e
        )
    return None

# ==========================================
# 2. 描画・フォントロジック (コアエンジン)
# ==========================================

def contains_japanese(text):
    if not text: return False
    return bool(re.search(r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]', str(text)))

def is_glyph_available(font, char):
    if char.isspace() or ord(char) < 32: return True
    if not hasattr(font, "getmask"): return True
    try:
        mask = font.getmask(char)
        return not (mask.size[0] == 0 or mask.size[1] == 0)
    except Exception: return True 

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
        
        if draw:
            draw.text((current_x, y), char, font=use_font, fill=fill)
        
        try: advance = use_font.getlength(char)
        except Exception: advance = char_w
        
        current_x += advance
        total_w += advance
        if char_h > max_h: max_h = char_h
        
    return total_w, max_h

# ★安全に数値を変換する内部関数
def safe_val(val):
    try:
        if val is None: return 0
        return int(float(val))
    except (ValueError, TypeError):
        return 0

def draw_text_with_shadow(base_img, text, x, y, font_path, font_size_px, max_width, fill_color, 
                          anchor="ma", 
                          shadow_on=False, shadow_color="#000000", 
                          shadow_blur=0, shadow_off_x=5, shadow_off_y=5,
                          shadow_opacity=255, shadow_spread=0,
                          fallback_font_path=None, measure_only=False, layout_bounds=None):
    if not text: return 0
    text_str = str(text)
    
    # 数値の安全確保
    current_size = safe_val(font_size_px)
    if current_size <= 0: current_size = 20
    min_size = 10
    
    shadow_blur = safe_val(shadow_blur)
    shadow_off_x = safe_val(shadow_off_x)
    shadow_off_y = safe_val(shadow_off_y)
    shadow_spread = safe_val(shadow_spread)
    shadow_opacity = safe_val(shadow_opacity)
    
    def load_fonts(size):
        try:
            p_font = ImageFont.truetype(font_path, size) if font_path and os.path.exists(font_path) else ImageFont.load_default()
        except Exception:
            p_font = ImageFont.load_default()
        f_font = p_font 
        if fallback_font_path and os.path.exists(fallback_font_path):
            try: f_font = ImageFont.truetype(fallback_font_path, size)
            except Exception: pass
        return p_font, f_font

    primary_font, fallback_font = load_fonts(current_size)
    dummy_draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    
    can_resize = True
    while can_resize and current_size > min_size:
        w, h = draw_text_mixed(dummy_draw, (0, 0), text_str, primary_font, fallback_font, fill_color)
        margin_est = max(shadow_blur * 3, abs(shadow_off_x), abs(shadow_off_y)) + 10 + shadow_spread
        if w + (margin_est * 2) <= max_width: break
        current_size -= 2
        primary_font, fallback_font = load_fonts(current_size)

    text_w, text_h = draw_text_mixed(dummy_draw, (0, 0), text_str, primary_font, fallback_font, fill_color)
    margin = int(max(shadow_blur * 3, abs(shadow_off_x), abs(shadow_off_y)) + 20 + shadow_spread)
    
    if measure_only:
        return int(text_h + margin + current_size * 0.2) 

    canvas_w = int(text_w + margin * 2)
    canvas_h = int(text_h + margin * 2 + current_size * 0.5) 
    
    txt_img = Image.new("RGBA", (canvas_w, canvas_h), (0,0,0,0))
    txt_draw = ImageDraw.Draw(txt_img)
    draw_x, draw_y = margin, margin
    draw_text_mixed(txt_draw, (draw_x, draw_y), text_str, primary_font, fallback_font, fill_color)
    
    final_layer = Image.new("RGBA", (canvas_w, canvas_h), (0,0,0,0))
    
    if shadow_on:
        try: s_rgb = ImageColor.getrgb(shadow_color)
        except Exception: s_rgb = (0, 0, 0)
        s_color_with_alpha = s_rgb + (int(shadow_opacity),)
        
        shadow_layer = Image.new("RGBA", (canvas_w, canvas_h), (0,0,0,0))
        shadow_draw = ImageDraw.Draw(shadow_layer)
        
        draw_text_mixed(shadow_draw, (draw_x + shadow_off_x, draw_y + shadow_off_y), 
                        text_str, primary_font, fallback_font, s_color_with_alpha)
        
        if shadow_spread > 0:
            r, g, b, a = shadow_layer.split()
            a_dilated = a.filter(ImageFilter.MaxFilter(1 + shadow_spread * 2))
            shadow_expanded = Image.new("RGBA", shadow_layer.size, s_color_with_alpha)
            shadow_expanded.putalpha(a_dilated)
            shadow_layer = shadow_expanded

        if shadow_blur > 0:
            shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(shadow_blur))
            
        final_layer.paste(shadow_layer, (0, 0), shadow_layer)
        
    final_layer.paste(txt_img, (0, 0), txt_img)
    
    content_w, content_h = canvas_w, canvas_h
    effective_text_w = text_w + (max(abs(shadow_off_x), shadow_blur*2)) + shadow_spread*2
    
    if effective_text_w > max_width:
        ratio = max_width / effective_text_w
        new_w = int(content_w * ratio)
        new_h = int(content_h * ratio)
        final_layer = final_layer.resize((new_w, new_h), Image.LANCZOS)
        content_w, content_h = new_w, new_h

    paste_x = x - int(margin * (content_w / canvas_w))
    paste_y = y - margin
    
    if anchor == "ra":
        paste_x = x - content_w + int(margin * (content_w / canvas_w))
    elif anchor == "ma":
        paste_x = x - (content_w // 2)
    elif anchor == "la":
        paste_x = x - int(margin * (content_w / canvas_w))

    if base_img:
        base_img.paste(final_layer, (int(paste_x), int(paste_y)), final_layer)
    if layout_bounds is not None:
        visible = final_layer.getbbox()
        if visible:
            layout_bounds.update(left=int(paste_x) + visible[0], top=int(paste_y) + visible[1],
                                 right=int(paste_x) + visible[2], bottom=int(paste_y) + visible[3])
    if layout_bounds is not None:
        ink = txt_img.getbbox()
        if ink:
            sx, sy = content_w / canvas_w, content_h / canvas_h
            layout_bounds['ink'] = dict(left=int(paste_x+ink[0]*sx), top=int(paste_y+ink[1]*sy),
                                        right=int(paste_x+ink[2]*sx), bottom=int(paste_y+ink[3]*sy),font_size=current_size*sx)
    return content_h - margin

def draw_time_row_aligned(base_img, label, time_str, x, y, font, font_size_px, max_width, fill_color,
                          shadow_on, shadow_color, shadow_blur, shadow_off_x, shadow_off_y, fallback_font_path,
                          shadow_opacity=255, shadow_spread=0, 
                          tri_visible=True, tri_scale=1.0, tri_color=None,
                          alignment="center", fixed_label_w=0, measure_only=False, layout_bounds=None):
    
    # 数値の安全確保
    shadow_blur = safe_val(shadow_blur)
    shadow_off_x = safe_val(shadow_off_x)
    shadow_off_y = safe_val(shadow_off_y)
    shadow_spread = safe_val(shadow_spread)
    shadow_opacity = safe_val(shadow_opacity)
    
    try: primary_font = font
    except Exception: primary_font = ImageFont.load_default()
    fallback_font = primary_font
    if fallback_font_path and os.path.exists(fallback_font_path):
        try: fallback_font = ImageFont.truetype(fallback_font_path, int(font_size_px))
        except Exception: pass

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
        
    margin = int(max(shadow_blur * 3, abs(shadow_off_x), abs(shadow_off_y)) + 20 + shadow_spread)
    canvas_h = int(max(h_label, h_time, tri_h) + margin * 2 + font_size_px * 0.5)
    
    if measure_only: return canvas_h - (margin * 2)

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
        try: s_rgb = ImageColor.getrgb(shadow_color)
        except Exception: s_rgb = (0,0,0)
        s_color_with_alpha = s_rgb + (int(shadow_opacity),)
        
        shadow_layer = Image.new("RGBA", (canvas_w, canvas_h), (0,0,0,0))
        shadow_draw = ImageDraw.Draw(shadow_layer)
        
        s_cur_x = margin 
        if alignment == "triangle":
            s_cur_x += (fixed_label_w - w_label)
            draw_text_mixed(shadow_draw, (s_cur_x, draw_y), label, primary_font, fallback_font, s_color_with_alpha)
            s_cur_x = margin + fixed_label_w
        else:
            draw_text_mixed(shadow_draw, (s_cur_x, draw_y), label, primary_font, fallback_font, s_color_with_alpha)
            s_cur_x += w_label
            
        s_cur_x += tri_padding
        if tri_visible:
            cy = draw_y + (font_size_px * 0.5)
            shadow_draw.polygon([(s_cur_x, cy - tri_h/2), (s_cur_x, cy + tri_h/2), (s_cur_x + tri_w, cy)], fill=s_color_with_alpha)
            s_cur_x += tri_w + tri_padding
        
        draw_text_mixed(shadow_draw, (s_cur_x, draw_y), time_str, primary_font, fallback_font, s_color_with_alpha)
        
        if shadow_spread > 0:
            r, g, b, a = shadow_layer.split()
            a = a.filter(ImageFilter.MaxFilter(1 + shadow_spread * 2))
            shadow_expanded = Image.new("RGBA", shadow_layer.size, s_color_with_alpha)
            shadow_expanded.putalpha(a)
            shadow_layer = shadow_expanded

        if shadow_blur > 0:
            shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(shadow_blur))
            
        final_layer.paste(shadow_layer, (shadow_off_x, shadow_off_y), shadow_layer)

    final_layer.paste(txt_img, (0, 0), txt_img)
    
    paste_x = x - (canvas_w // 2) + margin
    paste_y = y - margin
    
    if base_img:
        base_img.paste(final_layer, (int(paste_x), int(paste_y)), final_layer)
        
    if layout_bounds is not None:
        visible = final_layer.getbbox()
        if visible:
            layout_bounds.update(left=int(paste_x)+visible[0], top=int(paste_y)+visible[1],
                                 right=int(paste_x)+visible[2], bottom=int(paste_y)+visible[3])
    if layout_bounds is not None:
        ink = txt_img.getbbox()
        if ink:
            layout_bounds['ink'] = dict(left=int(paste_x)+ink[0], top=int(paste_y)+ink[1],
                                        right=int(paste_x)+ink[2], bottom=int(paste_y)+ink[3])
    return max(h_label, h_time)

# ==========================================
# 3. フライヤー生成関数 (メインロジック)
# ==========================================
def create_flyer_image_shadow(bg_source, logo_source, main_source, styles,
                              date_text, venue_text, subtitle_text,
                              open_time, start_time,
                              ticket_info_list, common_notes_list,
                              system_fallback_filename="keifont.ttf",
                              failures=None):
    
    layout_meta = {}
    CANVAS_W, CANVAS_H = 1080, 1350
    
    # 背景
    bg_img = load_image(bg_source)
    # §5: 背景の指定があったのに読めなかったら記録する(未指定は失敗ではない)
    if bg_img is None and bg_source and failures is not None:
        failures.append({
            "kind": "flyer_bg",
            "name": None,
            "url": bg_source if isinstance(bg_source, str) else None,
            "reason": "fetch_failed",
        })
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
    
    # フォント
    def get_font_path(fname):
        candidates = [fname, os.path.join(FONT_DIR, fname), os.path.join("assets", "fonts", fname), "keifont.ttf"]
        for c in candidates:
            if c and os.path.exists(c): return c
        return None
    fallback_path = get_font_path(system_fallback_filename)

    # Geometry only: these observers never change the existing pixel rendering.
    boxes = {}
    phase = 'subtitle'
    def paint_text(*args, **kwargs):
        bounds = kwargs.setdefault('layout_bounds', {})
        height = draw_text_with_shadow(*args, **kwargs)
        if bounds: boxes.setdefault(phase, []).append({**bounds.get('ink',bounds),'advance':height})
        return height
    def paint_time(*args, **kwargs):
        bounds = kwargs.setdefault('layout_bounds', {})
        height = draw_time_row_aligned(*args, **kwargs)
        if args[0] is not None and bounds: boxes.setdefault('time', []).append(dict(bounds.get('ink',bounds)))
        return height

    # メイン画像
    main_img = load_image(main_source)
    if main_img:
        scale_w_pct = styles.get("content_scale_w", 100)
        scale_h_pct = styles.get("content_scale_h", 100)
        pos_y_off = styles.get("content_pos_y", 0)
        target_w = int(CANVAS_W * (scale_w_pct / 100))
        target_h = int(main_img.height * (target_w / main_img.width) * (scale_h_pct/scale_w_pct))
        main_resized = main_img.resize((target_w, target_h), Image.LANCZOS)
        main_base_x = CANVAS_W // 2
        main_base_y = CANVAS_H // 2
        main_x = main_base_x - (target_w // 2)
        main_y = (main_base_y - (target_h // 2)) - pos_y_off
        canvas.paste(main_resized, (main_x, main_y), main_resized)
        layout_meta["main"] = {"base_x": main_base_x, "base_y": main_base_y}
        boxes['main'] = [dict(left=main_x, top=main_y, right=main_x+target_w, bottom=main_y+target_h)]

    # --- 4. ロゴ (★影機能追加) ---
    logo_img = load_image(logo_source)
    # §5: ロゴの指定があったのに読めなかったら記録する(未指定は失敗ではない)
    if logo_img is None and logo_source and failures is not None:
        failures.append({
            "kind": "flyer_logo",
            "name": None,
            "url": logo_source if isinstance(logo_source, str) else None,
            "reason": "fetch_failed",
        })
    if logo_img:
        l_scale = styles.get("logo_scale", 1.0)
        l_off_x = styles.get("logo_pos_x", 0.0)
        l_off_y = styles.get("logo_pos_y", 0.0)
        base_w = CANVAS_W * 0.4 * l_scale
        l_ratio = logo_img.height / logo_img.width
        l_w = int(base_w)
        l_h = int(l_w * l_ratio)
        logo_resized = logo_img.resize((l_w, l_h), Image.LANCZOS)
        
        base_x = (CANVAS_W - l_w) // 2
        base_y = 50
        final_x = base_x + int(CANVAS_W * (l_off_x / 100))
        final_y = base_y - int(CANVAS_H * (l_off_y / 100))
        
        # ロゴの影描画
        if styles.get("logo_shadow_on", False):
            try:
                ls_rgb = ImageColor.getrgb(styles.get("logo_shadow_color", "#000000"))
                ls_opacity = int(styles.get("logo_shadow_opacity", 128))
                ls_spread = int(styles.get("logo_shadow_spread", 0))
                ls_blur = int(styles.get("logo_shadow_blur", 5))
                ls_off_x = int(styles.get("logo_shadow_off_x", 5))
                ls_off_y = int(styles.get("logo_shadow_off_y", 5))
                
                l_alpha = logo_resized.getchannel("A")
                shadow_base = Image.new("RGBA", logo_resized.size, ls_rgb + (ls_opacity,))
                shadow_base.putalpha(l_alpha)
                
                if ls_spread > 0:
                    mask = shadow_base.getchannel("A")
                    mask = mask.filter(ImageFilter.MaxFilter(1 + ls_spread * 2))
                    shadow_expanded = Image.new("RGBA", logo_resized.size, ls_rgb + (ls_opacity,))
                    shadow_expanded.putalpha(mask)
                    shadow_base = shadow_expanded
                
                if ls_blur > 0:
                    shadow_base = shadow_base.filter(ImageFilter.GaussianBlur(ls_blur))
                
                canvas.paste(shadow_base, (final_x + ls_off_x, final_y + ls_off_y), shadow_base)
            except Exception as e:
                print(f"Logo shadow error: {e}")

        canvas.paste(logo_resized, (final_x, final_y), logo_resized)
        visible = logo_resized.getbbox()
        if visible:
            boxes['logo'] = [dict(left=final_x+visible[0], top=final_y+visible[1],
                                  right=final_x+visible[2], bottom=final_y+visible[3])]
        layout_meta["logo"] = {"base_x": CANVAS_W // 2, "base_y": 50, "mode": "percent"}

    # テキスト描画
    footer_base_y = CANVAS_H - 450 - styles.get("footer_pos_y", 0)
    current_y = footer_base_y

    free_font_scale = 1.0

    def get_s(key_prefix):
        return {
            "font_path": get_font_path(styles.get(f"{key_prefix}_font")),
            "font_size_px": max(10, round(styles.get(f"{key_prefix}_size", 40) * free_font_scale)) if key_prefix in ("free_viewing", "free_note", "free_notice") else styles.get(f"{key_prefix}_size", 40),
            "fill_color": styles.get(f"{key_prefix}_color", "#FFFFFF"),
            "shadow_on": styles.get(f"{key_prefix}_shadow_on", False),
            "shadow_color": styles.get(f"{key_prefix}_shadow_color", "#000000"),
            "shadow_blur": styles.get(f"{key_prefix}_shadow_blur", 0),
            "shadow_off_x": styles.get(f"{key_prefix}_shadow_off_x", 5),
            "shadow_off_y": styles.get(f"{key_prefix}_shadow_off_y", 5),
            "shadow_opacity": styles.get(f"{key_prefix}_shadow_opacity", 255),
            "shadow_spread": styles.get(f"{key_prefix}_shadow_spread", 0),
            "pos_x": styles.get(f"{key_prefix}_pos_x", 0),
            "pos_y": styles.get(f"{key_prefix}_pos_y", 0)
        }

    # (0) Subtitle
    phase = 'subtitle'
    if subtitle_text:
        s = get_s("subtitle")
        base_x = CANVAS_W // 2
        base_y = current_y
        layout_meta["subtitle"] = {"base_x": base_x, "base_y": base_y}
        h = paint_text(
            canvas, subtitle_text,
            base_x + s["pos_x"], base_y - s["pos_y"],
            s["font_path"], s["font_size_px"], CANVAS_W - 40, s["fill_color"],
            anchor="ma",
            shadow_on=s["shadow_on"], shadow_color=s["shadow_color"],
            shadow_blur=s["shadow_blur"], shadow_off_x=s["shadow_off_x"], shadow_off_y=s["shadow_off_y"],
            shadow_opacity=s["shadow_opacity"], shadow_spread=s["shadow_spread"],
            fallback_font_path=fallback_path
        )
        current_y += h + styles.get("subtitle_date_gap", 10)

    # (1) Date
    phase = 'date'
    if date_text:
        s = get_s("date")
        base_x = CANVAS_W // 2
        base_y = current_y
        layout_meta["date"] = {"base_x": base_x, "base_y": base_y}
        h = paint_text(
            canvas, date_text, 
            base_x + s["pos_x"], base_y - s["pos_y"],
            s["font_path"], s["font_size_px"], CANVAS_W - 40, s["fill_color"],
            anchor="ma",
            shadow_on=s["shadow_on"], shadow_color=s["shadow_color"],
            shadow_blur=s["shadow_blur"], shadow_off_x=s["shadow_off_x"], shadow_off_y=s["shadow_off_y"],
            shadow_opacity=s["shadow_opacity"], shadow_spread=s["shadow_spread"],
            fallback_font_path=fallback_path
        )
        current_y += h + styles.get("date_venue_gap", 10)

    # (2) Venue
    phase = 'venue'
    if venue_text:
        s = get_s("venue")
        base_x = CANVAS_W // 2
        base_y = current_y
        layout_meta["venue"] = {"base_x": base_x, "base_y": base_y}
        h = paint_text(
            canvas, venue_text, 
            base_x + s["pos_x"], base_y - s["pos_y"],
            s["font_path"], s["font_size_px"], CANVAS_W - 40, s["fill_color"],
            anchor="ma",
            shadow_on=s["shadow_on"], shadow_color=s["shadow_color"],
            shadow_blur=s["shadow_blur"], shadow_off_x=s["shadow_off_x"], shadow_off_y=s["shadow_off_y"],
            shadow_opacity=s["shadow_opacity"], shadow_spread=s["shadow_spread"],
            fallback_font_path=fallback_path
        )
        current_y += h + 30

    # Preserve existing footer offsets when hiding global times for multipart events.
    # Measuring the regular time block keeps saved ticket positioning compatible.
    # (3) Time
    s = get_s("time")
    try: time_font = ImageFont.truetype(s["font_path"], int(s["font_size_px"]))
    except Exception: time_font = ImageFont.load_default()
    tri_visible = styles.get("time_tri_visible", True)
    tri_scale = styles.get("time_tri_scale", 1.0)
    line_gap = styles.get("time_line_gap", 0)
    alignment = styles.get("time_alignment", "center")

    center_x = CANVAS_W // 2 + s["pos_x"]
    start_y = current_y - s["pos_y"]
    if not styles.get("event_multipart"):
        layout_meta["time"] = {"base_x": CANVAS_W // 2, "base_y": current_y}

    dummy = ImageDraw.Draw(Image.new("RGBA",(1,1)))
    w_open, _ = draw_text_mixed(dummy, (0,0), "OPEN", time_font, None, None)
    w_start, _ = draw_text_mixed(dummy, (0,0), "START", time_font, None, None)
    fixed_label_w = max(w_open, w_start)

    h1 = paint_time(
        None if styles.get("event_multipart") else canvas, "OPEN", open_time, center_x, start_y,
        time_font, s["font_size_px"], CANVAS_W, s["fill_color"],
        s["shadow_on"], s["shadow_color"], s["shadow_blur"], s["shadow_off_x"], s["shadow_off_y"], fallback_path,
        s["shadow_opacity"], s["shadow_spread"],
        tri_visible, tri_scale, s["fill_color"], alignment, fixed_label_w
    )

    h2 = paint_time(
        None if styles.get("event_multipart") else canvas, "START", start_time, center_x, start_y + h1 + line_gap,
        time_font, s["font_size_px"], CANVAS_W, s["fill_color"],
        s["shadow_on"], s["shadow_color"], s["shadow_blur"], s["shadow_off_x"], s["shadow_off_y"], fallback_path,
        s["shadow_opacity"], s["shadow_spread"],
        tri_visible, tri_scale, s["fill_color"], alignment, fixed_label_w
    )
    current_y = start_y + h1 + line_gap + h2 + styles.get("area_gap", 40)

    # (4) Footer
    phase = 'ticket_name'
    layout_meta["footer_area"] = {"base_x": CANVAS_W // 2, "base_y": current_y}
    layout_meta["ticket_name"] = {"base_x": CANVAS_W // 2, "base_y": current_y}
    layout_meta["ticket_note"] = {"base_x": CANVAS_W // 2, "base_y": current_y}
    
    s_ticket = get_s("ticket_name")
    t_gap = styles.get("ticket_gap", 20)
    ticket_bottom = None
    for t in ticket_info_list:
        if not t.get("name") and not t.get("price"): continue
        line_text = f"{t.get('name')} {t.get('price')}"
        if t.get("note"): line_text += f" ({t.get('note')})"
        ticket_bounds = {}
        h = paint_text(
            canvas, line_text, 
            CANVAS_W // 2 + s_ticket["pos_x"], current_y - s_ticket["pos_y"],
            s_ticket["font_path"], s_ticket["font_size_px"], CANVAS_W - 60, s_ticket["fill_color"],
            anchor="ma",
            shadow_on=s_ticket["shadow_on"], shadow_color=s_ticket["shadow_color"],
            shadow_blur=s_ticket["shadow_blur"], shadow_off_x=s_ticket["shadow_off_x"], shadow_off_y=s_ticket["shadow_off_y"],
            shadow_opacity=s_ticket["shadow_opacity"], shadow_spread=s_ticket["shadow_spread"],
            fallback_font_path=fallback_path, layout_bounds=ticket_bounds
        )
        bottom = ticket_bounds.get("bottom", current_y - s_ticket["pos_y"] + h)
        ticket_bottom = max(ticket_bottom, bottom) if ticket_bottom is not None else bottom
        current_y += h + t_gap

    if styles.get("event_free_viewing"):
        # Old free_placement values are intentionally ignored: all flyers stay inline.
        base_y = (ticket_bottom if ticket_bottom is not None else current_y) + 10
        notices = [line.strip() for line in str(styles.get("event_free_notices") or "").splitlines()
                   if line.strip()]
        phase = 'free_notice'
        if notices:
            # Reserve space inside the original canvas even for older large free-text styles.
            line_sizes = [styles.get("free_viewing_size", 40)]
            if styles.get("event_free_text"):
                line_sizes.append(styles.get("free_note_size", 22))
            line_sizes.extend([styles.get("free_notice_size", 20)] * len(notices))
            needed = sum(line_sizes) * 1.1 + 5 * len(line_sizes)
            free_font_scale = min(1.0, max(.15, (CANVAS_H - base_y - 20) / needed))
        free_bottom = base_y
        for prefix, text in (("free_viewing", "観覧無料"),
                             ("free_note", styles.get("event_free_text", ""))):
            if not text:
                continue
            phase = prefix
            s = get_s(prefix)
            layout_meta[prefix] = {"base_x": CANVAS_W // 2, "base_y": base_y}
            y = base_y - s.pop("pos_y")
            bounds = {}
            h = paint_text(canvas, text,
                CANVAS_W // 2 + s.pop("pos_x"), y,
                max_width=CANVAS_W - 60, anchor="ma", fallback_font_path=fallback_path,
                layout_bounds=bounds, **s)
            bottom = bounds.get("bottom", y + h)
            free_bottom = max(free_bottom, bottom)
            base_y = bottom + 5
        phase = 'free_notice'
        if notices:
            layout_meta["free_notice"] = {"base_x": CANVAS_W // 2, "base_y": base_y}
            style = get_s("free_notice")
            notice_x = CANVAS_W // 2 + style.pop("pos_x")
            notice_y = base_y - style.pop("pos_y")
            for line in notices:
                text = line if line.startswith("※") else "※" + line
                bounds = {}
                h = paint_text(canvas, text, notice_x, notice_y,
                    max_width=CANVAS_W - 60, anchor="ma", fallback_font_path=fallback_path,
                    layout_bounds=bounds, **style)
                bottom = bounds.get("bottom", notice_y + h)
                free_bottom = max(free_bottom, bottom)
                notice_y = bottom + 4
        # Leave room before common notes, preserving their saved position offsets.
        current_y += free_bottom - (ticket_bottom if ticket_bottom is not None else current_y)

    phase = "ticket_note"
    s_note = get_s("ticket_note")
    n_gap = styles.get("note_gap", 15)
    current_y += 10 
    for note in common_notes_list:
        if not note: continue
        h = paint_text(
            canvas, note, 
            CANVAS_W // 2 + s_note["pos_x"], current_y - s_note["pos_y"],
            s_note["font_path"], s_note["font_size_px"], CANVAS_W - 60, s_note["fill_color"],
            anchor="ma",
            shadow_on=s_note["shadow_on"], shadow_color=s_note["shadow_color"],
            shadow_blur=s_note["shadow_blur"], shadow_off_x=s_note["shadow_off_x"], shadow_off_y=s_note["shadow_off_y"],
            shadow_opacity=s_note["shadow_opacity"], shadow_spread=s_note["shadow_spread"],
            fallback_font_path=fallback_path
        )
        current_y += h + n_gap

    # ==========================================
    # ★追加: BUZZチケロゴの描画 (一番手前に描画)
    # ==========================================
    if styles.get("show_buzz_logo", False):
        buzz_logo_path = os.path.join("assets", "buzz-logo-appicon.jpg")
        if os.path.exists(buzz_logo_path):
            try:
                # ロゴの読み込みとリサイズ (120x120)
                buzz_img = Image.open(buzz_logo_path).convert("RGBA")
                b_size = 120
                if styles.get("buzz_logo_top_right", False):
                    # Crop only the wordmark from the existing official square asset,
                    # preserving its proportions and omitting the small footer tagline.
                    w, h = buzz_img.size
                    wordmark = buzz_img.crop((0, round(h * .33), w, round(h * .67)))
                    logo_w = 240
                    logo_h = round(wordmark.height * logo_w / wordmark.width)
                    buzz_resized = wordmark.resize((logo_w, logo_h), Image.LANCZOS)
                else:
                    buzz_resized = buzz_img.resize((b_size, b_size), Image.LANCZOS)
                
                # 配置位置 (右下、余白30px)
                margin_x = 30
                margin_y = 30
                paste_x = CANVAS_W - b_size - margin_x
                paste_y = CANVAS_H - b_size - margin_y
                if styles.get("buzz_logo_top_right", False):
                    paste_x, paste_y = CANVAS_W - buzz_resized.width, 0

                # キャンバスに貼り付け
                canvas.paste(buzz_resized, (paste_x, paste_y), buzz_resized)
                boxes['buzz'] = [dict(left=paste_x, top=paste_y, right=paste_x+buzz_resized.width, bottom=paste_y+buzz_resized.height)]
            except Exception as e:
                print(f"BUZZチケロゴの合成エラー: {e}")

    layout_meta['bounds'] = boxes
    return canvas, layout_meta
