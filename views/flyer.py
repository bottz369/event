import streamlit as st
from PIL import Image, ImageDraw, ImageFont
import io
import os
import requests
import json
import datetime
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
    if not img: return None
    w_percent = (target_width / float(img.size[0]))
    h_size = int((float(img.size[1]) * float(w_percent)))
    return img.resize((target_width, h_size), Image.LANCZOS)

def format_event_date(dt_obj):
    """日付を YYYY.MM.DD.WDY 形式にする"""
    if not dt_obj: return ""
    if isinstance(dt_obj, str): return dt_obj
    
    try:
        # datetime.date または datetime.datetime の場合
        weekdays = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
        return f"{dt_obj.strftime('%Y.%m.%d')}.{weekdays[dt_obj.weekday()]}"
    except:
        return str(dt_obj)

def format_time_str(t_val):
    """時間を HH:MM 形式にする (intの0やNoneも安全に処理)"""
    if not t_val: return ""
    if t_val == 0 or t_val == "0": return ""
    
    if isinstance(t_val, str):
        # "10:30:00" -> "10:30"
        return t_val[:5]
    
    try:
        # timeオブジェクトの場合
        return t_val.strftime("%H:%M")
    except:
        return str(t_val)

def local_create_font_preview(font_path, text="Preview", width=400, height=50):
    """フォントプレビュー画像を生成"""
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
    except Exception as e:
        print(f"Font Preview Error: {e}")
        return None

# ==========================================
# 2. UI コンポーネント
# ==========================================

def render_visual_selector(label, assets, key_prefix, current_id, allow_none=False):
    """画像をグリッド表示して選択させるUI"""
    st.markdown(f"**{label}**")
    
    if allow_none:
        # IDが0またはNoneなら「設定なし」が選択状態
        is_none_selected = (not current_id or current_id == 0)
        if st.button("🚫 設定なし", key=f"btn_none_{key_prefix}", type="primary" if is_none_selected else "secondary"):
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
    # 1. 背景
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
    
    # 日時
    draw.text((padding_x, info_y_start), str(date_text), fill=text_color, font=f_date, anchor="la", stroke_width=2, stroke_fill=stroke_color)
    date_bbox = draw.textbbox((0, 0), str(date_text), font=f_date)
    date_h = date_bbox[3] - date_bbox[1]
    
    # 会場
    venue_y = info_y_start + date_h + int(H * 0.01)
    draw.text((padding_x, venue_y), str(venue_text), fill=text_color, font=f_venue, anchor="la", stroke_width=2, stroke_fill=stroke_color)

    # 右側 (OPEN/START)
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

    # C. アー写グリッド (またはTT画像)
    main_img = load_image_from_source(main_source)
    if main_img:
        grid_target_w = int(W * 0.95)
        main_img = resize_image_to_width(main_img, grid_target_w)
        grid_x = (W - main_img.width) // 2
        base_img.paste(main_img, (grid_x, current_y), main_img)
        current_y += main_img.height + int(H * 0.03)

    # D. チケット & 注釈
    for ticket in ticket_info_list:
        line = f"{ticket.get('name','')} {ticket.get('price','')}"
        if ticket.get('note'): line += f" ({ticket.get('note')})"
        
        draw.text((W//2, current_y), line, fill=text_color, font=f_ticket_name, anchor="ma", stroke_width=2, stroke_fill=stroke_color)
        current_y += int(H * 0.05)

    current_y += int(H * 0.01)
    for txt in free_text_list:
        content = txt.get('content', '')
        if content:
            draw.text((W//2, current_y), content, fill=text_color, font=f_note, anchor="ma")
            current_y += int(H * 0.03)

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

    # --- 保存された設定のロード (flyer_jsonカラムを使用) ---
    saved_config = {}
    if getattr(proj, "flyer_json", None): # ★CSVに合わせてカラム名をflyer_jsonに変更
        try:
            if isinstance(proj.flyer_json, str):
                saved_config = json.loads(proj.flyer_json)
            elif isinstance(proj.flyer_json, dict):
                saved_config = proj.flyer_json
        except:
            pass
    
    # セッション初期化 (保存値があればそれを使用)
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

    # --- UI レイアウト ---
    c_conf, c_prev = st.columns([1, 1])

    with c_conf:
        # 1. 背景
        with st.expander("1. 背景画像を選択", expanded=True):
            render_visual_selector("背景", bgs, "flyer_bg_id", st.session_state.flyer_bg_id)

        # 2. ロゴ
        with st.expander("2. ロゴ画像を選択", expanded=False):
            render_visual_selector("ロゴ", logos, "flyer_logo_id", st.session_state.flyer_logo_id, allow_none=True)

        # 3. フォント・色
        with st.expander("3. フォント・色設定", expanded=True):
            all_fonts = [f for f in os.listdir(FONT_DIR) if f.lower().endswith(".ttf")]
            if not all_fonts: all_fonts = ["default"]

            current_font = st.session_state.flyer_basic_font
            if current_font not in all_fonts: current_font = all_fonts[0]
            
            font_choice = st.selectbox("フォント", all_fonts, index=all_fonts.index(current_font), key="flyer_basic_font")
            
            # プレビュー
            if font_choice != "default":
                preview_path = os.path.join(FONT_DIR, font_choice)
                prev_img = local_create_font_preview(preview_path, text="OPEN 18:30 / START 19:00")
                if prev_img:
                    st.image(prev_img, caption="フォントプレビュー", use_container_width=True)

            c1, c2 = st.columns(2)
            with c1: st.color_picker("文字色", st.session_state.flyer_text_color, key="flyer_text_color")
            with c2: st.color_picker("縁取り色", st.session_state.flyer_stroke_color, key="flyer_stroke_color")

        # --- アクションボタン ---
        c_act1, c_act2 = st.columns(2)
        
        # ★保存ボタン
        with c_act1:
            if st.button("💾 設定を保存する", use_container_width=True):
                config_data = {
                    "bg_id": st.session_state.flyer_bg_id,
                    "logo_id": st.session_state.flyer_logo_id,
                    "font": st.session_state.flyer_basic_font,
                    "text_color": st.session_state.flyer_text_color,
                    "stroke_color": st.session_state.flyer_stroke_color
                }
                
                # ★flyer_jsonカラムに保存
                if hasattr(proj, "flyer_json"):
                    try:
                        proj.flyer_json = json.dumps(config_data)
                        db.commit()
                        st.success("設定を保存しました！")
                    except Exception as e:
                        st.error(f"保存エラー: {e}")
                else:
                    st.warning("DBカラム 'flyer_json' が見つかりません")

        # ★生成ボタン
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
                
                # ★データ取得の安全化 (CSVの構造に対応)
                # venue_name を使用
                v_text = getattr(proj, "venue_name", "") or "" 
                if not v_text: # venue_nameがない場合、念のためvenueも探す
                    v_text = getattr(proj, "venue", "") or ""

                args = {
                    "bg_source": bg_url,
                    "logo_source": logo_url,
                    "basic_font_path": font_path,
                    "text_color": st.session_state.flyer_text_color,
                    "stroke_color": st.session_state.flyer_stroke_color,
                    "date_text": format_event_date(proj.event_date),
                    "venue_text": v_text, # ★修正済み
                    "open_time": format_time_str(proj.open_time),
                    "start_time": format_time_str(proj.start_time),
                    # DBから直接チケット情報を読む場合のフォールバック
                    "ticket_info_list": st.session_state.get("proj_tickets", []),
                    "free_text_list": st.session_state.get("proj_free_text", [])
                }
                
                # セッションステートが空の場合、DBのJSONから読み込む処理 (念のため)
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
