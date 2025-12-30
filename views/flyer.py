import streamlit as st
from PIL import Image, ImageDraw, ImageFont
import io
import os
import requests
from constants import FONT_DIR
from database import get_db, TimetableProject, Asset, get_image_url

# ==========================================
# 1. ヘルパー関数群
# ==========================================

def load_image_from_source(source):
    """パス(str), URL(str), ImageオブジェクトなどからRGBA画像を生成"""
    if source is None:
        return None
    try:
        if isinstance(source, Image.Image):
            return source.convert("RGBA")
        
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
    """幅に合わせてアスペクト比固定でリサイズ"""
    w_percent = (target_width / float(img.size[0]))
    h_size = int((float(img.size[1]) * float(w_percent)))
    return img.resize((target_width, h_size), Image.LANCZOS)

def format_event_date(dt_obj):
    """日付を YYYY.MM.DD.WDY 形式にする"""
    if not dt_obj: return ""
    if isinstance(dt_obj, str): return dt_obj
    weekdays = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
    return f"{dt_obj.strftime('%Y.%m.%d')}.{weekdays[dt_obj.weekday()]}"

def format_time_str(t_val):
    """時間を HH:MM 形式にする"""
    if not t_val: return ""
    if isinstance(t_val, str): return t_val[:5]
    try: return t_val.strftime("%H:%M")
    except: return str(t_val)

# --- ★追加: 安全なフォントプレビュー生成関数 (エラー回避用) ---
def local_create_font_preview(font_path, text="Preview", width=400, height=50):
    try:
        img = Image.new("RGBA", (width, height), (0,0,0,0)) # 透明背景
        draw = ImageDraw.Draw(img)
        try:
            # 高さに合わせてフォントサイズ調整
            font_size = int(height * 0.8)
            font = ImageFont.truetype(font_path, font_size)
        except:
            font = ImageFont.load_default()
        
        # 中央配置
        bbox = draw.textbbox((0, 0), text, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        x = (width - text_w) // 2
        y = (height - text_h) // 2
        
        draw.text((x, y), text, font=font, fill="white")
        return img
    except Exception as e:
        print(f"Font Preview Error: {e}")
        return None

# ==========================================
# 2. UI コンポーネント (画像選択)
# ==========================================

def render_visual_selector(label, assets, key_prefix, current_id, allow_none=False):
    """画像をグリッド表示して選択させるUI"""
    st.markdown(f"**{label}**")
    
    # "なし" の選択肢
    if allow_none:
        if st.button("🚫 設定なし", key=f"btn_none_{key_prefix}", type="secondary" if current_id != 0 else "primary"):
            st.session_state[key_prefix] = 0
            st.rerun()

    if not assets:
        st.info("画像が見つかりません。")
        return

    # 4列で表示
    cols = st.columns(4)
    for i, asset in enumerate(assets):
        with cols[i % 4]:
            # 画像表示
            img_url = get_image_url(asset.image_filename)
            st.image(img_url, use_container_width=True)
            
            # 選択ボタン (選択中はPrimary色)
            is_selected = (asset.id == current_id)
            btn_label = "✅ 選択中" if is_selected else "選択"
            btn_type = "primary" if is_selected else "secondary"
            
            if st.button(btn_label, key=f"btn_{key_prefix}_{asset.id}", type=btn_type, use_container_width=True):
                st.session_state[key_prefix] = asset.id
                st.rerun()

# ==========================================
# 3. フライヤー生成ロジック
# ==========================================

def create_flyer_image_v2(
    bg_source, logo_source, main_source,
    basic_font_path, text_color, stroke_color,
    date_text, venue_text, open_time, start_time,
    ticket_info_list, free_text_list
):
    # 1. 背景読み込み
    base_img = load_image_from_source(bg_source)
    if base_img is None: return None
    
    W, H = base_img.size
    draw = ImageDraw.Draw(base_img)
    
    # 2. フォント設定
    try:
        f_date = ImageFont.truetype(basic_font_path, int(W * 0.09))
        f_venue = ImageFont.truetype(basic_font_path, int(W * 0.05))
        f_label = ImageFont.truetype(basic_font_path, int(W * 0.04))
        f_time = ImageFont.truetype(basic_font_path, int(W * 0.06))
        f_ticket_name = ImageFont.truetype(basic_font_path, int(W * 0.05))
        f_note = ImageFont.truetype(basic_font_path, int(W * 0.025))
    except:
        f_date = f_venue = f_label = f_time = f_ticket_name = f_note = ImageFont.load_default()

    padding_x = int(W * 0.05)
    current_y = int(H * 0.05)

    # A. ロゴ
    logo_img = load_image_from_source(logo_source)
    if logo_img:
        logo_w = int(W * 0.8)
        logo_img = resize_image_to_width(logo_img, logo_w)
        logo_x = (W - logo_img.width) // 2
        base_img.paste(logo_img, (logo_x, current_y), logo_img)
        current_y += logo_img.height + int(H * 0.02)
    else:
        current_y += int(H * 0.15)

    # B. 日時・会場・OPEN/START
    info_y_start = current_y
    
    # 左側: 日付・会場
    draw.text((padding_x, info_y_start), str(date_text), fill=text_color, font=f_date, anchor="la", stroke_width=2, stroke_fill=stroke_color)
    date_bbox = draw.textbbox((0, 0), str(date_text), font=f_date)
    date_h = date_bbox[3] - date_bbox[1]
    venue_y = info_y_start + date_h + int(H * 0.01)
    draw.text((padding_x, venue_y), str(venue_text), fill=text_color, font=f_venue, anchor="la", stroke_width=2, stroke_fill=stroke_color)

    # 右側: OPEN/START
    right_x = W - padding_x
    o_time_str = str(open_time) if open_time else ""
    s_time_str = str(start_time) if start_time else ""

    draw.text((right_x, info_y_start), o_time_str, fill=text_color, font=f_time, anchor="ra", stroke_width=2, stroke_fill=stroke_color)
    time_bbox = draw.textbbox((0,0), o_time_str, font=f_time)
    draw.text((right_x - (time_bbox[2]-time_bbox[0]) - 20, info_y_start + 10), "OPEN ▶", fill=text_color, font=f_label, anchor="ra", stroke_width=1, stroke_fill=stroke_color)

    start_y = info_y_start + (time_bbox[3] - time_bbox[1]) + int(H * 0.01)
    draw.text((right_x, start_y), s_time_str, fill=text_color, font=f_time, anchor="ra", stroke_width=2, stroke_fill=stroke_color)
    draw.text((right_x - (time_bbox[2]-time_bbox[0]) - 20, start_y + 10), "START ▶", fill=text_color, font=f_label, anchor="ra", stroke_width=1, stroke_fill=stroke_color)

    current_y = max(venue_y + int(H * 0.05), start_y + int(H * 0.05)) + int(H * 0.02)

    # C. アー写グリッド
    main_img = load_image_from_source(main_source)
    if main_img:
        grid_target_w = int(W * 0.95)
        main_img = resize_image_to_width(main_img, grid_target_w)
        grid_x = (W - main_img.width) // 2
        base_img.paste(main_img, (grid_x, current_y), main_img)
        current_y += main_img.height + int(H * 0.03)

    # D. チケット & 注釈
    for ticket in ticket_info_list:
        line = f"{ticket['name']} {ticket['price']}"
        if ticket.get('note'): line += f" ({ticket['note']})"
        draw.text((W//2, current_y), line, fill=text_color, font=f_ticket_name, anchor="ma", stroke_width=2, stroke_fill=stroke_color)
        current_y += int(H * 0.05)

    current_y += int(H * 0.01)
    for txt in free_text_list:
        if txt.get('content'):
            draw.text((W//2, current_y), txt.get('content'), fill=text_color, font=f_note, anchor="ma")
            current_y += int(H * 0.03)

    return base_img

# ==========================================
# 4. メイン画面描画
# ==========================================

def render_flyer_editor(project_id):
    db = next(get_db())
    proj = db.query(TimetableProject).filter(TimetableProject.id == project_id).first()
    
    # 削除されていないアセットを取得
    logos = db.query(Asset).filter(Asset.asset_type == "logo", Asset.is_deleted == False).all()
    bgs = db.query(Asset).filter(Asset.asset_type == "background", Asset.is_deleted == False).all()
    
    if not proj:
        st.error("プロジェクトエラー")
        db.close()
        return

    st.subheader("📑 フライヤー生成 (NEWデザイン)")

    # 初期化
    if "flyer_bg_id" not in st.session_state:
        st.session_state.flyer_bg_id = bgs[0].id if bgs else 0
    if "flyer_logo_id" not in st.session_state:
        st.session_state.flyer_logo_id = 0
    if "flyer_result_grid" not in st.session_state: st.session_state.flyer_result_grid = None
    if "flyer_result_tt" not in st.session_state: st.session_state.flyer_result_tt = None

    c_conf, c_prev = st.columns([1, 1])

    with c_conf:
        # --- 1. 背景選択 (画像一覧) ---
        with st.expander("1. 背景画像を選択", expanded=True):
            render_visual_selector("背景", bgs, "flyer_bg_id", st.session_state.flyer_bg_id)

        # --- 2. ロゴ選択 (画像一覧) ---
        with st.expander("2. ロゴ画像を選択", expanded=False):
            render_visual_selector("ロゴ", logos, "flyer_logo_id", st.session_state.flyer_logo_id, allow_none=True)

        # --- 3. フォント・色 (プレビュー付き) ---
        with st.expander("3. フォント・色設定", expanded=True):
            all_fonts = [f for f in os.listdir(FONT_DIR) if f.lower().endswith(".ttf")]
            if not all_fonts: all_fonts = ["default"]

            font_choice = st.selectbox("フォント", all_fonts, key="flyer_basic_font")
            
            # ★フォントプレビュー表示 (エラー回避版)
            if font_choice != "default":
                preview_path = os.path.join(FONT_DIR, font_choice)
                prev_img = local_create_font_preview(preview_path, text="OPEN 18:30 / START 19:00")
                if prev_img:
                    st.image(prev_img, caption="フォントプレビュー", use_container_width=True)

            c1, c2 = st.columns(2)
            with c1: st.color_picker("文字色", "#FFFFFF", key="flyer_text_color")
            with c2: st.color_picker("縁取り色", "#000000", key="flyer_stroke_color")

        st.divider()

        if st.button("🚀 画像を生成する", type="primary", use_container_width=True):
            # Asset取得
            bg_id = st.session_state.flyer_bg_id
            logo_id = st.session_state.flyer_logo_id
            
            # 安全にURL取得
            bg_url = None
            if bg_id:
                bg_asset = db.query(Asset).get(bg_id)
                if bg_asset: bg_url = get_image_url(bg_asset.image_filename)
            
            logo_url = None
            if logo_id:
                logo_asset = db.query(Asset).get(logo_id)
                if logo_asset: logo_url = get_image_url(logo_asset.image_filename)
            
            font_path = os.path.join(FONT_DIR, st.session_state.flyer_basic_font)
            
            # DB情報取得
            tickets = st.session_state.get("proj_tickets", [])
            free_texts = st.session_state.get("proj_free_text", [])
            
            args = {
                "bg_source": bg_url,
                "logo_source": logo_url,
                "basic_font_path": font_path,
                "text_color": st.session_state.flyer_text_color,
                "stroke_color": st.session_state.flyer_stroke_color,
                "date_text": format_event_date(proj.event_date),
                "venue_text": proj.venue,
                "open_time": format_time_str(proj.open_time),
                "start_time": format_time_str(proj.start_time),
                "ticket_info_list": tickets,
                "free_text_list": free_texts
            }

            with st.spinner("生成中..."):
                # Grid版
                grid_src = st.session_state.get("last_generated_grid_image")
                if grid_src:
                    st.session_state.flyer_result_grid = create_flyer_image_v2(main_source=grid_src, **args)
                # TT版
                tt_src = st.session_state.get("last_generated_tt_image")
                if tt_src:
                    st.session_state.flyer_result_tt = create_flyer_image_v2(main_source=tt_src, **args)

            st.success("生成完了！")

    # --- プレビューエリア ---
    with c_prev:
        st.markdown("##### 生成結果")
        t1, t2 = st.tabs(["アー写グリッド版", "タイムテーブル版"])
        
        with t1:
            if st.session_state.flyer_result_grid:
                st.image(st.session_state.flyer_result_grid, use_container_width=True)
                buf = io.BytesIO()
                st.session_state.flyer_result_grid.save(buf, format="PNG")
                st.download_button("DL (Grid)", buf.getvalue(), "flyer_grid.png", "image/png", type="primary")
            else:
                st.info("「アー写グリッド」タブで画像を生成してください")

        with t2:
            if st.session_state.flyer_result_tt:
                st.image(st.session_state.flyer_result_tt, use_container_width=True)
                buf = io.BytesIO()
                st.session_state.flyer_result_tt.save(buf, format="PNG")
                st.download_button("DL (TT)", buf.getvalue(), "flyer_tt.png", "image/png", type="primary")
            else:
                st.info("「タイムテーブル」タブで画像を生成してください")

    db.close()
