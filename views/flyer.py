import streamlit as st
import io
import json
import zipfile
import os
from datetime import datetime

# ★追加: FlyerTemplate をインポート
from database import get_db, TimetableProject, Asset, get_image_url, SystemFontConfig, FlyerTemplate
from utils import get_sorted_font_list, create_font_specimen_img

# ここでインポートしている generate_event_summary_text_from_proj が
# 先ほど更新した共通ロジックを利用するため、自動的に最新のテキスト生成ルールが適用されます。
from utils.flyer_helpers import (
    format_event_date, format_time_str,
    generate_event_summary_text_from_proj, generate_timetable_csv_string
)
from utils.flyer_generator import create_flyer_image_shadow

# ==========================================
# 設定データの収集関数 (保存・テンプレート共通)
# ==========================================
def gather_flyer_settings_from_session():
    """現在のセッションステートから保存すべき設定データを辞書で返す"""
    save_data = {}
    
    # 1. 基本設定
    base_keys = [
        "bg_id", "logo_id", "date_format", 
        # "sub_title",  <-- テキスト自体は保存せず、あくまでデザイン設定のみ保存
        "logo_scale", "logo_pos_x", "logo_pos_y",
        "grid_scale_w", "grid_scale_h", "grid_pos_y", 
        "tt_scale_w", "tt_scale_h", "tt_pos_y",       
        "subtitle_date_gap", # ★追加
        "date_venue_gap", "ticket_gap", "area_gap", "note_gap", "footer_pos_y",
        "fallback_font", "time_tri_visible", "time_tri_scale", "time_line_gap", "time_alignment"
    ]
    for k in base_keys:
        save_data[k] = st.session_state.get(f"flyer_{k}")
    
    # 2. スタイル設定 (subtitle含む)
    target_keys = ["subtitle", "date", "venue", "time", "ticket_name", "ticket_note"]
    style_params = ["font", "size", "color", "shadow_on", "shadow_color", "shadow_blur", "shadow_off_x", "shadow_off_y", "pos_x", "pos_y"]
    for k in target_keys:
        for p in style_params:
            save_data[f"{k}_{p}"] = st.session_state.get(f"flyer_{k}_{p}")
            
    return save_data

# ==========================================
# UI コンポーネント
# ==========================================
def render_visual_selector(label, options, key_name, current_value, allow_none=False):
    st.markdown(f"**{label}**")
    if allow_none:
        is_none = (not current_value or current_value == 0)
        if st.button(f"🚫 {label}なし", key=f"btn_none_{key_name}", type="primary" if is_none else "secondary"):
            st.session_state[key_name] = 0
            st.rerun()
            
    if not options:
        st.info("選択肢がありません")
        return

    cols = st.columns(4)
    for i, opt in enumerate(options):
        with cols[i % 4]:
            is_selected = (opt.id == current_value)
            img_url = None
            if hasattr(opt, "image_filename") and opt.image_filename:
                img_url = get_image_url(opt.image_filename)
            
            if img_url:
                st.image(img_url, use_container_width=True)
            else:
                st.markdown(f"🔲 {opt.name}")

            if is_selected:
                st.button("✅ 選択中", key=f"btn_{key_name}_{opt.id}", disabled=True, use_container_width=True)
            else:
                if st.button("選択", key=f"btn_{key_name}_{opt.id}", use_container_width=True):
                    st.session_state[key_name] = opt.id
                    st.rerun()
    st.divider()

# ==========================================
# メイン画面描画
# ==========================================
def render_flyer_editor(project_id):
    db = next(get_db())
    proj = db.query(TimetableProject).filter(TimetableProject.id == project_id).first()
    
    logos = db.query(Asset).filter(Asset.asset_type == "logo", Asset.is_deleted == False).all()
    bgs = db.query(Asset).filter(Asset.asset_type == "background", Asset.is_deleted == False).all()
    
    font_list_data = get_sorted_font_list(db)
    font_options = [f["filename"] for f in font_list_data]
    font_map = {f["filename"]: f["name"] for f in font_list_data}
    if not font_options: font_options = ["keifont.ttf"]

    if not proj:
        st.error("プロジェクトエラー: 指定されたプロジェクトが見つかりません。")
        return

    st.subheader("📑 フライヤー生成 (Custom V6 - Layout Safe)")

    # 設定読み込み
    saved_config = {}
    if getattr(proj, "flyer_json", None):
        try: saved_config = json.loads(proj.flyer_json)
        except: pass

    # Session State 初期化ヘルパー
    def init_s(key, val):
        if key not in st.session_state:
            short_key = key.replace("flyer_", "")
            st.session_state[key] = saved_config.get(short_key, val)

    # --- パラメータ初期化 ---
    init_s("flyer_bg_id", 0)
    init_s("flyer_logo_id", 0)
    init_s("flyer_date_format", "EN")
    init_s("flyer_logo_scale", 1.0)
    init_s("flyer_logo_pos_x", 0.0)
    init_s("flyer_logo_pos_y", 0.0)

    init_s("flyer_grid_scale_w", 95)
    init_s("flyer_grid_scale_h", 100)
    init_s("flyer_grid_pos_y", 0)    
    init_s("flyer_tt_scale_w", 95)
    init_s("flyer_tt_scale_h", 100)
    init_s("flyer_tt_pos_y", 0)      
    init_s("flyer_grid_link", True) 
    init_s("flyer_tt_link", True)

    init_s("flyer_subtitle_date_gap", 10) 
    init_s("flyer_date_venue_gap", 10)
    init_s("flyer_ticket_gap", 20)
    init_s("flyer_area_gap", 40)
    init_s("flyer_note_gap", 15)
    init_s("flyer_footer_pos_y", 0)
    
    init_s("flyer_time_tri_visible", True)
    init_s("flyer_time_tri_scale", 1.0)
    init_s("flyer_time_line_gap", 0)
    init_s("flyer_time_alignment", "right")
    
    sys_conf = db.query(SystemFontConfig).first()
    def_sys = sys_conf.filename if sys_conf else "keifont.ttf"
    init_s("flyer_fallback_font", def_sys)

    # スタイル編集用UI関数
    def render_style_editor(label, prefix):
        init_s(f"flyer_{prefix}_font", "keifont.ttf")
        init_s(f"flyer_{prefix}_size", 50)
        init_s(f"flyer_{prefix}_color", "#FFFFFF")
        init_s(f"flyer_{prefix}_shadow_on", False)
        init_s(f"flyer_{prefix}_shadow_color", "#000000")
        init_s(f"flyer_{prefix}_shadow_blur", 2)
        init_s(f"flyer_{prefix}_shadow_off_x", 5)
        init_s(f"flyer_{prefix}_shadow_off_y", 5)
        init_s(f"flyer_{prefix}_pos_x", 0)
        init_s(f"flyer_{prefix}_pos_y", 0)

        with st.expander(f"📝 {label} スタイル", expanded=False):
            c1, c2 = st.columns([2, 1])
            with c1:
                st.selectbox("フォント", font_options, key=f"flyer_{prefix}_font", 
                             format_func=lambda x: font_map.get(x, x))
            with c2:
                st.color_picker("文字色", key=f"flyer_{prefix}_color")
            
            st.slider("ベースサイズ", 10, 200, step=5, key=f"flyer_{prefix}_size")
            
            cp1, cp2 = st.columns(2)
            with cp1: st.number_input("X移動 (横)", -500, 500, step=5, key=f"flyer_{prefix}_pos_x")
            with cp2: st.number_input("Y移動 (縦)", -500, 500, step=5, key=f"flyer_{prefix}_pos_y")

            st.markdown("---")
            sc1, sc2 = st.columns([1, 2])
            with sc1:
                st.checkbox("影をつける", key=f"flyer_{prefix}_shadow_on")
                if st.session_state[f"flyer_{prefix}_shadow_on"]:
                    st.color_picker("影の色", key=f"flyer_{prefix}_shadow_color")
            with sc2:
                if st.session_state[f"flyer_{prefix}_shadow_on"]:
                    st.slider("ぼかし", 0, 20, step=1, key=f"flyer_{prefix}_shadow_blur")
                    c1, c2 = st.columns(2)
                    with c1: st.number_input("影X", -50, 50, key=f"flyer_{prefix}_shadow_off_x")
                    with c2: st.number_input("影Y", -50, 50, key=f"flyer_{prefix}_shadow_off_y")
            
            if prefix == "time":
                st.markdown("---")
                align_map = {"right":"右揃え", "center":"中央揃え", "left":"左揃え", "triangle":"▶揃え"}
                c_al1, c_al2 = st.columns(2)
                with c_al1:
                    sel_align = st.selectbox("配置モード", list(align_map.keys()), 
                                             format_func=lambda x: align_map[x],
                                             key="flyer_time_alignment_sel",
                                             index=list(align_map.keys()).index(st.session_state.flyer_time_alignment))
                    st.session_state.flyer_time_alignment = sel_align
                with c_al2:
                    st.checkbox("三角形(▶)を表示", key="flyer_time_tri_visible")
                
                if st.session_state.flyer_time_tri_visible:
                    st.slider("三角形サイズ", 0.1, 2.0, step=0.1, key="flyer_time_tri_scale")
                st.slider("OPEN/STARTの行間", -100, 100, step=1, key="flyer_time_line_gap")

    # --- レイアウト構築 ---
    c_conf, c_prev = st.columns([1, 1.2])

    with c_conf:
        # ★追加: テンプレート管理エリア (Supabase対応)
        with st.expander("📂 テンプレート管理 (読込/保存)", expanded=False):
            st.caption("現在のデザイン設定をテンプレートとして保存し、他のプロジェクトで再利用できます。")
            
            # テンプレート読み込み
            templates = db.query(FlyerTemplate).all()
            templates.sort(key=lambda x: x.created_at or "", reverse=True) # 新しい順
            
            t_options = ["(選択してください)"] + [t.name for t in templates]
            
            c_load1, c_load2 = st.columns([3, 1])
            with c_load1:
                sel_template = st.selectbox("保存済みテンプレート", t_options, label_visibility="collapsed")
            with c_load2:
                if st.button("読込", use_container_width=True):
                    if sel_template != "(選択してください)":
                        target_t = next((t for t in templates if t.name == sel_template), None)
                        if target_t and target_t.data_json:
                            try:
                                loaded_data = json.loads(target_t.data_json)
                                # セッションステートを上書き
                                for k, v in loaded_data.items():
                                    st.session_state[f"flyer_{k}"] = v
                                
                                # プロジェクト設定にも即時保存 (リロードで戻らないように)
                                proj.flyer_json = json.dumps(loaded_data)
                                db.commit()
                                
                                st.toast(f"テンプレート「{sel_template}」を適用しました！", icon="✨")
                                st.rerun()
                            except Exception as e:
                                st.error(f"読込エラー: {e}")
            
            st.divider()
            
            # テンプレート保存
            c_save1, c_save2 = st.columns([3, 1])
            with c_save1:
                new_t_name = st.text_input("新規テンプレート名", placeholder="例: 赤系ロック風")
            with c_save2:
                if st.button("保存", use_container_width=True):
                    if not new_t_name:
                        st.error("名前を入力してください")
                    else:
                        existing = db.query(FlyerTemplate).filter(FlyerTemplate.name == new_t_name).first()
                        if existing:
                            st.error("同名のテンプレートが存在します")
                        else:
                            save_data = gather_flyer_settings_from_session()
                            new_tmpl = FlyerTemplate(
                                name=new_t_name,
                                data_json=json.dumps(save_data),
                                created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            )
                            db.add(new_tmpl)
                            db.commit()
                            st.toast(f"テンプレート「{new_t_name}」をSupabaseに保存しました！", icon="💾")
                            st.rerun()

        with st.expander("🖼️ 基本設定", expanded=True):
            render_visual_selector("背景画像", bgs, "flyer_bg_id", st.session_state.flyer_bg_id)
            st.markdown("---")
            render_visual_selector("ロゴ画像", logos, "flyer_logo_id", st.session_state.flyer_logo_id, allow_none=True)
            
            if st.session_state.flyer_logo_id:
                st.markdown("**ロゴ微調整**")
                c_l1, c_l2, c_l3 = st.columns(3)
                with c_l1: st.slider("サイズ", 0.1, 2.0, step=0.1, key="flyer_logo_scale")
                with c_l2: st.slider("X位置", -100.0, 100.0, step=1.0, key="flyer_logo_pos_x")
                with c_l3: st.slider("Y位置", -100.0, 100.0, step=1.0, key="flyer_logo_pos_y")
            
            st.markdown("---")
            current_subtitle = proj.subtitle if proj.subtitle else "(未設定)"
            st.markdown(f"**サブタイトル** (イベント概要から自動取得)")
            if not proj.subtitle:
                st.caption("※イベント概要タブで設定してください")
            else:
                st.info(current_subtitle)

            st.markdown("---")
            date_opts = ["EN (例: 2025.2.15.SUN)", "JP (例: 2025年2月15日 (日))"]
            
            curr_fmt = st.session_state.flyer_date_format
            idx = 0 if curr_fmt == "EN" else 1
            sel_fmt = st.radio("📅 日付表示形式", date_opts, index=idx)
            st.session_state.flyer_date_format = "EN" if sel_fmt.startswith("EN") else "JP"
            
            st.markdown("---")
            st.selectbox("🇯🇵 日本語用フォント (補助)", font_options, 
                         key="flyer_fallback_font", 
                         format_func=lambda x: font_map.get(x, x),
                         help="デザインフォントで日本語が表示できない場合に、このフォントを使用します。")

        with st.expander("🔤 フォント一覧見本を表示"):
            with st.container(height=300):
                specimen_img = create_font_specimen_img(db, font_list_data)
                if specimen_img: st.image(specimen_img, use_container_width=True)
                else: st.info("フォントが見つかりません")

        with st.expander("📐 コンテンツ・余白調整", expanded=False):
            st.markdown("**メイン画像サイズ・位置**")
            t_sz1, t_sz2 = st.tabs(["グリッド画像", "TT画像"])
            
            with t_sz1:
                c_link1, c_link2 = st.columns([0.15, 0.85])
                with c_link1: st.checkbox("🔗", key="flyer_grid_link", help="縦横比を固定")
                c1, c2 = st.columns(2)
                with c1:
                    new_w = st.slider("横幅 (%)", 10, 150, step=1, key="flyer_grid_scale_w")
                if st.session_state.flyer_grid_link:
                    st.session_state.flyer_grid_scale_h = new_w
                with c2:
                    st.slider("高さ (%)", 10, 150, step=1, key="flyer_grid_scale_h", disabled=st.session_state.flyer_grid_link)
                
                st.slider("上下位置調整 (Y)", -500, 500, step=10, key="flyer_grid_pos_y", help="グリッド画像の表示位置を上下に調整します")

            with t_sz2:
                c_link1, c_link2 = st.columns([0.15, 0.85])
                with c_link1: st.checkbox("🔗", key="flyer_tt_link", help="縦横比を固定")
                c1, c2 = st.columns(2)
                with c1:
                    new_w = st.slider("横幅 (%)", 10, 150, step=1, key="flyer_tt_scale_w")
                if st.session_state.flyer_tt_link:
                    st.session_state.flyer_tt_scale_h = new_w
                with c2:
                    st.slider("高さ (%)", 10, 150, step=1, key="flyer_tt_scale_h", disabled=st.session_state.flyer_tt_link)
                
                st.slider("上下位置調整 (Y)", -500, 500, step=10, key="flyer_tt_pos_y", help="タイムテーブル画像の表示位置を上下に調整します")

            st.markdown("---")
            st.markdown("**間隔設定**")
            st.slider("サブタイトルと日付の間隔", 0, 100, step=1, key="flyer_subtitle_date_gap")
            st.slider("日付と会場の間隔", 0, 100, step=1, key="flyer_date_venue_gap")
            st.slider("チケット行間", 0, 100, step=1, key="flyer_ticket_gap")
            st.slider("チケットエリアと備考エリアの行間", 0, 200, step=5, key="flyer_area_gap")
            st.slider("備考行間", 0, 100, step=1, key="flyer_note_gap")
            st.slider("フッターエリア位置 (Y移動)", -200, 200, step=5, key="flyer_footer_pos_y")

        st.markdown("#### 🎨 各要素のスタイル")
        render_style_editor("サブタイトル (Subtitle)", "subtitle")
        render_style_editor("日付 (DATE)", "date")
        render_style_editor("会場名 (VENUE)", "venue")
        render_style_editor("時間 (OPEN/START)", "time")
        render_style_editor("チケット情報 (List)", "ticket_name")
        render_style_editor("チケット共通備考 (Notes)", "ticket_note")

        if st.button("💾 設定を保存 (このプロジェクト)", use_container_width=True):
            save_data = gather_flyer_settings_from_session()
            if hasattr(proj, "flyer_json"):
                proj.flyer_json = json.dumps(save_data)
                db.commit()
                st.success("設定を保存しました")

    with c_prev:
        st.markdown("### 🚀 生成プレビュー")
        
        tickets = []
        if getattr(proj, "tickets_json", None):
            try: tickets = json.loads(proj.tickets_json)
            except: pass
        
        notes = []
        if getattr(proj, "ticket_notes_json", None):
            try: notes = json.loads(proj.ticket_notes_json)
            except: pass

        if st.button("プレビューを生成する", type="primary", use_container_width=True):
            bg_url = None
            if st.session_state.flyer_bg_id:
                asset = db.query(Asset).get(st.session_state.flyer_bg_id)
                if asset: bg_url = get_image_url(asset.image_filename)
            
            logo_url = None
            if st.session_state.flyer_logo_id:
                asset = db.query(Asset).get(st.session_state.flyer_logo_id)
                if asset: logo_url = get_image_url(asset.image_filename)

            styles = {k.replace("flyer_",""): v for k, v in st.session_state.items() if k.startswith("flyer_")}
            
            v_text = getattr(proj, "venue_name", "") or getattr(proj, "venue", "") or ""
            d_text = format_event_date(proj.event_date, st.session_state.flyer_date_format)
            fallback_filename = st.session_state.get("flyer_fallback_font")
            subtitle_text = proj.subtitle or ""

            with st.spinner("生成中..."):
                # 1. Generate Grid Flyer
                grid_src = st.session_state.get("last_generated_grid_image")
                if grid_src:
                    s_grid = styles.copy()
                    s_grid["content_scale_w"] = st.session_state.flyer_grid_scale_w
                    s_grid["content_scale_h"] = st.session_state.flyer_grid_scale_h
                    s_grid["content_pos_y"] = st.session_state.flyer_grid_pos_y 
                    
                    st.session_state.flyer_result_grid = create_flyer_image_shadow(
                        db=db, bg_source=bg_url, logo_source=logo_url, main_source=grid_src,
                        styles=s_grid,
                        date_text=d_text, venue_text=v_text,
                        subtitle_text=subtitle_text,
                        open_time=format_time_str(proj.open_time),
                        start_time=format_time_str(proj.start_time),
                        ticket_info_list=tickets, common_notes_list=notes,
                        system_fallback_filename=fallback_filename 
                    )
                
                # 2. Generate TT Flyer
                tt_src = st.session_state.get("last_generated_tt_image")
                if tt_src:
                    s_tt = styles.copy()
                    s_tt["content_scale_w"] = st.session_state.flyer_tt_scale_w
                    s_tt["content_scale_h"] = st.session_state.flyer_tt_scale_h
                    s_tt["content_pos_y"] = st.session_state.flyer_tt_pos_y 
                    
                    st.session_state.flyer_result_tt = create_flyer_image_shadow(
                        db=db, bg_source=bg_url, logo_source=logo_url, main_source=tt_src,
                        styles=s_tt,
                        date_text=d_text, venue_text=v_text,
                        subtitle_text=subtitle_text,
                        open_time=format_time_str(proj.open_time),
                        start_time=format_time_str(proj.start_time),
                        ticket_info_list=tickets, common_notes_list=notes,
                        system_fallback_filename=fallback_filename 
                    )

        t1, t2, t3, t4 = st.tabs(["アー写グリッド版", "タイムテーブル版", "イベント概要テキスト", "一括ダウンロード"])
        
        with t1:
            if st.session_state.get("flyer_result_grid"):
                st.image(st.session_state.flyer_result_grid, use_container_width=True)
                buf = io.BytesIO()
                st.session_state.flyer_result_grid.save(buf, format="PNG")
                st.download_button("DL (Grid)", buf.getvalue(), "flyer_grid.png", "image/png", key="dl_grid_single")
            else: st.info("プレビューを生成してください")
            
        with t2:
            if st.session_state.get("flyer_result_tt"):
                st.image(st.session_state.flyer_result_tt, use_container_width=True)
                buf = io.BytesIO()
                st.session_state.flyer_result_tt.save(buf, format="PNG")
                st.download_button("DL (TT)", buf.getvalue(), "flyer_tt.png", "image/png", key="dl_tt_single")
            else: st.info("プレビューを生成してください")
            
        with t3:
            st.markdown("### 告知用テキストプレビュー")
            # ★ここで共通ロジック経由の関数を呼び出しています
            summary_text = generate_event_summary_text_from_proj(proj, tickets, notes)
            st.text_area("内容", value=summary_text, height=300, disabled=True)
            st.download_button(
                label="📄 テキストをダウンロード",
                data=summary_text,
                file_name=f"event_outline_{proj.id}.txt",
                mime="text/plain"
            )

        with t4:
            st.markdown("### ファイル一括ダウンロード")
            include_assets = st.checkbox("素材データを含める (透過PNG, CSV, テキスト等)")
            
            if st.button("📦 ZIPファイルを生成", type="primary"):
                if not st.session_state.get("flyer_result_grid"):
                    st.error("先にプレビューを生成してください。")
                else:
                    try:
                        zip_buffer = io.BytesIO()
                        with zipfile.ZipFile(zip_buffer, 'w') as zip_file:
                            buf = io.BytesIO()
                            st.session_state.flyer_result_grid.save(buf, format="PNG")
                            zip_file.writestr("Flyer_Grid.png", buf.getvalue())
                            
                            if st.session_state.get("flyer_result_tt"):
                                buf = io.BytesIO()
                                st.session_state.flyer_result_tt.save(buf, format="PNG")
                                zip_file.writestr("Flyer_Timetable.png", buf.getvalue())
                            
                            # ★ここでも共通ロジック経由の関数を呼び出しています
                            summary_text = generate_event_summary_text_from_proj(proj, tickets, notes)
                            zip_file.writestr("Event_Outline.txt", summary_text)

                            if include_assets:
                                if st.session_state.get("last_generated_grid_image"):
                                    buf = io.BytesIO()
                                    st.session_state.last_generated_grid_image.save(buf, format="PNG")
                                    zip_file.writestr("Source_Grid_Transparent.png", buf.getvalue())
                                
                                if st.session_state.get("last_generated_tt_image"):
                                    buf = io.BytesIO()
                                    st.session_state.last_generated_tt_image.save(buf, format="PNG")
                                    zip_file.writestr("Source_Timetable_Transparent.png", buf.getvalue())
                                
                                csv_str = generate_timetable_csv_string(proj)
                                if csv_str:
                                    zip_file.writestr("Timetable_Data.csv", csv_str)

                        st.download_button(
                            label="⬇️ ZIPをダウンロード",
                            data=zip_buffer.getvalue(),
                            file_name=f"flyer_assets_{proj.id}.zip",
                            mime="application/zip"
                        )
                    except Exception as e:
                        st.error(f"ZIP生成エラー: {e}")

    db.close()
