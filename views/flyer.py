import streamlit as st
from PIL import Image, ImageDraw, ImageFont
import io
import os
import requests
import json
from constants import FONT_DIR
from database import get_db, TimetableProject, Asset, get_image_url

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

def resize_image_to_width(img, target_width):
    if not img: return None
    w_percent = (target_width / float(img.size[0]))
    h_size = int((float(img.size[1]) * float(w_percent)))
    return img.resize((target_width, h_size), Image.LANCZOS)

def resize_image_contain(img, max_w, max_h):
    """指定した枠内に収まるようにリサイズ"""
    if not img: return None
    ratio = min(max_w / img.width, max_h / img.height)
    new_w = int(img.width * ratio)
    new_h = int(img.height * ratio)
    return img.resize((new_w, new_h), Image.LANCZOS)

def format_event_date(dt_obj):
    if not dt_obj: return ""
    if isinstance(dt_obj, str): return dt_obj
    try:
        weekdays = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
        return f"{dt_obj.strftime('%Y.%m.%d')}.{weekdays[dt_obj.weekday()]}"
    except:
        return str(dt_obj)

def format_time_str(t_val):
    if not t_val or t_val == 0 or t_val == "0": return ""
    if isinstance(t_val, str): return t_val[:5]
    try: return t_val.strftime("%H:%M")
    except: return str(t_val)

def local_create_font_preview(font_path, text="Preview", width=400, height=50):
    try:
        img = Image.new("RGBA", (width, height), (0,0,0,0))
        draw = ImageDraw.Draw(img)
        try:
            font_size = int(height * 0.8)
            font = ImageFont.truetype(font_path, font_size)
        except:
            font = ImageFont.load_default()
        bbox = draw.textbbox((0, 0), text, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        x = (width - text_w) // 2
        y = (height - text_h) // 2 - bbox[1]
        draw.text((x, y), text, font=font, fill="white")
        return img
    except: return None

# --- ★新機能: テキストを長体（横につぶす）で描画する関数 ---
def draw_text_squeezed(base_img, text, x, y, font, max_width, fill, stroke_width=0, stroke_fill=None, anchor="la"):
    """
    指定幅(max_width)を超えたら、画像を縮小(長体)して描画する。
    anchor: 'la' (左上基準), 'ra' (右上基準), 'ma' (中央上基準) 対応
    """
    if not text: return y
    
    # 1. テキストの本来のサイズを計測
    dummy_img = Image.new("RGBA", (1, 1))
    dummy_draw = ImageDraw.Draw(dummy_img)
    bbox = dummy_draw.textbbox((0, 0), text, font=font, stroke_width=stroke_width)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    
    # 余白を含めたキャンバス作成
    canvas_w = text_w + abs(bbox[0]) # 左のはみ出しケア
    canvas_h = text_h + abs(bbox[1]) + stroke_width * 2
    
    # 2. テキスト描画用の一時画像を作成
    txt_img = Image.new("RGBA", (canvas_w, canvas_h), (0,0,0,0))
    txt_draw = ImageDraw.Draw(txt_img)
    # 一時画像の (0, 0) ではなく、bboxのオフセット分ずらして描画
    draw_x = -bbox[0]
    draw_y = -bbox[1]
    txt_draw.text((draw_x, draw_y), text, font=font, fill=fill, stroke_width=stroke_width, stroke_fill=stroke_fill)
    
    # 3. 幅が最大値を超えていたらリサイズ（長体処理）
    final_w = canvas_w
    final_h = canvas_h
    if canvas_w > max_width:
        final_w = max_width
        txt_img = txt_img.resize((final_w, final_h), Image.LANCZOS)
    
    # 4. ベース画像に貼り付け (アンカー計算)
    paste_x = x
    paste_y = y
    
    if anchor == "ra":   # 右揃え
        paste_x = x - final_w
    elif anchor == "ma": # 中央揃え
        paste_x = x - (final_w // 2)
    # "la" は x そのまま
    
    base_img.paste(txt_img, (paste_x, paste_y), txt_img)
    
    return final_h # 描画した高さを返す

# ==========================================
# 2. UI コンポーネント
# ==========================================

def render_visual_selector(label, assets, key_prefix, current_id, allow_none=False):
    st.markdown(f"**{label}**")
    if allow_none:
        is_none = (not current_id or current_id == 0)
        if st.button("🚫 設定なし", key=f"btn_none_{key_prefix}", type="primary" if is_none else "secondary"):
            st.session_state[key_prefix] = 0
            st.rerun()

    if not assets:
        st.info("画像が見つかりません。")
        return

    cols = st.columns(4)
    for i, asset in enumerate(assets):
        with cols[i % 4]:
            st.image(get_image_url(asset.image_filename), use_container_width=True)
            is_sel = (asset.id == current_id)
            if st.button("✅ 選択中" if is_sel else "選択", key=f"btn_{key_prefix}_{asset.id}", type="primary" if is_sel else "secondary", use_container_width=True):
                st.session_state[key_prefix] = asset.id
                st.rerun()

# ==========================================
# 3. フライヤー生成ロジック (配置改善版)
# ==========================================

def create_flyer_image_v2(
    bg_source, logo_source, main_source,
    basic_font_path, text_color, stroke_color,
    date_text, venue_text, open_time, start_time,
    ticket_info_list, free_text_list
):
    # 1. 背景
    base_img = load_image_from_source(bg_source)
    if base_img is None: return None
    W, H = base_img.size
    
    # 2. フォント設定
    try:
        f_date = ImageFont.truetype(basic_font_path, int(W * 0.09))
        f_venue = ImageFont.truetype(basic_font_path, int(W * 0.05))
        f_label = ImageFont.truetype(basic_font_path, int(W * 0.04))
        f_time = ImageFont.truetype(basic_font_path, int(W * 0.06))
        f_ticket_name = ImageFont.truetype(basic_font_path, int(W * 0.045)) # 少し小さく調整
        f_note = ImageFont.truetype(basic_font_path, int(W * 0.025))
    except:
        f_date = f_venue = f_label = f_time = f_ticket_name = f_note = ImageFont.load_default()

    padding_x = int(W * 0.05)
    current_y = int(H * 0.05)

    # ==========================
    # A. ロゴ (縮小: 50%)
    # ==========================
    logo_img = load_image_from_source(logo_source)
    if logo_img:
        logo_w = int(W * 0.5) # ★サイズ変更: 50%
        logo_img = resize_image_to_width(logo_img, logo_w)
        logo_x = (W - logo_img.width) // 2
        base_img.paste(logo_img, (logo_x, current_y), logo_img)
        current_y += logo_img.height + int(H * 0.02)
    else:
        current_y += int(H * 0.10)

    header_bottom_y = current_y # ここから日時などを描画

    # ==========================
    # B. 日時・会場 (長体適用)
    # ==========================
    
    # 左エリアの最大幅 (全体の50%程度)
    left_max_w = int(W * 0.55)
    
    # 日時
    h_date = draw_text_squeezed(base_img, str(date_text), padding_x, current_y, f_date, left_max_w, text_color, 2, stroke_color, "la")
    
    # 会場 (日時のすぐ下)
    venue_y = current_y + h_date + int(H * 0.005)
    h_venue = draw_text_squeezed(base_img, str(venue_text), padding_x, venue_y, f_venue, left_max_w, text_color, 2, stroke_color, "la")
    
    header_end_y = venue_y + h_venue # ヘッダー情報の終わり位置

    # ==========================
    # C. OPEN / START (右側)
    # ==========================
    right_x = W - padding_x
    right_max_w = int(W * 0.35)
    
    o_time_str = str(open_time) if open_time else ""
    s_time_str = str(start_time) if start_time else ""

    # OPEN
    h_open = draw_text_squeezed(base_img, o_time_str, right_x, current_y, f_time, right_max_w, text_color, 2, stroke_color, "ra")
    
    # ラベル "OPEN ▶" (時間の左)
    # 時間の描画幅を簡易計算して左に配置するのは複雑なので、少し固定オフセットで配置
    # 時間文字が長体かかると位置がずれるため、おおよその位置に配置
    draw = ImageDraw.Draw(base_img)
    lbl_bbox = draw.textbbox((0,0), "OPEN ▶", font=f_label)
    lbl_w = lbl_bbox[2] - lbl_bbox[0]
    # 簡易的に右端から少し離す
    draw_text_squeezed(base_img, "OPEN ▶", right_x - int(W*0.25), current_y + 10, f_label, int(W*0.15), text_color, 1, stroke_color, "ra")

    # START (OPENの下)
    start_y = current_y + h_open + int(H * 0.01)
    draw_text_squeezed(base_img, s_time_str, right_x, start_y, f_time, right_max_w, text_color, 2, stroke_color, "ra")
    draw_text_squeezed(base_img, "START ▶", right_x - int(W*0.25), start_y + 10, f_label, int(W*0.15), text_color, 1, stroke_color, "ra")

    header_end_y = max(header_end_y, start_y + int(H*0.08)) + int(H * 0.02)

    # ==========================
    # D. フッター高さ計算 (チケット情報)
    # ==========================
    # チケット情報を下から積み上げるために、必要な高さを計算
    # ※実際に描画はせず、高さだけシミュレーション
    
    footer_lines = []
    # チケット
    for ticket in ticket_info_list:
        line = f"{ticket.get('name','')} {ticket.get('price','')}"
        if ticket.get('note'): line += f" ({ticket.get('note')})"
        footer_lines.append({"text": line, "font": f_ticket_name, "gap": int(H * 0.05)})
    
    # 注釈
    for txt in free_text_list:
        c = txt.get('content','')
        if c: footer_lines.append({"text": c, "font": f_note, "gap": int(H * 0.03)})
    
    # フッターの総高さを計算
    footer_total_h = int(H * 0.05) # 下部パディング
    for item in reversed(footer_lines):
        bbox = draw.textbbox((0,0), item["text"], font=item["font"])
        h = bbox[3] - bbox[1]
        footer_total_h += h + item["gap"]

    footer_start_y = H - footer_total_h
    
    # ==========================
    # E. メイン画像 (グリッド/TT)
    # ==========================
    # ヘッダー終わり 〜 フッター開始 の間に画像を収める
    
    available_h = footer_start_y - header_end_y - int(H * 0.02)
    
    main_img = load_image_from_source(main_source)
    if main_img and available_h > 100:
        # 幅は95%、高さは空きスペースに合わせる
        target_w = int(W * 0.95)
        main_img = resize_image_contain(main_img, target_w, available_h)
        
        grid_x = (W - main_img.width) // 2
        # 中央配置
        grid_y = header_end_y + (available_h - main_img.height) // 2
        
        base_img.paste(main_img, (grid_x, int(grid_y)), main_img)

    # ==========================
    # F. フッター描画 (チケット等)
    # ==========================
    # 今度は実際に描画
    current_footer_y = footer_start_y + int(H * 0.02)
    
    for item in footer_lines:
        draw_text_squeezed(base_img, item["text"], W//2, current_footer_y, item["font"], int(W*0.9), text_color, 2, stroke_color, "ma")
        # 高さ分進める
        bbox = draw.textbbox((0,0), item["text"], font=item["font"])
        h = bbox[3] - bbox[1]
        current_footer_y += h + item["gap"]

    return base_img

# ==========================================
# 4. メイン画面描画
# ==========================================

def render_flyer_editor(project_id):
    db = next(get_db())
    proj = db.query(TimetableProject).filter(TimetableProject.id == project_id).first()
    
    logos = db.query(Asset).filter(Asset.asset_type == "logo", Asset.is_deleted == False).all()
    bgs = db.query(Asset).filter(Asset.asset_type == "background", Asset.is_deleted == False).all()
    
    if not proj:
        st.error("プロジェクトエラー")
        db.close()
        return

    st.subheader("📑 フライヤー生成 (NEWデザイン)")

    # 設定ロード
    saved_config = {}
    if getattr(proj, "flyer_json", None):
        try:
            if isinstance(proj.flyer_json, str): saved_config = json.loads(proj.flyer_json)
            elif isinstance(proj.flyer_json, dict): saved_config = proj.flyer_json
        except: pass
    
    if "flyer_bg_id" not in st.session_state:
        st.session_state.flyer_bg_id = int(saved_config.get("bg_id", bgs[0].id if bgs else 0))
    if "flyer_logo_id" not in st.session_state:
        st.session_state.flyer_logo_id = int(saved_config.get("logo_id", 0))
    if "flyer_basic_font" not in st.session_state:
        st.session_state.flyer_basic_font = saved_config.get("font", "keifont.ttf")
    if "flyer_text_color" not in st.session_state:
        st.session_state.flyer_text_color = saved_config.get("text_color", "#FFFFFF")
    if "flyer_stroke_color" not in st.session_state:
        st.session_state.flyer_stroke_color = saved_config.get("stroke_color", "#000000")

    if "flyer_result_grid" not in st.session_state: st.session_state.flyer_result_grid = None
    if "flyer_result_tt" not in st.session_state: st.session_state.flyer_result_tt = None

    c_conf, c_prev = st.columns([1, 1])

    with c_conf:
        with st.expander("1. 背景画像を選択", expanded=True):
            render_visual_selector("背景", bgs, "flyer_bg_id", st.session_state.flyer_bg_id)
        
        with st.expander("2. ロゴ画像を選択", expanded=False):
            render_visual_selector("ロゴ", logos, "flyer_logo_id", st.session_state.flyer_logo_id, allow_none=True)

        with st.expander("3. フォント・色設定", expanded=True):
            all_fonts = [f for f in os.listdir(FONT_DIR) if f.lower().endswith(".ttf")]
            if not all_fonts: all_fonts = ["default"]
            
            cur_font = st.session_state.flyer_basic_font
            if cur_font not in all_fonts: cur_font = all_fonts[0]
            
            font_choice = st.selectbox("フォント", all_fonts, index=all_fonts.index(cur_font), key="flyer_basic_font")
            if font_choice != "default":
                prev_img = local_create_font_preview(os.path.join(FONT_DIR, font_choice), "OPEN 18:30 / START 19:00")
                if prev_img: st.image(prev_img, use_container_width=True)

            c1, c2 = st.columns(2)
            with c1: st.color_picker("文字色", st.session_state.flyer_text_color, key="flyer_text_color")
            with c2: st.color_picker("縁取り色", st.session_state.flyer_stroke_color, key="flyer_stroke_color")

        c_act1, c_act2 = st.columns(2)
        with c_act1:
            if st.button("💾 設定を保存する", use_container_width=True):
                config_data = {
                    "bg_id": st.session_state.flyer_bg_id,
                    "logo_id": st.session_state.flyer_logo_id,
                    "font": st.session_state.flyer_basic_font,
                    "text_color": st.session_state.flyer_text_color,
                    "stroke_color": st.session_state.flyer_stroke_color
                }
                if hasattr(proj, "flyer_json"):
                    try:
                        proj.flyer_json = json.dumps(config_data)
                        db.commit()
                        st.success("保存しました！")
                    except Exception as e: st.error(f"エラー: {e}")
                else: st.warning("保存カラムなし")

        with c_act2:
            if st.button("🚀 画像を生成する", type="primary", use_container_width=True):
                bg_id = st.session_state.flyer_bg_id
                logo_id = st.session_state.flyer_logo_id
                
                bg_url = None
                if bg_id:
                    bg_asset = db.query(Asset).get(bg_id)
                    if bg_asset: bg_url = get_image_url(bg_asset.image_filename)
                
                logo_url = None
                if logo_id:
                    logo_asset = db.query(Asset).get(logo_id)
                    if logo_asset: logo_url = get_image_url(logo_asset.image_filename)
                
                font_path = os.path.join(FONT_DIR, st.session_state.flyer_basic_font)
                
                v_text = getattr(proj, "venue_name", "") or getattr(proj, "venue", "") or ""
                
                args = {
                    "bg_source": bg_url,
                    "logo_source": logo_url,
                    "basic_font_path": font_path,
                    "text_color": st.session_state.flyer_text_color,
                    "stroke_color": st.session_state.flyer_stroke_color,
                    "date_text": format_event_date(proj.event_date),
                    "venue_text": v_text,
                    "open_time": format_time_str(proj.open_time),
                    "start_time": format_time_str(proj.start_time),
                    "ticket_info_list": st.session_state.get("proj_tickets", []),
                    "free_text_list": st.session_state.get("proj_free_text", [])
                }
                
                # DB読み込みフォールバック
                if not args["ticket_info_list"] and getattr(proj, "tickets_json", None):
                    try: args["ticket_info_list"] = json.loads(proj.tickets_json)
                    except: pass
                if not args["free_text_list"] and getattr(proj, "free_text_json", None):
                    try: args["free_text_list"] = json.loads(proj.free_text_json)
                    except: pass

                with st.spinner("生成中..."):
                    grid_src = st.session_state.get("last_generated_grid_image")
                    if grid_src:
                        st.session_state.flyer_result_grid = create_flyer_image_v2(main_source=grid_src, **args)
                    
                    tt_src = st.session_state.get("last_generated_tt_image")
                    if tt_src:
                        st.session_state.flyer_result_tt = create_flyer_image_v2(main_source=tt_src, **args)

                st.success("完了！")

    with c_prev:
        st.markdown("##### 生成結果")
        t1, t2 = st.tabs(["アー写グリッド版", "タイムテーブル版"])
        with t1:
            if st.session_state.flyer_result_grid:
                st.image(st.session_state.flyer_result_grid, use_container_width=True)
                buf = io.BytesIO()
                st.session_state.flyer_result_grid.save(buf, format="PNG")
                st.download_button("DL (Grid)", buf.getvalue(), "flyer_grid.png", "image/png", type="primary")
            else: st.info("アー写グリッドタブで画像を生成してください")
        with t2:
            if st.session_state.flyer_result_tt:
                st.image(st.session_state.flyer_result_tt, use_container_width=True)
                buf = io.BytesIO()
                st.session_state.flyer_result_tt.save(buf, format="PNG")
                st.download_button("DL (TT)", buf.getvalue(), "flyer_tt.png", "image/png", type="primary")
            else: st.info("タイムテーブルタブで画像を生成してください")

    db.close()
