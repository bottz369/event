import os
import re
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# ==========================================
# 3. 描画・フォントロジック (コアエンジン)
# ==========================================

def contains_japanese(text):
    """テキストに日本語（ひらがな、カタカナ、漢字）が含まれているか判定"""
    if not text: return False
    return bool(re.search(r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]', str(text)))

def is_glyph_available(font, char):
    """フォントに特定の文字(グリフ)が含まれているか判定"""
    if char.isspace() or ord(char) < 32: return True
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
        # メインフォントに文字がない場合はフォールバックを使用
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
                          anchor="la", 
                          shadow_on=False, shadow_color="#000000", shadow_blur=0, shadow_off_x=5, shadow_off_y=5,
                          fallback_font_path=None, measure_only=False):
    if not text: return 0
    text_str = str(text)
    
    current_size = int(font_size_px)
    min_size = 10
    
    # フォントロード関数 (サイズを引数に取る)
    def load_fonts(size):
        # メインフォント
        try:
            p_font = ImageFont.truetype(font_path, size) if font_path and os.path.exists(font_path) else ImageFont.load_default()
        except:
            p_font = ImageFont.load_default()
        
        # 補助フォント (★修正点: ここで size を確実に渡すことでサイズ適用バグを解消)
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
    
    # 実際の描画 (draw_text_mixed で文字ごとにフォントを切り替え)
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

    paste_x = x - int(margin * (content_w / canvas_w))
    paste_y = y - margin
    
    if anchor == "ra":
        paste_x = x - content_w + int(margin * (content_w / canvas_w))
    elif anchor == "ma":
        paste_x = x - (content_w // 2)

    if base_img:
        base_img.paste(final_layer, (int(paste_x), int(paste_y)), final_layer)
        
    return content_h - margin

def draw_time_row_aligned(base_img, label, time_str, x, y, font, font_size_px, max_width, fill_color,
                          shadow_on, shadow_color, shadow_blur, shadow_off_x, shadow_off_y, fallback_font_path,
                          tri_visible=True, tri_scale=1.0, tri_color=None,
                          alignment="right", fixed_label_w=0, measure_only=False):
    
    # フォント準備 (ここでもfallback_fontにサイズを適用)
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
    paste_x = x
    paste_y = y - margin
    
    if alignment == "right" or alignment == "triangle":
        paste_x = x - canvas_w + margin
    elif alignment == "center":
        paste_x = x - (canvas_w // 2) + margin
    else:
        paste_x = x - margin
    
    if base_img:
        base_img.paste(final_layer, (int(paste_x), int(paste_y)), final_layer)
        
    return max(h_label, h_time)
                              
