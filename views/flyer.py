import streamlit as st
from PIL import Image, ImageDraw, ImageFont
import io
import os
from constants import FONT_DIR
from database import get_db, TimetableProject, Asset, get_image_url
from logic_project import save_current_project
from utils import create_font_specimen_img

# --- 描画ヘルパー関数 ---
def draw_text_centered(draw, text, x, y, font, fill, stroke_width=0, stroke_fill=None, anchor="ma"):
    draw.text((x, y), text, font=font, fill=fill, stroke_width=stroke_width, stroke_fill=stroke_fill, anchor=anchor)

def draw_multiline_text_centered(draw, text, x, y, font, fill, line_spacing_ratio=1.2, stroke_width=0, stroke_fill=None, anchor="ma"):
    lines = text.split('\n')
    # フォントの高さを取得
    bbox = draw.textbbox((0, 0), "A", font=font)
    line_height = (bbox[3] - bbox[1]) * line_spacing_ratio
    
    current_y = y
    for line in lines:
        draw_text_centered(draw, line, x, current_y, font, fill, stroke_width, stroke_fill, anchor)
        current_y += line_height
    return current_y

def resize_image_to_fit(img, max_width, max_height):
    width_ratio = max_width / img.width
    height_ratio = max_height / img.height
    ratio = min(width_ratio, height_ratio)
    new_size = (int(img.width * ratio), int(img.height * ratio))
    return img.resize(new_size, Image.LANCZOS)

# --- フライヤー画像合成ロジック ---
def create_flyer_image(
    bg_path, logo_path, main_source, 
    sub_title, input_1, bottom_left, bottom_right, 
    font_path, text_color, stroke_color
):
    # 背景読み込み
    try: 
        base_img = Image.open(bg_path).convert("RGBA")
    except: 
        return None
        
    width, height = base_img.size
    draw = ImageDraw.Draw(base_img)
    
    # フォントサイズ計算 (画像サイズに対する比率で設定)
    try:
        font_sub = ImageFont.truetype(font_path, int(width * 0.08))
        font_in1 = ImageFont.truetype(font_path, int(width * 0.04))
        font_btm = ImageFont.truetype(font_path, int(width * 0.05))
        font_ticket = ImageFont.truetype(font_path, int(width * 0.045))
        font_free = ImageFont.truetype(font_path, int(width * 0.025))
    except:
        font_sub = font_in1 = font_btm = font_ticket = font_free = ImageFont.load_default()
    
    current_y = height * 0.05
    center_x = width / 2
    stroke_w = int(width * 0.003)

    # 1. ロゴ配置
    if logo_path:
        try:
            logo_img = Image.open(logo_path).convert("RGBA")
            logo_img = resize_image_to_fit(logo_img, width * 0.8, height * 0.2)
            logo_x = int((width - logo_img.width) / 2)
            base_img.paste(logo_img, (logo_x, int(current_y)), logo_img)
            current_y += logo_img.height + (height * 0.02)
        except: pass
    else:
        current_y += height * 0.1

    # 2. 上部テキスト (日付・会場など)
    if sub_title:
        draw_text_centered(draw, sub_title, center_x, current_y, font_sub, text_color, stroke_w, stroke_color)
        bbox = draw.textbbox((0, 0), sub_title, font=font_sub)
        current_y += (bbox[3] - bbox[1]) + (height * 0.01)
    
    if input_1:
        draw_text_centered(draw, input_1, center_x, current_y, font_in1, text_color, stroke_w, stroke_color)
        bbox = draw.textbbox((0, 0), input_1, font=font_in1)
        current_y += (bbox[3] - bbox[1]) + (height * 0.02)

    time_str = f"{bottom_left}   {bottom_right}"
    if time_str.strip():
        draw_text_centered(draw, time_str, center_x, current_y, font_btm, text_color, stroke_w, stroke_color)
        bbox = draw.textbbox((0, 0), time_str, font=font_btm)
        current_y += (bbox[3] - bbox[1]) + (height * 0.03)

    # 3. メイン画像 (Grid / Timetable / Custom)
    if main_source:
        try:
            if isinstance(main_source, Image.Image):
                main_img = main_source.convert("RGBA")
            else:
                main_img = Image.open(main_source).convert("RGBA")
                
            # メイン画像の配置エリア計算 (下部のテキストエリア分を残す)
            available_height = (height * 0.95) - current_y - (height * 0.25)
            
            if available_height > 100:
                main_img = resize_image_to_fit(main_img, width * 0.95, available_height)
                main_x = int((width - main_img.width) / 2)
                base_img.paste(main_img, (main_x, int(current_y)), main_img)
                current_y += main_img.height + (height * 0.03)
        except Exception as e:
            print(f"Main Image Error: {e}")
            pass

    # 4. 下部情報 (チケット・自由記述)
    # セッションから自動取得
    ticket_str = ""
    if "proj_tickets" in st.session_state:
        lines = []
        for t in st.session_state.proj_tickets:
            line = f"{t.get('name','')} {t.get('price','')}"
            if t.get("note"): line += f" ({t.get('note')})"
            if line.strip(): lines.append(line)
        ticket_str = "\n".join(lines)

    notes_str = ""
    if "proj_free_text" in st.session_state:
        lines = []
        for f in st.session_state.proj_free_text:
            if f.get("title"): lines.append(f"【{f.get('title')}】")
            if f.get("content"): lines.append(f.get("content"))
        notes_str = "\n".join(lines)

    if ticket_str:
        current_y = draw_multiline_text_centered(draw, ticket_str, center_x, current_y, font_ticket, text_color, 1.2, stroke_w, stroke_color)
        current_y += height * 0.02
    
    if notes_str:
        draw_multiline_text_centered(draw, notes_str, center_x, current_y, font_free, text_color, 1.3, 0, None)

    return base_img

# --- 画面描画 ---
def render_flyer_editor(project_id):
    db = next(get_db())
    
    # データを取得
    proj = db.query(TimetableProject).filter(TimetableProject.id == project_id).first()
    logos = db.query(Asset).filter(Asset.asset_type == "logo", Asset.is_deleted == False).all()
    bgs = db.query(Asset).filter(Asset.asset_type == "background", Asset.is_deleted == False).all()
    
    if not proj:
        st.error("プロジェクトが見つかりません")
        db.close()
        return

    st.subheader("📑 フライヤーセット同時生成")
    st.caption("デザインを設定し、全てのパターンのフライヤーを一括生成します。")
    
    if not bgs:
        st.warning("⚠️ 「素材アーカイブ」メニューで、少なくとも1つの『背景画像』を登録してください。")
        db.close()
        return

    # --- レイアウト ---
    c_conf, c_prev = st.columns([1, 1])

    with c_conf:
        # 1. 素材選択
        with st.expander("1. 素材選択 (共通)", expanded=True):
            # ロゴ
            logo_opts = {0: "(なし)"}
            for a in logos: logo_opts[a.id] = a.name
            
            # セッション値の整合性チェック
            current_logo_id = st.session_state.get("flyer_logo_id", 0)
            if current_logo_id not in logo_opts: current_logo_id = 0
            
            st.selectbox("ロゴ画像", options=logo_opts.keys(), format_func=lambda x: logo_opts[x], key="flyer_logo_id")
            
            # 背景
            bg_opts = {a.id: a.name for a in bgs}
            current_bg_id = st.session_state.get("flyer_bg_id")
            if current_bg_id not in bg_opts and bg_opts:
                current_bg_id = list(bg_opts.keys())[0]
                st.session_state.flyer_bg_id = current_bg_id
            
            st.selectbox("背景画像", options=bg_opts.keys(), format_func=lambda x: bg_opts[x], key="flyer_bg_id")

        # 2. テキスト情報
        with st.expander("2. テキスト情報 (共通)", expanded=True):
            st.text_input("サブタイトル (日付など)", key="flyer_sub_title")
            st.text_input("入力1 (会場名など)", key="flyer_input_1")
            c1, c2 = st.columns(2)
            with c1: st.text_input("左下 (OPENなど)", key="flyer_bottom_left")
            with c2: st.text_input("右下 (STARTなど)", key="flyer_bottom_right")
            st.caption("※チケット情報や注意事項は「イベント概要」タブの内容が自動反映されます。")

        # 3. デザイン
        with st.expander("3. デザイン (共通)", expanded=False):
            all_fonts = [f for f in os.listdir(FONT_DIR) if f.lower().endswith(".ttf")]
            if not all_fonts: all_fonts = ["keifont.ttf"]
            
            # フォント見本
            specimen_img = create_font_specimen_img(FONT_DIR, all_fonts)
            if specimen_img:
                st.image(specimen_img, use_container_width=True)

            # ガード処理
            if "flyer_font" not in st.session_state or st.session_state.flyer_font not in all_fonts:
                st.session_state.flyer_font = all_fonts[0]
            
            st.selectbox("フォント", all_fonts, key="flyer_font")
            st.color_picker("文字色", key="flyer_text_color")
            st.color_picker("縁取り色", key="flyer_stroke_color")
            
        st.divider()
        
        # 設定反映ボタン
        if st.button("🔄 設定反映 (プレビュー更新＆保存)", type="primary", use_container_width=True):
            if save_current_project(db, project_id):
                st.toast("設定を保存し、プレビューを更新しました！", icon="✅")
                # 再描画を強制
                st.session_state.flyer_force_update = True
            else:
                st.error("保存に失敗しました")

    # --- プレビュー表示エリア ---
    with c_prev:
        st.markdown("##### 生成プレビュー")
        
        # 必要なIDなどの取得
        bg_id = st.session_state.get("flyer_bg_id")
        logo_id = st.session_state.get("flyer_logo_id")
        
        # パス解決
        bg_asset = db.query(Asset).filter(Asset.id == bg_id).first()
        bg_path = get_image_url(bg_asset.image_filename) if bg_asset else None
        
        logo_path = None
        if logo_id and logo_id != 0:
            logo_asset = db.query(Asset).filter(Asset.id == logo_id).first()
            if logo_asset: logo_path = get_image_url(logo_asset.image_filename)
            
        font_path = os.path.join(FONT_DIR, st.session_state.get("flyer_font", "keifont.ttf"))

        if not bg_path:
            st.info("👈 背景画像を選択してください")
        else:
            # タブ切り替え
            tab_grid, tab_tt, tab_custom = st.tabs(["🖼️ アー写グリッド版", "⏱️ タイムテーブル版", "📁 カスタム"])

            # 共通引数を辞書化
            common_args = {
                "bg_path": bg_path,
                "logo_path": logo_path,
                "sub_title": st.session_state.get("flyer_sub_title", ""),
                "input_1": st.session_state.get("flyer_input_1", ""),
                "bottom_left": st.session_state.get("flyer_bottom_left", ""),
                "bottom_right": st.session_state.get("flyer_bottom_right", ""),
                "font_path": font_path,
                "text_color": st.session_state.get("flyer_text_color", "#FFFFFF"),
                "stroke_color": st.session_state.get("flyer_stroke_color", "#000000")
            }

            # 1. アー写グリッド版
            with tab_grid:
                grid_source = st.session_state.get("last_generated_grid_image")
                if grid_source:
                    try:
                        # プレビュー生成
                        img_grid = create_flyer_image(main_source=grid_source, **common_args)
                        
                        if img_grid:
                            st.image(img_grid, use_container_width=True)
                            
                            # ダウンロードボタン
                            buf = io.BytesIO()
                            img_grid.save(buf, format="PNG")
                            st.download_button(
                                "画像をダウンロード (Grid)", 
                                buf.getvalue(), 
                                "flyer_grid.png", 
                                "image/png", 
                                type="primary", 
                                use_container_width=True
                            )
                        else:
                            st.error("画像生成に失敗しました（ベース画像読込エラーなど）")
                    except Exception as e:
                        st.error(f"生成エラー: {e}")
                else:
                    st.warning("⚠️ まだアー写グリッドが作成されていません。")
                    st.info("「アー写グリッド」タブで「設定反映」ボタンを押して画像を生成してください。")

            # 2. タイムテーブル版
            with tab_tt:
                tt_source = st.session_state.get("last_generated_tt_image")
                if tt_source:
                    try:
                        img_tt = create_flyer_image(main_source=tt_source, **common_args)
                        
                        if img_tt:
                            st.image(img_tt, use_container_width=True)
                            
                            buf = io.BytesIO()
                            img_tt.save(buf, format="PNG")
                            st.download_button(
                                "画像をダウンロード (TT)", 
                                buf.getvalue(), 
                                "flyer_timetable.png", 
                                "image/png", 
                                type="primary", 
                                use_container_width=True
                            )
                        else:
                            st.error("画像生成に失敗しました")
                    except Exception as e:
                        st.error(f"生成エラー: {e}")
                else:
                    st.warning("⚠️ まだタイムテーブル画像が作成されていません。")
                    st.info("「タイムテーブル」タブで「設定反映」ボタンを押して画像を生成してください。")

            # 3. カスタム
            with tab_custom:
                st.caption("手持ちの画像をメインエリアに配置したい場合はこちら")
                custom_file = st.file_uploader("メイン画像をアップロード", type=['png','jpg','webp'])
                if custom_file:
                    try:
                        img_custom = create_flyer_image(main_source=custom_file, **common_args)
                        if img_custom:
                            st.image(img_custom, use_container_width=True)
                            
                            buf = io.BytesIO()
                            img_custom.save(buf, format="PNG")
                            st.download_button(
                                "画像をダウンロード (Custom)", 
                                buf.getvalue(), 
                                "flyer_custom.png", 
                                "image/png", 
                                type="primary", 
                                use_container_width=True
                            )
                    except Exception as e:
                        st.error(f"生成エラー: {e}")

    db.close()
