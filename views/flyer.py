import streamlit as st
from PIL import Image, ImageDraw, ImageFont
import io
import os
import requests
import math
from constants import FONT_DIR
from database import get_db, TimetableProject, Asset, get_image_url

# --- ヘルパー関数: 画像読み込み ---
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
        
        # UploadedFileなど
        return Image.open(source).convert("RGBA")
    except Exception as e:
        print(f"Image Load Error: {e}")
        return None

# --- ヘルパー関数: リサイズ ---
def resize_image_to_width(img, target_width):
    """幅に合わせてアスペクト比固定でリサイズ"""
    w_percent = (target_width / float(img.size[0]))
    h_size = int((float(img.size[1]) * float(w_percent)))
    return img.resize((target_width, h_size), Image.LANCZOS)

# --- ★新フライヤー画像合成ロジック (ROCK FIELD風) ---
def create_flyer_image_v2(
    bg_source, logo_source, main_source,
    basic_font_path, artist_font_path,
    text_color, stroke_color,
    # 新しいレイアウト用パラメータ
    date_text, venue_text, open_time, start_time,
    ticket_info_list, free_text_list
):
    # 1. 背景読み込み
    base_img = load_image_from_source(bg_source)
    if base_img is None: return None
    
    W, H = base_img.size
    draw = ImageDraw.Draw(base_img)
    
    # 2. フォント設定 (サイズはキャンバス幅に対する比率で計算)
    try:
        # 基本フォント（日時・会場・チケット）
        f_date = ImageFont.truetype(basic_font_path, int(W * 0.09))   # 日付:大
        f_venue = ImageFont.truetype(basic_font_path, int(W * 0.05))  # 会場:中
        f_label = ImageFont.truetype(basic_font_path, int(W * 0.04))  # OPEN/STARTラベル
        f_time = ImageFont.truetype(basic_font_path, int(W * 0.06))   # 時間
        
        # チケット情報用（少し小さめ）
        f_ticket_name = ImageFont.truetype(basic_font_path, int(W * 0.05))
        f_ticket_note = ImageFont.truetype(basic_font_path, int(W * 0.03))
        
        # 注釈用
        f_note = ImageFont.truetype(basic_font_path, int(W * 0.025))

    except:
        f_date = f_venue = f_label = f_time = f_ticket_name = f_ticket_note = f_note = ImageFont.load_default()

    # パディング設定
    padding_x = int(W * 0.05)
    current_y = int(H * 0.05)

    # ==========================================
    # A. ロゴ配置 (最上部)
    # ==========================================
    logo_img = load_image_from_source(logo_source)
    if logo_img:
        # ロゴは横幅の80%くらいに収める
        logo_w = int(W * 0.8)
        logo_img = resize_image_to_width(logo_img, logo_w)
        logo_x = (W - logo_img.width) // 2
        base_img.paste(logo_img, (logo_x, current_y), logo_img)
        current_y += logo_img.height + int(H * 0.02)
    else:
        # ロゴがない場合スペースだけ空ける
        current_y += int(H * 0.15)

    # ==========================================
    # B. 日時・会場 (左) / OPEN・START (右)
    # ==========================================
    info_y_start = current_y
    
    # --- 左側: 日付と会場 ---
    draw.text((padding_x, info_y_start), date_text, fill=text_color, font=f_date, anchor="la", stroke_width=2, stroke_fill=stroke_color)
    
    # 会場名は日付の下
    date_bbox = draw.textbbox((0, 0), date_text, font=f_date)
    date_h = date_bbox[3] - date_bbox[1]
    venue_y = info_y_start + date_h + int(H * 0.01)
    draw.text((padding_x, venue_y), venue_text, fill=text_color, font=f_venue, anchor="la", stroke_width=2, stroke_fill=stroke_color)

    # --- 右側: OPEN / START ---
    right_x = W - padding_x
    
    # OPEN
    draw.text((right_x, info_y_start), open_time, fill=text_color, font=f_time, anchor="ra", stroke_width=2, stroke_fill=stroke_color)
    time_bbox = draw.textbbox((0,0), open_time, font=f_time)
    # "OPEN ▶" ラベルを時間の左に配置
    draw.text((right_x - (time_bbox[2]-time_bbox[0]) - 20, info_y_start + 10), "OPEN ▶", fill=text_color, font=f_label, anchor="ra", stroke_width=1, stroke_fill=stroke_color)

    # START (OPENの下)
    start_y = info_y_start + (time_bbox[3] - time_bbox[1]) + int(H * 0.01)
    draw.text((right_x, start_y), start_time, fill=text_color, font=f_time, anchor="ra", stroke_width=2, stroke_fill=stroke_color)
    draw.text((right_x - (time_bbox[2]-time_bbox[0]) - 20, start_y + 10), "START ▶", fill=text_color, font=f_label, anchor="ra", stroke_width=1, stroke_fill=stroke_color)

    # 次のセクションの開始位置 (会場名かSTART時刻の低い方に合わせる)
    current_y = max(venue_y + int(H * 0.05), start_y + int(H * 0.05)) + int(H * 0.02)

    # ==========================================
    # C. アー写グリッド (中央)
    # ==========================================
    main_img = load_image_from_source(main_source)
    if main_img:
        # グリッド画像を読み込み、幅いっぱいにリサイズ（マージン考慮）
        grid_target_w = int(W * 0.95)
        main_img = resize_image_to_width(main_img, grid_target_w)
        grid_x = (W - main_img.width) // 2
        
        base_img.paste(main_img, (grid_x, current_y), main_img)
        current_y += main_img.height + int(H * 0.03)

    # ==========================================
    # D. チケット情報 & 注釈 (下部中央揃え)
    # ==========================================
    
    # チケット
    for ticket in ticket_info_list:
        line = f"{ticket['name']} {ticket['price']}"
        if ticket.get('note'):
            line += f" ({ticket['note']})"
        
        # チケット名は少し大きく
        draw.text((W//2, current_y), line, fill=text_color, font=f_ticket_name, anchor="ma", stroke_width=2, stroke_fill=stroke_color)
        current_y += int(H * 0.05)

    # 注釈（自由入力欄の内容など）
    current_y += int(H * 0.01)
    for txt in free_text_list:
        content = txt.get('content', '')
        if content:
            draw.text((W//2, current_y), content, fill=text_color, font=f_note, anchor="ma")
            current_y += int(H * 0.03)

    return base_img

# --- 画面描画 ---
def render_flyer_editor(project_id):
    db = next(get_db())
    proj = db.query(TimetableProject).filter(TimetableProject.id == project_id).first()
    logos = db.query(Asset).filter(Asset.asset_type == "logo", Asset.is_deleted == False).all()
    bgs = db.query(Asset).filter(Asset.asset_type == "background", Asset.is_deleted == False).all()
    
    if not proj:
        st.error("プロジェクトエラー")
        return

    st.subheader("📑 フライヤー生成 (NEWデザイン)")

    # --- セッション初期化 ---
    if "flyer_result_grid" not in st.session_state: st.session_state.flyer_result_grid = None
    if "flyer_result_tt" not in st.session_state: st.session_state.flyer_result_tt = None
    
    # --- レイアウト設定 ---
    c_conf, c_prev = st.columns([1, 1])

    with c_conf:
        # 1. 素材
        with st.expander("1. 画像素材", expanded=True):
            # ロゴ選択
            logo_opts = {0: "(なし)"}
            for a in logos: logo_opts[a.id] = a.name
            st.selectbox("ロゴ画像", logo_opts.keys(), format_func=lambda x: logo_opts[x], key="flyer_logo_id")
            
            # 背景選択
            bg_opts = {a.id: a.name for a in bgs}
            if "flyer_bg_id" not in st.session_state and bg_opts:
                st.session_state.flyer_bg_id = list(bg_opts.keys())[0]
            st.selectbox("背景画像", bg_opts.keys(), format_func=lambda x: bg_opts[x], key="flyer_bg_id")

        # 2. イベント情報 (新レイアウト対応)
        with st.expander("2. イベント情報", expanded=True):
            st.text_input("開催日 (例: 2025.11.30.SUN)", value="2025.xx.xx", key="flyer_date_text")
            st.text_input("会場名", value="会場名を入力", key="flyer_venue_text")
            c_t1, c_t2 = st.columns(2)
            with c_t1: st.text_input("OPEN", value="10:30", key="flyer_open_time")
            with c_t2: st.text_input("START", value="11:00", key="flyer_start_time")

        # 3. フォント設定 (2種類)
        with st.expander("3. フォント・色設定", expanded=True):
            all_fonts = [f for f in os.listdir(FONT_DIR) if f.lower().endswith(".ttf")]
            if not all_fonts: all_fonts = ["default"]

            st.markdown("**基本フォント** (日時・会場・チケット)")
            st.selectbox("選択", all_fonts, key="flyer_basic_font")
            
            st.markdown("**アーティスト名フォント** (グリッド生成時に使用)")
            st.info("※アーティスト名のフォントは「アー写グリッド生成」タブの設定が反映されています。ここでは変更できません。")

            c_col1, c_col2 = st.columns(2)
            with c_col1: st.color_picker("文字色", "#FFFFFF", key="flyer_text_color")
            with c_col2: st.color_picker("縁取り色", "#000000", key="flyer_stroke_color")

        st.divider()

        if st.button("🚀 画像を生成する", type="primary", use_container_width=True):
            # データ準備
            bg_id = st.session_state.get("flyer_bg_id")
            logo_id = st.session_state.get("flyer_logo_id")
            
            bg_url = get_image_url(db.query(Asset).get(bg_id).image_filename) if bg_id else None
            logo_url = get_image_url(db.query(Asset).get(logo_id).image_filename) if logo_id and logo_id != 0 else None
            
            basic_font_path = os.path.join(FONT_DIR, st.session_state.get("flyer_basic_font", "keifont.ttf"))
            
            # チケット情報取得
            tickets = st.session_state.get("proj_tickets", [])
            free_texts = st.session_state.get("proj_free_text", [])

            # 引数まとめ
            args = {
                "bg_source": bg_url,
                "logo_source": logo_url,
                "basic_font_path": basic_font_path,
                "artist_font_path": basic_font_path, # 今回は基本フォントを仮で渡す（グリッドは画像化済みのため）
                "text_color": st.session_state.flyer_text_color,
                "stroke_color": st.session_state.flyer_stroke_color,
                "date_text": st.session_state.flyer_date_text,
                "venue_text": st.session_state.flyer_venue_text,
                "open_time": st.session_state.flyer_open_time,
                "start_time": st.session_state.flyer_start_time,
                "ticket_info_list": tickets,
                "free_text_list": free_texts
            }

            with st.spinner("生成中..."):
                # グリッド版生成
                grid_src = st.session_state.get("last_generated_grid_image")
                if grid_src:
                    st.session_state.flyer_result_grid = create_flyer_image_v2(main_source=grid_src, **args)
                
                # タイムテーブル版生成
                tt_src = st.session_state.get("last_generated_tt_image")
                if tt_src:
                    st.session_state.flyer_result_tt = create_flyer_image_v2(main_source=tt_src, **args)

            st.success("生成完了！")

    # --- プレビュー ---
    with c_prev:
        st.markdown("##### 生成結果")
        tab1, tab2 = st.tabs(["アー写グリッド版", "タイムテーブル版"])
        
        with tab1:
            if st.session_state.flyer_result_grid:
                st.image(st.session_state.flyer_result_grid, use_container_width=True)
                # ダウンロードボタン
                buf = io.BytesIO()
                st.session_state.flyer_result_grid.save(buf, format="JPEG", quality=95)
                st.download_button("画像をダウンロード", buf.getvalue(), "flyer_grid.jpg", "image/jpeg", type="primary")
            else:
                st.info("「アー写グリッド」タブでグリッドを作成してから生成してください。")

        with tab2:
            if st.session_state.flyer_result_tt:
                st.image(st.session_state.flyer_result_tt, use_container_width=True)
                buf = io.BytesIO()
                st.session_state.flyer_result_tt.save(buf, format="JPEG", quality=95)
                st.download_button("画像をダウンロード", buf.getvalue(), "flyer_tt.jpg", "image/jpeg", type="primary")
            else:
                st.info("「タイムテーブル」タブで画像を生成してから実行してください。")

    db.close()
