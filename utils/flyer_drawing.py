import os
import re
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# ==========================================
# 3. 描画・フォントロジック (コアエンジン)
# ==========================================

def contains_japanese(text):
    """テキストに日本語（ひらがな、カタカナ、漢字）が含まれているか判定"""
    if not text: return False
    # ひらがな: 3040-309F, カタカナ: 30A0-30FF, 漢字: 4E00-9FFF
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
            if fallback_font: use_font = fallback_font
        
        bbox = draw.textbbox((0, 0), char, font=use_font)
        char_w = bbox[2] - bbox[0]
        char_h = bbox[3] - bbox[1] 
        
        # 描画 (drawオブジェクトが渡された場合のみ)
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
    """
    テキストを描画する高機能関数
    - Autoscaling: max_widthに収まるようにフォントサイズを自動縮小
    - Fallback: 日本語が含まれる場合、強制的に日本語フォントを使用するロジックを含む
    - Shadow: 影の描画
    - measure_only: Trueの場合、描画せずに「描画に必要な高さ」だけを返す（レイアウト計算用）
    """
    if not text: return 0
    text_str = str(text)
    
    current_size = int(font_size_px)
    min_size = 10
    
    # 日本語が含まれるかチェック
    has_jp = contains_japanese(text_str)
    
    def load_fonts(size):
        try:
            p_font = ImageFont.truetype(font_path, size) if font_path and os.path.exists(font_path) else ImageFont.load_default()
        except: p_font = ImageFont.load_default()
        
        f_font = p_font
        if fallback_font_path and os.path.exists(fallback_font_path):
            try: f_font = ImageFont.truetype(fallback_font_path, size)
            except: pass
            
        # ★重要修正: 日本語が含まれていて、かつ補助フォントが指定されている場合
        # メインフォント（英語用など）だと豆腐になる可能性があるため、補助フォントを優先する
        if has_jp and f_font != p_font:
            return f_font, f_font 
            
        return p_font, f_font

    primary_font, fallback_font = load_fonts(current_size)
    
    # 計測用のダミー
    dummy_img = Image.new("RGBA", (1, 1))
    dummy_draw = ImageDraw.Draw(dummy_img)
    
    can_resize = True

    # --- Autoscaling Loop ---
    # 指定幅に収まるまでフォントサイズを小さくする
    while can_resize and current_size > min_size:
        w, h = draw_text_mixed(dummy_draw, (0, 0), text_str, primary_font, fallback_font, fill_color)
        # 影の分のマージンを考慮
        margin_est = max(shadow_blur * 3, abs(shadow_off_x), abs(shadow_off_y)) + 10
        
        if w + (margin_est * 2) <= max_width:
            break
            
        current_size -= 2
        primary_font, fallback_font = load_fonts(current_size)

    # 最終的なサイズで計測
    text_w, text_h = draw_text_mixed(dummy_draw, (0, 0), text_str, primary_font, fallback_font, fill_color)
    margin = int(max(shadow_blur * 3, abs(shadow_off_x), abs(shadow_off_y)) + 20)
    
    # measure_only=Trueなら、高さだけ返して終了（レイアウト計算用）
    if measure_only:
        return int(text_h + margin + current_size * 0.2) 

    # --- 本番描画 ---
    canvas_w = int(text_w + margin * 2)
    canvas_h = int(text_h + margin * 2 + current_size * 0.5) 
    
    txt_img = Image.new("RGBA", (canvas_w, canvas_h), (0,0,0,0))
    txt_draw = ImageDraw.Draw(txt_img)
    
    draw_x = margin
    draw_y = margin
    
    draw_text_mixed(txt_draw, (draw_x, draw_y), text_str, primary_font, fallback_font, fill_color)
    
    final_layer = Image.new("RGBA", (canvas_w, canvas_h), (0,0,0,0))
    
    # 影の描画
    if shadow_on:
        alpha = txt_img.getchannel("A")
        shadow_solid = Image.new("RGBA", (canvas_w, canvas_h), shadow_color)
        shadow_solid.putalpha(alpha)
        if shadow_blur > 0:
            shadow_solid = shadow_solid.filter(ImageFilter.GaussianBlur(shadow_blur))
        final_layer.paste(shadow_solid, (shadow_off_x, shadow_off_y), shadow_solid)
        
    final_layer.paste(txt_img, (0, 0), txt_img)
    
    # 最終的な縮小チェック（Autoscalingでも収まらなかった場合の保険）
    content_w = canvas_w
    content_h = canvas_h
    effective_text_w = text_w + (max(abs(shadow_off_x), shadow_blur*2)) 
    
    if effective_text_w > max_width:
        ratio = max_width / effective_text_w
        new_w = int(content_w * ratio)
        new_h = int(content_h * ratio)
        final_layer = final_layer.resize((new_w, new_h), Image.LANCZOS)
        content_w = new_w
        content_h = new_h # 高さも変わる

    # アンカー計算 (配置位置の調整)
    paste_x = x - int(margin * (content_w / canvas_w))
    paste_y = y - margin
    
    if anchor == "ra": # Right Align
        paste_x = x - content_w + int(margin * (content_w / canvas_w))
    elif anchor == "ma": # Middle Align
        paste_x = x - (content_w // 2)

    if base_img:
        base_img.paste(final_layer, (int(paste_x), int(paste_y)), final_layer)
        
    return content_h - margin # 描画した高さを返す

def draw_time_row_aligned(base_img, label, time_str, x, y, font, font_size_px, max_width, fill_color,
                          shadow_on, shadow_color, shadow_blur, shadow_off_x, shadow_off_y, fallback_font_path,
                          tri_visible=True, tri_scale=1.0, tri_color=None,
                          alignment="right", fixed_label_w=0, measure_only=False):
    """
    時間表示（OPEN/START）専用描画
    - 三角形(▶)の位置合わせ機能付き
    """
    fallback_font = font
    if fallback_font_path and os.path.exists(fallback_font_path):
        try: fallback_font = ImageFont.truetype(fallback_font_path, int(font_size_px))
        except: pass

    dummy = ImageDraw.Draw(Image.new("RGBA", (1,1)))
    w_label, h_label = draw_text_mixed(dummy, (0,0), label, font, fallback_font, fill_color)
    w_time, h_time = draw_text_mixed(dummy, (0,0), time_str, font, fallback_font, fill_color)
    
    tri_h = font_size_px * 0.6 * tri_scale
    tri_w = tri_h * 0.8
    tri_padding = font_size_px * 0.3
    
    # コンテンツ幅の計算
    if alignment == "triangle":
        # 三角形の左端を揃えるモード（ラベル幅を固定とみなす）
        total_w_content = fixed_label_w + (tri_w + tri_padding * 2 if tri_visible else tri_padding) + w_time
    else:
        # 通常モード
        total_w_content = w_label + (tri_w + tri_padding * 2 if tri_visible else tri_padding) + w_time
        
    margin = int(max(shadow_blur * 3, abs(shadow_off_x), abs(shadow_off_y)) + 20)
    canvas_h = int(max(h_label, h_time, tri_h) + margin * 2 + font_size_px * 0.5)
    
    if measure_only:
        return canvas_h - (margin * 2) # 概算高さだけ返す

    canvas_w = int(total_w_content + margin * 2)
    txt_img = Image.new("RGBA", (canvas_w, canvas_h), (0,0,0,0))
    draw = ImageDraw.Draw(txt_img)
    
    cur_x = margin
    draw_y = margin
    
    # ラベル描画
    if alignment == "triangle":
        # 右寄せして描画
        label_draw_x = cur_x + (fixed_label_w - w_label)
        draw_text_mixed(draw, (label_draw_x, draw_y), label, font, fallback_font, fill_color)
        cur_x += fixed_label_w
    else:
        draw_text_mixed(draw, (cur_x, draw_y), label, font, fallback_font, fill_color)
        cur_x += w_label
    
    # 三角形描画
    if tri_visible:
        cur_x += tri_padding
        cy = draw_y + (font_size_px * 0.5)
        ty = cy - (tri_h / 2)
        by = cy + (tri_h / 2)
        lx = cur_x
        rx = cur_x + tri_w
        t_col = tri_color if tri_color else fill_color
        draw.polygon([(lx, ty), (lx, by), (rx, cy)], fill=t_col)
        cur_x += tri_w + tri_padding
    else:
        cur_x += tri_padding

    # 時間テキスト描画
    draw_text_mixed(draw, (cur_x, draw_y), time_str, font, fallback_font, fill_color)
    
    final_layer = Image.new("RGBA", (canvas_w, canvas_h), (0,0,0,0))
    
    # 影
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
    else: # left
        paste_x = x - margin
    
    if base_img:
        base_img.paste(final_layer, (int(paste_x), int(paste_y)), final_layer)
        
    return max(h_label, h_time)
