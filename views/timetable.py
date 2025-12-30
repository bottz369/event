import streamlit as st
import pandas as pd
import json
import io
import os
from datetime import datetime, date, timedelta
from database import get_db, SessionLocal, Artist, TimetableProject
from constants import (
    TIME_OPTIONS, DURATION_OPTIONS, ADJUSTMENT_OPTIONS, 
    GOODS_DURATION_OPTIONS, PLACE_OPTIONS, FONT_DIR, get_default_row_settings
)
from utils import safe_int, safe_str, get_duration_minutes, calculate_timetable_flow, create_business_pdf, create_font_specimen_img
from logic_project import save_current_project

try:
    from streamlit_sortables import sort_items
except ImportError:
    sort_items = None

try:
    from logic_timetable import generate_timetable_image
except ImportError:
    generate_timetable_image = None

def render_timetable_page():
    if "ws_active_project_id" not in st.session_state or st.session_state.ws_active_project_id is None:
        st.title("⏱️ タイムテーブル作成")
    
    db = next(get_db())
    
    selected_id = None
    if "ws_active_project_id" in st.session_state and st.session_state.ws_active_project_id:
        selected_id = st.session_state.ws_active_project_id
    else:
        projects = db.query(TimetableProject).all()
        projects.sort(key=lambda x: x.event_date or "0000-00-00", reverse=True)
        proj_map = {f"{p.event_date} {p.title}": p.id for p in projects}
        options = ["(選択してください)"] + list(proj_map.keys())
        selected_label = st.selectbox("プロジェクトを選択", options)
        if selected_label != "(選択してください)": selected_id = proj_map[selected_label]

    if selected_id:
        if st.session_state.get("tt_current_proj_id") != selected_id:
            proj = db.query(TimetableProject).filter(TimetableProject.id == selected_id).first()
            if proj:
                st.session_state.tt_title = proj.title
                try: st.session_state.tt_event_date = datetime.strptime(proj.event_date, "%Y-%m-%d").date() if proj.event_date else date.today()
                except: st.session_state.tt_event_date = date.today()
                st.session_state.tt_venue = proj.venue_name
                st.session_state.tt_open_time = proj.open_time or "10:00"
                st.session_state.tt_start_time = proj.start_time or "10:30"
                st.session_state.tt_goods_offset = proj.goods_start_offset if proj.goods_start_offset is not None else 5
                
                if proj.data_json:
                    try:
                        data = json.loads(proj.data_json)
                        new_order = []
                        new_artist_settings = {}
                        new_row_settings = []
                        st.session_state.tt_has_pre_goods = False
                        for item in data:
                            name = item["ARTIST"]
                            if name == "開演前物販":
                                st.session_state.tt_has_pre_goods = True
                                st.session_state.tt_pre_goods_settings = {
                                    "GOODS_START_MANUAL": safe_str(item.get("GOODS_START_MANUAL")),
                                    "GOODS_DURATION": safe_int(item.get("GOODS_DURATION"), 60),
                                    "PLACE": safe_str(item.get("PLACE")),
                                }
                                continue
                            if name == "終演後物販":
                                st.session_state.tt_post_goods_settings = {
                                    "GOODS_START_MANUAL": safe_str(item.get("GOODS_START_MANUAL")),
                                    "GOODS_DURATION": safe_int(item.get("GOODS_DURATION"), 60),
                                    "PLACE": safe_str(item.get("PLACE")),
                                }
                                continue
                            new_order.append(name)
                            new_artist_settings[name] = {"DURATION": safe_int(item.get("DURATION"), 20)}
                            new_row_settings.append({
                                "ADJUSTMENT": safe_int(item.get("ADJUSTMENT"), 0),
                                "GOODS_START_MANUAL": safe_str(item.get("GOODS_START_MANUAL")),
                                "GOODS_DURATION": safe_int(item.get("GOODS_DURATION"), 60),
                                "PLACE": safe_str(item.get("PLACE")),
                                "ADD_GOODS_START": safe_str(item.get("ADD_GOODS_START")),
                                "ADD_GOODS_DURATION": safe_int(item.get("ADD_GOODS_DURATION"), None),
                                "ADD_GOODS_PLACE": safe_str(item.get("ADD_GOODS_PLACE")),
                                "IS_POST_GOODS": bool(item.get("IS_POST_GOODS", False))
                            })
                        st.session_state.tt_artists_order = new_order
                        st.session_state.tt_artist_settings = new_artist_settings
                        st.session_state.tt_row_settings = new_row_settings
                        st.session_state.rebuild_table_flag = True
                    except Exception as e:
                        st.error(f"データ展開エラー: {e}")
                
                st.session_state.tt_current_proj_id = selected_id
                if "ws_active_project_id" not in st.session_state: st.rerun()

    def force_sync(): st.session_state.tt_unsaved_changes = True 
    def mark_dirty(): st.session_state.tt_unsaved_changes = True
    
    def import_csv_callback():
        uploaded = st.session_state.get("csv_upload_key")
        if not uploaded: return
        try:
            uploaded.seek(0)
            try:
                df_csv = pd.read_csv(uploaded)
            except UnicodeDecodeError:
                uploaded.seek(0)
                df_csv = pd.read_csv(uploaded, encoding="cp932")
            
            df_csv.columns = [c.strip() for c in df_csv.columns]
            
            temp_db = SessionLocal()
            try:
                artists_to_check = []
                col_group = "グループ名" if "グループ名" in df_csv.columns else next((c for c in df_csv.columns if c.lower() == "artist"), df_csv.columns[0])
                artists_to_check = [str(row.get(col_group, "")).strip() for _, row in df_csv.iterrows()]
                artists_to_check = list(set([a for a in artists_to_check if a and a != "nan"]))

                for artist_name in artists_to_check:
                    existing = temp_db.query(Artist).filter(Artist.name == artist_name).first()
                    if not existing:
                        new_artist = Artist(name=artist_name, image_filename=None)
                        temp_db.add(new_artist)
                temp_db.commit()
            except Exception as e:
                print(f"Auto reg error: {e}")
            finally:
                temp_db.close()
            
            new_order = []
            new_artist_settings = {}
            new_row_settings = []
            
            col_start = "START" if "START" in df_csv.columns else None
            col_end = "END" if "END" in df_csv.columns else None
            col_duration = "持ち時間" if "持ち時間" in df_csv.columns else "Duration"
            col_adj = "Adjustment" if "Adjustment" in df_csv.columns else None

            if not df_csv.empty and col_start:
                first_start_time = str(df_csv.iloc[0].get(col_start, "")).strip()
                if ":" in first_start_time:
                    try:
                        h, m = map(int, first_start_time.split(":"))
                        formatted_start = f"{h:02d}:{m:02d}"
                        st.session_state.tt_start_time = formatted_start
                    except:
                        pass 

            for i, row in df_csv.iterrows():
                name = str(row.get(col_group, ""))
                if name == "nan" or not name: continue 
                
                duration = safe_int(row.get(col_duration), 20)
                adjustment = 0
                
                if col_start and col_end and i < len(df_csv) - 1:
                    current_end = str(row.get(col_end, "")).strip()
                    next_start = str(df_csv.iloc[i+1].get(col_start, "")).strip()
                    if current_end and next_start:
                        adjustment = get_duration_minutes(current_end, next_start)
                        if adjustment < 0: adjustment = 0
                elif col_adj:
                    adjustment = safe_int(row.get(col_adj), 0)
                
                new_order.append(name)
                new_artist_settings[name] = {"DURATION": duration}
                
                g_start = safe_str(row.get("物販開始") or row.get("GoodsStart"))
                g_dur = safe_int(row.get("物販時間") or row.get("GoodsDuration"), 60)
                g_place = safe_str(row.get("物販場所") or row.get("Place") or "A")
                
                new_row_settings.append({
                    "ADJUSTMENT": adjustment,
                    "GOODS_START_MANUAL": g_start,
                    "GOODS_DURATION": g_dur,
                    "PLACE": g_place,
                    "ADD_GOODS_START": safe_str(row.get("AddGoodsStart")), 
                    "ADD_GOODS_DURATION": safe_int(row.get("AddGoodsDuration"), None), 
                    "ADD_GOODS_PLACE": safe_str(row.get("AddGoodsPlace")),
                    "IS_POST_GOODS": bool(row.get("IS_POST_GOODS", False))
                })

            st.session_state.tt_artists_order = new_order
            st.session_state.tt_artist_settings = new_artist_settings
            st.session_state.tt_row_settings = new_row_settings
            st.session_state.rebuild_table_flag = True 
            st.session_state.tt_unsaved_changes = True
            st.success(f"CSVを読み込みました (開演時間を {st.session_state.tt_start_time} に設定)")
        except Exception as e:
            st.error(f"読み込みエラー: {e}")

    if st.session_state.tt_current_proj_id:
        
        # 設定エリア
        col_p1, col_p2, col_p3 = st.columns(3)
        with col_p1: st.selectbox("開場時間", TIME_OPTIONS, key="tt_open_time", on_change=mark_dirty)
        with col_p2: st.selectbox("開演時間", TIME_OPTIONS, key="tt_start_time", on_change=mark_dirty)
        with col_p3: st.number_input("物販開始オフセット(分)", min_value=0, key="tt_goods_offset", on_change=mark_dirty)
        
        if st.button("🔄 時間を再計算して反映"):
            st.session_state.request_calc = True
            mark_dirty()

        with st.expander("📂 CSVから構成を読み込む"):
            st.file_uploader("CSVファイル", key="csv_upload_key")
            st.button("CSV反映", on_click=import_csv_callback)

        st.divider()

        # --- エディタ ---
        col_ui_left, col_ui_right = st.columns([1, 2.5])
        
        with col_ui_left:
            st.subheader("出演順")
            all_artists = db.query(Artist).filter(Artist.is_deleted == False).all()
            all_artists.sort(key=lambda x: x.name)
            available_to_add = [a.name for a in all_artists if a.name not in st.session_state.tt_artists_order]
            
            c_add1, c_add2 = st.columns([3, 1])
            with c_add1: new_artist = st.selectbox("追加", [""] + available_to_add, label_visibility="collapsed")
            with c_add2:
                if st.button("＋"):
                    if new_artist:
                        st.session_state.tt_artists_order.append(new_artist)
                        st.session_state.tt_artist_settings[new_artist] = {"DURATION": 20}
                        st.session_state.tt_row_settings.append(get_default_row_settings())
                        st.session_state.rebuild_table_flag = True 
                        mark_dirty()
                        st.rerun()

            st.caption("リスト操作")
            if sort_items:
                sorted_items = sort_items(st.session_state.tt_artists_order, direction="vertical")
                if sorted_items != st.session_state.tt_artists_order:
                    st.session_state.tt_artists_order = sorted_items
                    st.session_state.rebuild_table_flag = True; mark_dirty(); st.rerun()
            
            del_target = st.selectbox("削除対象", ["(選択なし)"] + st.session_state.tt_artists_order)
            if del_target != "(選択なし)":
                if st.button("削除実行"):
                    idx = st.session_state.tt_artists_order.index(del_target)
                    st.session_state.tt_artists_order.pop(idx)
                    if del_target in st.session_state.tt_artist_settings: del st.session_state.tt_artist_settings[del_target]
                    st.session_state.tt_row_settings.pop(idx)
                    st.session_state.rebuild_table_flag = True; mark_dirty(); st.rerun()

        with col_ui_right:
            st.subheader("タイムテーブル詳細")
            if st.checkbox("開演前物販を表示", value=st.session_state.tt_has_pre_goods, on_change=mark_dirty):
                if not st.session_state.tt_has_pre_goods: st.session_state.tt_has_pre_goods = True; st.session_state.rebuild_table_flag = True; st.rerun()
            else:
                if st.session_state.tt_has_pre_goods: st.session_state.tt_has_pre_goods = False; st.session_state.rebuild_table_flag = True; st.rerun()

            column_order = ["ARTIST", "DURATION", "IS_POST_GOODS", "ADJUSTMENT", "GOODS_START_MANUAL", "GOODS_DURATION", "PLACE", "ADD_GOODS_START", "ADD_GOODS_DURATION", "ADD_GOODS_PLACE"]
            
            if st.session_state.rebuild_table_flag:
                rows = []
                if st.session_state.tt_has_pre_goods:
                    p = st.session_state.tt_pre_goods_settings
                    rows.append({"ARTIST": "開演前物販", "DURATION":0, "ADJUSTMENT":0, "IS_POST_GOODS":False, 
                                 "GOODS_START_MANUAL": safe_str(p.get("GOODS_START_MANUAL")), "GOODS_DURATION": safe_int(p.get("GOODS_DURATION"), 60), "PLACE": "", 
                                 "ADD_GOODS_START":"", "ADD_GOODS_DURATION":None, "ADD_GOODS_PLACE":""})
                while len(st.session_state.tt_row_settings) < len(st.session_state.tt_artists_order):
                    st.session_state.tt_row_settings.append(get_default_row_settings())

                has_post = False
                for i, name in enumerate(st.session_state.tt_artists_order):
                    ad = st.session_state.tt_artist_settings.get(name, {"DURATION": 20})
                    rd = st.session_state.tt_row_settings[i]
                    is_p = bool(rd.get("IS_POST_GOODS", False))
                    if is_p: has_post = True
                    rows.append({
                        "ARTIST": name, "DURATION": safe_int(ad.get("DURATION"), 20), "IS_POST_GOODS": is_p,
                        "ADJUSTMENT": safe_int(rd.get("ADJUSTMENT"), 0),
                        "GOODS_START_MANUAL": safe_str(rd.get("GOODS_START_MANUAL")), "GOODS_DURATION": safe_int(rd.get("GOODS_DURATION"), 60), "PLACE": safe_str(rd.get("PLACE")),
                        "ADD_GOODS_START": safe_str(rd.get("ADD_GOODS_START")), "ADD_GOODS_DURATION": safe_int(rd.get("ADD_GOODS_DURATION"), None), "ADD_GOODS_PLACE": safe_str(rd.get("ADD_GOODS_PLACE"))
                    })
                if has_post:
                    p = st.session_state.tt_post_goods_settings
                    rows.append({"ARTIST": "終演後物販", "DURATION":0, "ADJUSTMENT":0, "IS_POST_GOODS":False,
                                 "GOODS_START_MANUAL": safe_str(p.get("GOODS_START_MANUAL")), "GOODS_DURATION": safe_int(p.get("GOODS_DURATION"), 60), "PLACE": "",
                                 "ADD_GOODS_START":"", "ADD_GOODS_DURATION":None, "ADD_GOODS_PLACE":""})

                st.session_state.binding_df = pd.DataFrame(rows, columns=column_order)
                st.session_state.tt_editor_key = st.session_state.get("tt_editor_key", 0) + 1
                st.session_state.rebuild_table_flag = False

            # --- Data Editor ---
            current_key = f"tt_editor_{st.session_state.tt_editor_key}"
            
            edited_df = pd.DataFrame(columns=column_order)
            if not st.session_state.binding_df.empty:
                if current_key in st.session_state:
                    if isinstance(st.session_state[current_key], pd.DataFrame):
                        st.session_state.binding_df = st.session_state[current_key]

            edited_df = st.data_editor(
                st.session_state.binding_df, key=current_key, num_rows="fixed", use_container_width=True,
                column_config={
                    "ARTIST": st.column_config.TextColumn("アーティスト", disabled=True),
                    "DURATION": st.column_config.SelectboxColumn("出演", options=DURATION_OPTIONS, width="small"),
                    "IS_POST_GOODS": st.column_config.CheckboxColumn("終演後", width="small"),
                    "ADJUSTMENT": st.column_config.SelectboxColumn("転換", options=ADJUSTMENT_OPTIONS, width="small"),
                    "GOODS_START_MANUAL": st.column_config.SelectboxColumn("物販開始", options=[""]+TIME_OPTIONS, width="small"),
                    "GOODS_DURATION": st.column_config.SelectboxColumn("物販分", options=GOODS_DURATION_OPTIONS, width="small"),
                    "PLACE": st.column_config.SelectboxColumn("場所", options=[""]+PLACE_OPTIONS, width="small"),
                    "ADD_GOODS_START": st.column_config.SelectboxColumn("追加開始", options=[""]+TIME_OPTIONS, width="small"),
                    "ADD_GOODS_DURATION": st.column_config.SelectboxColumn("追加分", options=GOODS_DURATION_OPTIONS, width="small"),
                    "ADD_GOODS_PLACE": st.column_config.SelectboxColumn("追加場所", options=[""]+PLACE_OPTIONS, width="small"),
                },
                hide_index=True, on_change=force_sync
            )
            
            new_row_settings_from_edit = []
            current_has_post_check = False
            for i, row in edited_df.iterrows():
                name = row["ARTIST"]
                is_post = bool(row.get("IS_POST_GOODS", False))
                
                if name == "開演前物販":
                    dur = get_duration_minutes(st.session_state.tt_open_time, st.session_state.tt_start_time)
                    st.session_state.tt_pre_goods_settings = {"GOODS_START_MANUAL": st.session_state.tt_open_time, "GOODS_DURATION": dur, "PLACE": ""}
                    continue
                if name == "終演後物販":
                    st.session_state.tt_post_goods_settings = {"GOODS_START_MANUAL": safe_str(row["GOODS_START_MANUAL"]), "GOODS_DURATION": safe_int(row["GOODS_DURATION"], 60), "PLACE": ""}
                    continue
                
                if is_post: current_has_post_check = True
                st.session_state.tt_artist_settings[name] = {"DURATION": safe_int(row["DURATION"], 20)}
                
                g_start = safe_str(row["GOODS_START_MANUAL"])
                g_dur = safe_int(row["GOODS_DURATION"], 60)
                add_start = safe_str(row["ADD_GOODS_START"])
                add_dur = safe_int(row["ADD_GOODS_DURATION"], None)
                add_place = safe_str(row["ADD_GOODS_PLACE"])
                
                if is_post:
                    g_start = ""; g_dur = 60; add_start = ""; add_dur = None; add_place = ""

                new_row_settings_from_edit.append({
                    "ADJUSTMENT": safe_int(row["ADJUSTMENT"], 0),
                    "GOODS_START_MANUAL": g_start, "GOODS_DURATION": g_dur, "PLACE": safe_str(row["PLACE"]),
                    "ADD_GOODS_START": add_start, "ADD_GOODS_DURATION": add_dur, "ADD_GOODS_PLACE": add_place,
                    "IS_POST_GOODS": is_post
                })
            
            if len(new_row_settings_from_edit) == len(st.session_state.tt_artists_order):
                st.session_state.tt_row_settings = new_row_settings_from_edit
            
            row_exists = any(r["ARTIST"] == "終演後物販" for r in st.session_state.binding_df.to_dict("records"))
            if (current_has_post_check and not row_exists) or (not current_has_post_check and row_exists):
                st.session_state.rebuild_table_flag = True; mark_dirty(); st.rerun()

            if st.session_state.request_calc:
                curr = datetime.strptime(st.session_state.tt_start_time, "%H:%M")
                for i, name in enumerate(st.session_state.tt_artists_order):
                    if i >= len(st.session_state.tt_row_settings): break
                    rd = st.session_state.tt_row_settings[i]
                    dur = st.session_state.tt_artist_settings[name].get("DURATION", 20)
                    
                    end_obj = curr + timedelta(minutes=dur)
                    if not rd.get("IS_POST_GOODS", False):
                        g_start_obj = end_obj + timedelta(minutes=st.session_state.tt_goods_offset)
                        rd["GOODS_START_MANUAL"] = g_start_obj.strftime("%H:%M")
                        st.session_state.tt_row_settings[i] = rd
                    
                    curr = end_obj + timedelta(minutes=rd.get("ADJUSTMENT", 0))
                
                if current_has_post_check:
                    st.session_state.tt_post_goods_settings["GOODS_START_MANUAL"] = curr.strftime("%H:%M")
                
                st.session_state.rebuild_table_flag = True; st.session_state.tt_editor_key += 1
                st.session_state.request_calc = False; st.success("計算完了"); st.rerun()

            # --- 結果表示 ---
            calculated_df = calculate_timetable_flow(edited_df, st.session_state.tt_open_time, st.session_state.tt_start_time)
            st.dataframe(calculated_df[["TIME_DISPLAY", "ARTIST", "GOODS_DISPLAY", "PLACE"]], use_container_width=True, hide_index=True)
            
            # --- フライヤー連携用データ準備 ---
            gen_list = []
            for _, row in calculated_df.iterrows():
                if row["ARTIST"] == "OPEN / START": continue
                gen_list.append([row["TIME_DISPLAY"], row["ARTIST"], row["GOODS_DISPLAY"], row["PLACE"]])
            st.session_state.tt_gen_list = gen_list
            
            st.divider()

            # --- ★追加: 画像生成・プレビューエリア ---
            all_fonts = [f for f in os.listdir(FONT_DIR) if f.lower().endswith(".ttf")]
            if not all_fonts: all_fonts = ["keifont.ttf"]
            
            # セッションの値がリストにない場合のガード
            if "tt_font" not in st.session_state or st.session_state.tt_font not in all_fonts:
                st.session_state.tt_font = all_fonts[0]
            
            # ★フォント見本パネル
            with st.expander("🔤 フォント一覧見本を表示"):
                specimen_img = create_font_specimen_img(FONT_DIR, all_fonts)
                if specimen_img:
                    st.image(specimen_img, use_container_width=True)
                else:
                    st.info("フォントが見つかりません")

            # ★修正: index引数を削除 (keyと競合するため)
            st.selectbox("プレビュー用フォント", all_fonts, key="tt_font")
            
            # 設定スナップショット
            current_tt_params = {
                "gen_list": gen_list,
                "font": st.session_state.tt_font
            }
            if "tt_last_generated_params" not in st.session_state: st.session_state.tt_last_generated_params = None

            # =================================================================
            # ★追加: 自動生成ロジック (画像がない場合に実行)
            # =================================================================
            if st.session_state.get("last_generated_tt_image") is None:
                if generate_timetable_image and gen_list:
                    try:
                        # 自動生成
                        auto_img = generate_timetable_image(gen_list, font_path=os.path.join(FONT_DIR, st.session_state.tt_font))
                        # 保存して最新状態にする
                        st.session_state.last_generated_tt_image = auto_img
                        st.session_state.tt_last_generated_params = current_tt_params
                    except Exception as e:
                        pass # 自動生成失敗時は何もしない

            # ボタン式
            if st.button("🔄 設定反映 (プレビュー生成)", type="primary", use_container_width=True, key="btn_tt_generate"):
                if generate_timetable_image:
                    if gen_list:
                        with st.spinner("画像を生成＆保存中..."):
                            try:
                                # 画像生成
                                img = generate_timetable_image(gen_list, font_path=os.path.join(FONT_DIR, st.session_state.tt_font))
                                
                                # セッションに保存
                                st.session_state.last_generated_tt_image = img
                                st.session_state.tt_last_generated_params = current_tt_params
                                
                                # ★DBへも保存
                                if save_current_project(db, selected_id):
                                    st.toast("保存＆プレビュー更新完了！", icon="✅")
                                else:
                                    st.error("DB保存に失敗しました")
                                    
                            except Exception as e:
                                st.error(f"生成エラー: {e}")
                    else:
                        st.warning("データがありません")
                else:
                    st.error("ロジックエラー: generate_timetable_image がロードされていません")

            # 判定ロジック
            is_outdated = False
            if st.session_state.tt_last_generated_params is None:
                is_outdated = True
            elif st.session_state.tt_last_generated_params != current_tt_params:
                is_outdated = True

            if st.session_state.get("last_generated_tt_image"):
                if is_outdated:
                    st.warning("⚠️ 設定が変更されています。最新の状態にするには「設定反映」ボタンを押してください。")
                    st.caption("👇 前回生成時のプレビュー")
                else:
                    st.caption("👇 現在のプレビュー")
                
                st.image(st.session_state.last_generated_tt_image, use_container_width=True)
            
            elif is_outdated:
                 st.info("👆 「設定反映」ボタンを押してプレビューを生成してください。")

    else:
        st.info("👈 上のボックスからプロジェクトを選択してください")
    
    db.close()
