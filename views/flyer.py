import streamlit as st
from PIL import Image, ImageDraw, ImageFont, ImageOps
import io
import os
import requests
import json
from constants import FONT_DIR
from database import get_db, TimetableProject, Asset, get_image_url
from utils import get_sorted_font_list

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

def crop_center_to_a4(img):
    """画像をA4縦比率(1:1.414)に合わせて中央トリミング/リサイズする"""
    if not img: return None
    
    # A4比率
    A4_RATIO = 1.4142
    
    img_w, img_h = img.size
    current_ratio = img_h / img_w
    
    # ターゲットサイズ計算（ベースは画像の幅に合わせるか、高さに合わせるか）
    if current_ratio > A4_RATIO:
        # 画像が細長すぎる -> 高さを削る
        new_h = int(img_w * A4_RATIO)
        top = (img_h - new_h) // 2
        img = img.crop((0, top, img_w, top + new_h))
    else:
        # 画像が横長、または太い -> 幅を削る
        new_w = int(img_h / A4_RATIO)
        left = (img_w - new_w) // 2
        img = img.crop((left, 0, left + new_w, img_h))
        
    return img

def resize_image_contain(img, max_w, max_h):
    """指定した枠内に収まるようにリサイズ"""
    if not img: return None
    ratio = min(max_w / img.width, max_h / img.height)
    new_w = int(img.width * ratio)
    new_h = int(img.height * ratio)
    return img.resize((new_w, new_h), Image.LANCZOS)

def format_event_date_short(dt_obj):
    if not dt_obj: return ""
    if isinstance(dt_obj, str): return dt_obj
    try:
        weekdays = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"]
        # weekday()は月曜0始まりなので変換注意: 6=Sunday -> 0=Sundayにするなら (w+1)%7
        # Pythonのweekday: 0=Mon, 6=Sun. 
        # 配列をMon始まりにする
        wd_str = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"][dt_obj.weekday()]
        return f"{dt_obj.year}.{dt_obj.month}.{dt_obj.day}.{wd_str}"
    except:
        return str(dt_obj)

def format_time_str(t_val):
    if not t_val or t_val == 0 or t_val == "0": return ""
    if isinstance(t_val, str): return t_val[:5]
    try: return t_val.strftime("%H:%M")
    except: return str(t_val)

def draw_text_squeezed(base_img, text, x, y, font, max_width, fill, stroke_width=0, stroke_fill=None, anchor="la"):
    """指定幅(max_width)を超えたら、画像を縮小(長体)して描画する"""
    if not text: return 0
    
    dummy_img = Image.new("RGBA", (1, 1))
    dummy_draw = ImageDraw.Draw(dummy_img)
    bbox = dummy_draw.textbbox((0, 0), text, font=font, stroke_width=stroke_width)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    
    canvas_w = text_w + abs(bbox[0]) + stroke_width * 2
    canvas_h = text_h + abs(bbox[1]) + stroke_width * 2
    
    txt_img = Image.new("RGBA", (canvas_w, canvas_h), (0,0,0,0))
    txt_draw = ImageDraw.Draw(txt_img)
    # textbboxのオフセット分ずらして描画
    draw_x = -bbox[0] + stroke_width
    draw_y = -bbox[1] + stroke_width
    txt_draw.text((draw_x, draw_y), text, font=font, fill=fill, stroke_width=stroke_width, stroke_fill=stroke_fill)
    
    final_w = canvas_w
    final_h = canvas_h
    
    # 幅オーバー時の圧縮
    if canvas_w > max_width:
        final_w = max_width
        txt_img = txt_img.resize((final_w, final_h), Image.LANCZOS)
    
    paste_x = x
    paste_y = y
    
    if anchor == "ra":
        paste_x = x - final_w
    elif anchor == "ma":
        paste_x = x - (final_w // 2)
    
    base_img.paste(txt_img, (paste_x, paste_y), txt_img)
    return final_h

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
            # サムネイル表示用に画像をロードしてA4縦にトリミングして表示
            # (パフォーマンスのため、本来はサムネイルを保存しておくべきですが、ここでは動的処理)
            img_url = get_image_url(asset.image_filename)
            
            # コンテナ幅いっぱいに表示（CSSでの強制縦長は難しいので、正方形コンテナ等で見せる）
            # ここでは「選択画面でもA4縦」という要望のため、st.imageで工夫する
            st.image(img_url, use_container_width=True) 
            
            is_sel = (asset.id == current_id)
            if st.button("選択", key=f"btn_{key_prefix}_{asset.id}", type="primary" if is_sel else "secondary", use_container_width=True):
                st.session_state[key_prefix] = asset.id
                st.rerun()

# ==========================================
# 3. フライヤー生成ロジック (V3)
# ==========================================

def create_flyer_image_v3(
    bg_source, logo_source, main_source,
    styles, # フォントやサイズの設定辞書
    date_text, venue_text, open_time, start_time,
    ticket_info_list,
    common_notes_list
):
    # 1. 背景の読み込みとA4化
    raw_bg = load_image_from_source(bg_source)
    if raw_bg is None:
        # 背景がない場合は白紙のA4 (高解像度)
        W, H = 2480, 3508
        base_img = Image.new("RGBA", (W, H), (20, 20, 30, 255)) # デフォルト暗い背景
    else:
        # 画像をA4比率にクロップ
        base_img = crop_center_to_a4(raw_bg)
        # 解像度があまりに低い場合はリサイズ（最低幅1200px確保）
        if base_img.width < 1200:
            scale = 1200 / base_img.width
            base_img = base_img.resize((1200, int(base_img.height * scale)), Image.LANCZOS)
    
    W, H = base_img.size
    draw = ImageDraw.Draw(base_img)

    # --- フォントローダー ---
    def get_font(style_key, default_size_ratio):
        f_name = styles.get(f"{style_key}_font", "keifont.ttf")
        f_size_val = styles.get(f"{style_key}_size", 50) # スライダーの生値 (10-200想定)
        
        # 画面サイズに応じた相対サイズに変換 (基準幅 2000px と仮定して補正)
        # ユーザーのスライダー値(例:50)を、画像幅に対する比率に直す
        # ここではスライダー値をそのままptサイズとして扱い、画像サイズに合わせてスケール
        scale_factor = W / 1200.0
        final_size = int(f_size_val * scale_factor)
        
        try:
            return ImageFont.truetype(os.path.join(FONT_DIR, f_name), final_size)
        except:
            return ImageFont.load_default()

    def get_color(style_key, default="#FFFFFF"):
        return styles.get(f"{style_key}_color", default)

    # 各種フォント準備
    f_date = get_font("date", 80)
    f_venue = get_font("venue", 50)
    f_time_lbl = get_font("time", 40) # OPEN/START ラベル
    f_time_val = get_font("time", 60) # 時間の値
    f_ticket_name = get_font("ticket_name", 45)
    f_ticket_price = get_font("ticket_price", 45)
    f_note = get_font("ticket_note", 30)

    # 各種カラー
    c_date = get_color("date")
    c_venue = get_color("venue")
    c_time = get_color("time")
    c_ticket = get_color("ticket")
    c_note = get_color("note")
    
    # 共通ストローク設定 (簡易化のため黒固定または設定値)
    c_stroke = styles.get("stroke_color", "#000000")
    stroke_w = int(W * 0.003)

    padding_x = int(W * 0.05)
    current_y = int(H * 0.03)

    # ==========================
    # A. ロゴ (サイズ・位置調整あり)
    # ==========================
    logo_img = load_image_from_source(logo_source)
    logo_bottom_y = current_y

    if logo_img:
        # 設定値取得
        logo_scale = styles.get("logo_scale", 1.0)
        logo_pos_x = styles.get("logo_pos_x", 0) # -100 to 100 (percentage shift)
        logo_pos_y = styles.get("logo_pos_y", 0) # -100 to 100 (percentage shift)

        # 基準サイズ: 横幅の50% * スケール
        base_logo_w = int(W * 0.5 * logo_scale)
        logo_img = resize_image_to_width(logo_img, base_logo_w)
        
        # 基準位置: 中央
        base_x = (W - logo_img.width) // 2
        base_y = current_y
        
        # 微調整 (画素数換算)
        offset_x = int(W * (logo_pos_x / 100.0))
        offset_y = int(H * (logo_pos_y / 100.0))
        
        final_x = base_x + offset_x
        final_y = base_y + offset_y
        
        base_img.paste(logo_img, (final_x, final_y), logo_img)
        logo_bottom_y = final_y + logo_img.height

    # ヘッダーエリアの開始位置（ロゴの下）
    header_y = logo_bottom_y + int(H * 0.02)
    
    # ==========================
    # B. 日付・会場 (左側) vs OPEN/START (右側)
    # ==========================
    
    # 左エリア幅: 55%, 右エリア幅: 35%
    left_x = padding_x
    right_x = W - padding_x
    left_max_w = int(W * 0.55)
    right_max_w = int(W * 0.35)

    # --- 左側: 日付 & 会場 ---
    # 日付
    h_date = draw_text_squeezed(base_img, str(date_text), left_x, header_y, f_date, left_max_w, c_date, stroke_w, c_stroke, "la")
    # 会場 (日付の下)
    venue_y = header_y + h_date + int(H * 0.005)
    h_venue = draw_text_squeezed(base_img, str(venue_text), left_x, venue_y, f_venue, left_max_w, c_venue, stroke_w, c_stroke, "la")
    
    left_bottom_y = venue_y + h_venue

    # --- 右側: OPEN / START ---
    # 参考画像レイアウト:
    # OPEN ▶ 10:30
    # START ▶ 10:45
    # ラベルと時間を横並びにするか、上下にするか。参考画像は横並びっぽい。
    
    # 時間文字列作成
    o_str = str(open_time) if open_time else "TBA"
    s_str = str(start_time) if start_time else "TBA"
    
    # 右寄せで描画するため、少し計算が必要
    # 行の高さ
    line_h = max(f_time_lbl.size, f_time_val.size) + 10
    
    # OPEN行
    draw_text_squeezed(base_img, o_str, right_x, header_y, f_time_val, int(right_max_w*0.6), c_time, stroke_w, c_stroke, "ra")
    # "OPEN ▶" をその左に
    # 時間の幅を概算
    dummy_draw = ImageDraw.Draw(Image.new("RGBA",(1,1)))
    bb_time = dummy_draw.textbbox((0,0), o_str, font=f_time_val)
    time_w = bb_time[2] - bb_time[0]
    label_x = right_x - time_w - int(W*0.02)
    draw_text_squeezed(base_img, "OPEN ▶", label_x, header_y + (f_time_val.size - f_time_lbl.size), f_time_lbl, int(right_max_w*0.4), c_time, 1, c_stroke, "ra")

    # START行 (OPENの下)
    start_y = header_y + line_h + int(H * 0.01)
    draw_text_squeezed(base_img, s_str, right_x, start_y, f_time_val, int(right_max_w*0.6), c_time, stroke_w, c_stroke, "ra")
    
    bb_time_s = dummy_draw.textbbox((0,0), s_str, font=f_time_val)
    time_w_s = bb_time_s[2] - bb_time_s[0]
    label_x_s = right_x - time_w_s - int(W*0.02)
    draw_text_squeezed(base_img, "START ▶", label_x_s, start_y + (f_time_val.size - f_time_lbl.size), f_time_lbl, int(right_max_w*0.4), c_time, 1, c_stroke, "ra")

    right_bottom_y = start_y + line_h

    header_bottom = max(left_bottom_y, right_bottom_y) + int(H * 0.02)

    # ==========================
    # C. フッター (チケット情報)
    # ==========================
    # 下から積み上げていく方式、あるいは高さを計算して配置
    
    footer_lines = []
    
    # 1. 共通備考 (一番下)
    for note in reversed(common_notes_list):
        if note and str(note).strip():
            footer_lines.append({"text": str(note).strip(), "font": f_note, "color": c_note, "gap": int(H*0.01)})
    
    # 2. チケット情報 (その上)
    # 形式: Sチケット ¥6,000 (備考)
    for ticket in reversed(ticket_info_list):
        name = ticket.get('name', '')
        price = ticket.get('price', '')
        note = ticket.get('note', '')
        
        # 名前と価格を結合
        main_txt = f"{name} {price}"
        
        # 備考がある場合は結合するか、行を分けるか。参考画像ではカッコ書きで横にある。
        if note:
            main_txt += f" ( {note} )"
        
        footer_lines.append({"text": main_txt, "font": f_ticket_name, "color": c_ticket, "gap": int(H*0.02)})

    # フッターの総高さを計算
    footer_h = int(H * 0.05) # 下部余白
    processed_footer = []
    
    for item in footer_lines:
        bbox = draw.textbbox((0,0), item["text"], font=item["font"])
        h = bbox[3] - bbox[1]
        processed_footer.append({**item, "h": h})
        footer_h += h + item["gap"]

    footer_start_y = H - footer_h
    
    # フッター描画実行
    curr_fy = footer_start_y
    for item in reversed(processed_footer): # 下から順に計算したが、描画は上から順（逆順リストをさらに逆順で処理）
        draw_text_squeezed(base_img, item["text"], W//2, curr_fy, item["font"], int(W*0.9), item["color"], stroke_w, c_stroke, "ma")
        curr_fy += item["h"] + item["gap"]

    # ==========================
    # D. メイン画像 (中央エリア)
    # ==========================
    available_top = header_bottom
    available_bottom = footer_start_y - int(H * 0.02)
    available_h = available_bottom - available_top
    
    main_img = load_image_from_source(main_source)
    
    if main_img and available_h > 100:
        # 横幅は95%まで
        max_w = int(W * 0.95)
        
        # メイン画像のリサイズ
        main_resized = resize_image_contain(main_img, max_w, available_h)
        
        # 配置座標 (中央)
        paste_x = (W - main_resized.width) // 2
        
        # 上下中央揃え
        paste_y = available_top + (available_h - main_resized.height) // 2
        
        base_img.paste(main_resized, (paste_x, int(paste_y)), main_resized)

    return base_img

def resize_image_to_width(img, target_width):
    if not img: return None
    w_percent = (target_width / float(img.size[0]))
    h_size = int((float(img.size[1]) * float(w_percent)))
    return img.resize((target_width, h_size), Image.LANCZOS)

# ==========================================
# 4. メイン画面描画
# ==========================================

def render_flyer_editor(project_id):
    db = next(get_db())
    proj = db.query(TimetableProject).filter(TimetableProject.id == project_id).first()
    
    logos = db.query(Asset).filter(Asset.asset_type == "logo", Asset.is_deleted == False).all()
    bgs = db.query(Asset).filter(Asset.asset_type == "background", Asset.is_deleted == False).all()
    
    # フォントリスト取得
    font_list_data = get_sorted_font_list(db)
    font_options = [f["filename"] for f in font_list_data]
    font_map = {f["filename"]: f["name"] for f in font_list_data}
    if not font_options: font_options = ["keifont.ttf"]

    if not proj:
        st.error("プロジェクトエラー")
        return

    st.subheader("📑 フライヤー生成 (PRO版)")

    # 設定ロード (JSON)
    saved_config = {}
    if getattr(proj, "flyer_json", None):
        try: saved_config = json.loads(proj.flyer_json)
        except: pass

    # --- セッションState初期化 ---
    # 基本
    if "flyer_bg_id" not in st.session_state: st.session_state.flyer_bg_id = int(saved_config.get("bg_id", 0))
    if "flyer_logo_id" not in st.session_state: st.session_state.flyer_logo_id = int(saved_config.get("logo_id", 0))
    if "flyer_stroke_color" not in st.session_state: st.session_state.flyer_stroke_color = saved_config.get("stroke_color", "#000000")
    
    # ロゴ調整
    if "flyer_logo_scale" not in st.session_state: st.session_state.flyer_logo_scale = saved_config.get("logo_scale", 1.0)
    if "flyer_logo_pos_x" not in st.session_state: st.session_state.flyer_logo_pos_x = saved_config.get("logo_pos_x", 0.0)
    if "flyer_logo_pos_y" not in st.session_state: st.session_state.flyer_logo_pos_y = saved_config.get("logo_pos_y", 0.0)

    # 各要素のスタイル初期化関数
    def init_style(key, def_font="keifont.ttf", def_size=50, def_color="#FFFFFF"):
        if f"flyer_{key}_font" not in st.session_state: st.session_state[f"flyer_{key}_font"] = saved_config.get(f"{key}_font", def_font)
        if f"flyer_{key}_size" not in st.session_state: st.session_state[f"flyer_{key}_size"] = saved_config.get(f"{key}_size", def_size)
        if f"flyer_{key}_color" not in st.session_state: st.session_state[f"flyer_{key}_color"] = saved_config.get(f"{key}_color", def_color)

    init_style("date", def_size=90)
    init_style("venue", def_size=50)
    init_style("time", def_size=60) # Open/Start
    init_style("ticket_name", def_size=50)
    init_style("ticket_price", def_size=50) # 今回はnameと共用だが拡張性のため
    init_style("ticket_note", def_size=30) # 共通備考

    # --- 画面構成 ---
    c_conf, c_prev = st.columns([1, 1.2])

    with c_conf:
        # 1. 素材選択
        with st.expander("🖼️ 素材選択 (背景・ロゴ)", expanded=True):
            render_visual_selector("背景画像 (自動でA4縦になります)", bgs, "flyer_bg_id", st.session_state.flyer_bg_id)
            st.markdown("---")
            render_visual_selector("ロゴ画像", logos, "flyer_logo_id", st.session_state.flyer_logo_id, allow_none=True)
            
            if st.session_state.flyer_logo_id:
                st.markdown("**ロゴ微調整**")
                c_l1, c_l2, c_l3 = st.columns(3)
                with c_l1: st.slider("サイズ", 0.1, 2.0, st.session_state.flyer_logo_scale, 0.1, key="flyer_logo_scale")
                with c_l2: st.slider("左右位置", -100.0, 100.0, st.session_state.flyer_logo_pos_x, 1.0, key="flyer_logo_pos_x")
                with c_l3: st.slider("上下位置", -100.0, 100.0, st.session_state.flyer_logo_pos_y, 1.0, key="flyer_logo_pos_y")

        # 2. テキストスタイル設定
        st.markdown("#### 🎨 テキストスタイル設定")
        st.color_picker("文字の縁取り色 (共通)", st.session_state.flyer_stroke_color, key="flyer_stroke_color")

        def render_style_editor(label, key_prefix):
            with st.expander(f"📝 {label} の設定", expanded=False):
                c1, c2 = st.columns([2, 1])
                with c1:
                    st.selectbox("フォント", font_options, 
                                 index=font_options.index(st.session_state[f"flyer_{key_prefix}_font"]) if st.session_state[f"flyer_{key_prefix}_font"] in font_options else 0,
                                 key=f"flyer_{key_prefix}_font", format_func=lambda x: font_map.get(x, x))
                with c2:
                    st.color_picker("文字色", st.session_state[f"flyer_{key_prefix}_color"], key=f"flyer_{key_prefix}_color")
                
                st.slider(f"文字サイズ ({label})", 10, 200, st.session_state[f"flyer_{key_prefix}_size"], 5, key=f"flyer_{key_prefix}_size")

        render_style_editor("日付 (DATE)", "date")
        render_style_editor("会場名 (VENUE)", "venue")
        render_style_editor("時間 (OPEN/START)", "time")
        render_style_editor("チケット情報", "ticket_name")
        render_style_editor("注意事項 (NOTES)", "ticket_note")

        # 保存ボタン
        if st.button("💾 設定を保存", use_container_width=True):
            # 辞書にまとめる
            save_data = {
                "bg_id": st.session_state.flyer_bg_id,
                "logo_id": st.session_state.flyer_logo_id,
                "stroke_color": st.session_state.flyer_stroke_color,
                "logo_scale": st.session_state.flyer_logo_scale,
                "logo_pos_x": st.session_state.flyer_logo_pos_x,
                "logo_pos_y": st.session_state.flyer_logo_pos_y,
            }
            # 各スタイルの保存
            for k in ["date", "venue", "time", "ticket_name", "ticket_note"]:
                save_data[f"{k}_font"] = st.session_state[f"flyer_{k}_font"]
                save_data[f"{k}_size"] = st.session_state[f"flyer_{k}_size"]
                save_data[f"{k}_color"] = st.session_state[f"flyer_{k}_color"]

            if hasattr(proj, "flyer_json"):
                proj.flyer_json = json.dumps(save_data)
                db.commit()
                st.success("設定を保存しました")
            else:
                st.warning("DBに保存カラムがありません")

    with c_prev:
        st.markdown("### 🚀 生成")
        
        if st.button("画像を生成する", type="primary", use_container_width=True):
            # 画像パス取得
            bg_url = None
            if st.session_state.flyer_bg_id:
                bg_asset = db.query(Asset).get(st.session_state.flyer_bg_id)
                if bg_asset: bg_url = get_image_url(bg_asset.image_filename)

            logo_url = None
            if st.session_state.flyer_logo_id:
                l_asset = db.query(Asset).get(st.session_state.flyer_logo_id)
                if l_asset: logo_url = get_image_url(l_asset.image_filename)

            # スタイル辞書作成
            style_dict = {
                "stroke_color": st.session_state.flyer_stroke_color,
                "logo_scale": st.session_state.flyer_logo_scale,
                "logo_pos_x": st.session_state.flyer_logo_pos_x,
                "logo_pos_y": st.session_state.flyer_logo_pos_y,
            }
            for k in ["date", "venue", "time", "ticket_name", "ticket_note"]:
                style_dict[f"{k}_font"] = st.session_state[f"flyer_{k}_font"]
                style_dict[f"{k}_size"] = st.session_state[f"flyer_{k}_size"]
                style_dict[f"{k}_color"] = st.session_state[f"flyer_{k}_color"]

            # データ取得
            tickets = []
            if getattr(proj, "tickets_json", None):
                try: tickets = json.loads(proj.tickets_json)
                except: pass
            
            notes = []
            if getattr(proj, "ticket_notes_json", None): # カラム名注意
                try: notes = json.loads(proj.ticket_notes_json)
                except: pass
            
            v_text = getattr(proj, "venue_name", "") or getattr(proj, "venue", "") or ""

            args = {
                "bg_source": bg_url,
                "logo_source": logo_url,
                "styles": style_dict,
                "date_text": format_event_date_short(proj.event_date),
                "venue_text": v_text,
                "open_time": format_time_str(proj.open_time),
                "start_time": format_time_str(proj.start_time),
                "ticket_info_list": tickets,
                "common_notes_list": notes
            }

            with st.spinner("生成中..."):
                grid_src = st.session_state.get("last_generated_grid_image")
                if grid_src:
                    st.session_state.flyer_result_grid = create_flyer_image_v3(main_source=grid_src, **args)
                
                tt_src = st.session_state.get("last_generated_tt_image")
                if tt_src:
                    st.session_state.flyer_result_tt = create_flyer_image_v3(main_source=tt_src, **args)

        # 表示
        t1, t2 = st.tabs(["アー写グリッド版", "タイムテーブル版"])
        with t1:
            if st.session_state.get("flyer_result_grid"):
                st.image(st.session_state.flyer_result_grid, use_container_width=True)
                # DL
                buf = io.BytesIO()
                st.session_state.flyer_result_grid.save(buf, format="PNG")
                st.download_button("DL (Grid)", buf.getvalue(), "flyer_grid.png", "image/png", key="dl_grid")
            else:
                st.info("生成ボタンを押してください")
        with t2:
            if st.session_state.get("flyer_result_tt"):
                st.image(st.session_state.flyer_result_tt, use_container_width=True)
                # DL
                buf = io.BytesIO()
                st.session_state.flyer_result_tt.save(buf, format="PNG")
                st.download_button("DL (TT)", buf.getvalue(), "flyer_tt.png", "image/png", key="dl_tt")
            else:
                st.info("生成ボタンを押してください")

    db.close()
