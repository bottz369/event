import streamlit as st
import pandas as pd
import json
import io
import os
import requests
from datetime import datetime, date, timedelta
from sqlalchemy import text # SQL実行用

from database import get_db, SessionLocal, Artist, TimetableProject, AssetFile, Asset, get_image_url
from constants import (
    TIME_OPTIONS, DURATION_OPTIONS, ADJUSTMENT_OPTIONS, 
    GOODS_DURATION_OPTIONS, PLACE_OPTIONS, FONT_DIR, get_default_row_settings
)
from utils import safe_int, safe_str, get_duration_minutes, calculate_timetable_flow, create_business_pdf, create_font_specimen_img, get_sorted_font_list
from logic_project import load_timetable_rows

# Phase 2B-1b: save_active_project 経由に切替
# Phase 2B-2-b: session_manager + 純粋変換器を追加 (draft_rows 一本化)
from services import project_service, session_manager
from models.timetable import (
    PRE_GOODS_ARTIST_NAME,
    POST_GOODS_ARTIST_NAME,
    TimetableRowDraft,
    draft_rows_to_df,
    df_to_draft_rows,
)

try:
    from streamlit_sortables import sort_items
except ImportError:
    sort_items = None

import_error_msg = None
try:
    from logic_timetable import generate_timetable_image
except Exception as e:
    import_error_msg = str(e)
    generate_timetable_image = None

# --- DBマイグレーション（列追加）関数 ---
def check_and_migrate_add_goods_columns(db):
    """
    timetable_rows テーブルに追加物販用のカラムが存在するか確認し、
    なければ追加する（自動修復）
    """
    try:
        columns_to_add = [
            ("add_goods_start_time", "TEXT"),
            ("add_goods_duration", "INTEGER"),
            ("add_goods_place", "TEXT")
        ]

        for col_name, col_type in columns_to_add:
            try:
                db.execute(text(f"ALTER TABLE timetable_rows ADD COLUMN {col_name} {col_type}"))
                db.commit()
            except Exception:
                db.rollback()
                pass

    except Exception as e:
        print(f"Migration check error: {e}")

# --- フォント確保関数 ---
def ensure_font_exists(db, font_filename):
    if not font_filename: return None
    abs_font_dir = os.path.abspath(FONT_DIR)
    os.makedirs(abs_font_dir, exist_ok=True)
    file_path = os.path.join(abs_font_dir, font_filename)

    if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
        return file_path

    try:
        asset = db.query(Asset).filter(Asset.image_filename == font_filename).first()
        if asset:
            url = get_image_url(asset.image_filename)
            if url:
                response = requests.get(url, timeout=10)
                if response.status_code == 200:
                    with open(file_path, "wb") as f:
                        f.write(response.content)
                    st.toast(f"フォント(URL)を準備しました: {font_filename}", icon="🔤")
                    return file_path
    except Exception as e:
        print(f"URL Font Download Error: {e}")

    try:
        asset_file = db.query(AssetFile).filter(AssetFile.filename == font_filename).first()
        if asset_file and asset_file.file_data:
            with open(file_path, "wb") as f:
                f.write(asset_file.file_data)
            st.toast(f"フォント(DB)を準備しました: {font_filename}", icon="🔤")
            return file_path
    except Exception as e:
        print(f"Binary Font Write Error: {e}")

    return None


# Phase 3 Fix2: check_and_migrate_add_goods_columns をプロセス 1 回のみに削減。
# 本体ロジック (ALTER TABLE × 3 を duplicate column で握りつぶす冪等 DDL) は変更しない。
# render_timetable_page は workspace の eager タブ描画で毎レンダ呼ばれるため、
# 旧仕様だと 1 rerun あたり 3 DDL のラウンドトリップが発生していた。
# @st.cache_resource で初回 1 回のみ実行、2 回目以降はキャッシュヒットで ~0ms に。
# 完全撤去は将来の timetable.py 全面書き換え時に行う(壊さない優先)。
@st.cache_resource
def _ensure_goods_columns_migrated():
    db = SessionLocal()
    try:
        check_and_migrate_add_goods_columns(db)
    finally:
        db.close()
    return True


# Phase 2B-2-b: editor key bump helper.
# 旧構造は「mutation → rebuild_table_flag = True → rebuild ブロック (L447) で
# tt_editor_key += 1」の間接構造だった。新構造では各 mutation 直後にこの
# helper を直接呼び、editor を強制 reset する(rebuild_table_flag 経由を撤去)。
# tt_editor_key の名前は据え置き(rename は -c 以降)。
def _bump_editor_seq():
    st.session_state["tt_editor_key"] = st.session_state.get("tt_editor_key", 0) + 1


# Phase 2B-2-b: 特殊行 (開演前/終演後物販) を draft_rows へ insert する factory。
# 仕様固定フィールド (duration=0 / adjustment=0 / is_post_goods=False / place=""
# / add_goods_* 空) は TimetableRowDraft デフォルト値と同じ。開演前物販の
# goods_start_time/goods_duration は open_time から自動計算 (旧 L485-488 と等価)。
def _make_pre_goods_row():
    open_time = st.session_state.get("tt_open_time", "10:00")
    start_time = st.session_state.get("tt_start_time", "10:30")
    pre_dur = get_duration_minutes(open_time, start_time)
    return TimetableRowDraft(
        artist_name=PRE_GOODS_ARTIST_NAME,
        duration=0,
        adjustment=0,
        is_post_goods=False,
        is_hidden=False,
        goods_start_time=open_time,
        goods_duration=pre_dur,
        place="",
    )


def _make_post_goods_row():
    # goods_start_time は再計算ボタン経由で設定されるため空で初期化。
    return TimetableRowDraft(
        artist_name=POST_GOODS_ARTIST_NAME,
        duration=0,
        adjustment=0,
        is_post_goods=False,
        is_hidden=False,
        goods_start_time="",
        goods_duration=60,
        place="",
    )


# Phase 2B-2-b: 特殊行の仕様固定フィールド強制リセット (旧 L484-499 と等価)。
# editor で特殊行が誤って編集されても、render 毎にこの正規化で固定値に戻す。
# 開演前物販: goods_start_time / goods_duration を open_time から強制再計算
#             (UI 上で変えても次 render で上書きされる)。
# 終演後物販: goods_start_time / goods_duration / is_hidden はユーザー編集を許容、
#             その他は仕様で 0/""/None。
# 注意: 特殊行 itself の is_post_goods は False が仕様 (集約計算から除外するため)。
def _normalize_edited_rows(rows):
    open_time = st.session_state.get("tt_open_time", "10:00")
    start_time = st.session_state.get("tt_start_time", "10:30")
    pre_dur = get_duration_minutes(open_time, start_time)
    for r in rows:
        if r.is_pre_goods_row:
            r.duration = 0
            r.adjustment = 0
            r.is_post_goods = False
            r.place = ""
            r.add_goods_start_time = ""
            r.add_goods_duration = None
            r.add_goods_place = ""
            r.goods_start_time = open_time
            r.goods_duration = pre_dur
        elif r.is_post_goods_row:
            r.duration = 0
            r.adjustment = 0
            r.is_post_goods = False
            r.place = ""
            r.add_goods_start_time = ""
            r.add_goods_duration = None
            r.add_goods_place = ""
    return rows


def render_timetable_page():
    if "ws_active_project_id" not in st.session_state or st.session_state.ws_active_project_id is None:
        st.title("⏱️ タイムテーブル作成")

    db = next(get_db())

    _ensure_goods_columns_migrated()
    
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
        # Phase 2B-2-c: last_check_key block を撤去 (旧 rebuild_table_flag セット用の
        # dead block。draft_rows ベースでは open_time 変化は editor 再表示時に
        # _normalize_edited_rows が draft_rows[開演前物販].goods_start_time を
        # 自動上書きするため、ここで何もする必要がない)。

        # --- プロジェクトデータの読み込み ---
        if st.session_state.get("tt_current_proj_id") != selected_id:
            proj = db.query(TimetableProject).filter(TimetableProject.id == selected_id).first()
            if proj:
                st.session_state.tt_title = proj.title
                try: st.session_state.tt_event_date = datetime.strptime(proj.event_date, "%Y-%m-%d").date() if proj.event_date else date.today()
                except: st.session_state.tt_event_date = date.today()
                st.session_state.tt_venue = proj.venue_name
                
                if "tt_open_time" not in st.session_state:
                     st.session_state.tt_open_time = proj.open_time or "10:00"
                if "tt_start_time" not in st.session_state:
                     st.session_state.tt_start_time = proj.start_time or "10:30"
                if "tt_goods_offset" not in st.session_state:
                     st.session_state.tt_goods_offset = proj.goods_start_offset if proj.goods_start_offset is not None else 5
                
                if "tt_font" not in st.session_state:
                    st.session_state.tt_font = "keifont.ttf"
                
                if proj.settings_json:
                    try:
                        settings = json.loads(proj.settings_json)
                        if "tt_font" in settings:
                            st.session_state.tt_font = settings["tt_font"]
                        if "tt_columns" in settings:
                            st.session_state.tt_columns = settings["tt_columns"]
                    except: pass
                
                if "tt_columns" not in st.session_state:
                    st.session_state.tt_columns = 2
                # Phase 2B-2-d: 旧6状態のDBロード展開を撤去。draft_rows は reload_project()
                # 経由 (timetable_repo.load_rows: timetable_rows→data_json) で直接埋まる。
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
            
            # Phase 2B-2-b ③ Edit B: CSV パース結果を draft_rows に直接書き戻す。
            # 既存 draft_rows の開演前物販行は保持、通常行は CSV で全置換、
            # 終演後物販は (CSV に IS_POST_GOODS=True があれば) 次 rerun の②集約 trigger で append。
            # 旧 6 状態 (tt_artists_order / tt_artist_settings / tt_row_settings) への
            # 書き戻しは撤去 (sentinel で _rebuild_from_legacy が skip されるため反映されない)。
            new_rows = []

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
                if name == "nan" or not name:
                    continue
                # ★ ガード: CSV に「開演前物販」「終演後物販」名行が含まれた場合は skip。
                # 特殊行は existing_pre 保持 + ②集約による終演後物販 append で管理する。
                # ガードなしだと: 開演前物販の二重化、終演後物販の auto-pop で意図と乖離。
                # (scratch/probe_csv_special_row_names.py で検証済み)
                if name in (PRE_GOODS_ARTIST_NAME, POST_GOODS_ARTIST_NAME):
                    continue

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

                g_start = safe_str(row.get("物販開始") or row.get("GoodsStart"))
                g_dur = safe_int(row.get("物販時間") or row.get("GoodsDuration"), 60)
                g_place = safe_str(row.get("物販場所") or row.get("Place") or "A")
                add_start = safe_str(row.get("AddGoodsStart"))
                add_dur = safe_int(row.get("AddGoodsDuration"), None)
                add_place = safe_str(row.get("AddGoodsPlace"))
                is_post = bool(row.get("IS_POST_GOODS", False))

                # 重複アーティスト名は旧と等価で append (除外なし)。
                # place は g_place ("A" 既定) で旧 get_default_row_settings と等価。
                new_rows.append(TimetableRowDraft(
                    artist_name=name,
                    duration=duration,
                    adjustment=adjustment,
                    is_post_goods=is_post,
                    is_hidden=False,
                    goods_start_time=g_start,
                    goods_duration=g_dur,
                    place=g_place,
                    add_goods_start_time=add_start,
                    add_goods_duration=add_dur,
                    add_goods_place=add_place,
                ))

            # 既存 draft_rows の開演前物販行を保持 + CSV 通常行で全置換。
            # 終演後物販は CSV 内 IS_POST_GOODS=True があれば、次 rerun の②集約で append される。
            existing_draft = session_manager.get_draft_rows()
            existing_pre = next((r for r in existing_draft if r.is_pre_goods_row), None)
            final_rows = ([existing_pre] if existing_pre else []) + new_rows
            session_manager.set_draft_rows(final_rows)
            if final_rows:
                st.session_state["tt_draft_authoritative"] = True
            # 構造変化 (CSV 全置換) なので editor key を bump して editor を強制 reset。
            _bump_editor_seq()
            st.session_state.tt_unsaved_changes = True
            # ★ on_click 内なので st.rerun() は呼ばない (Streamlit が自動 rerun)。
            st.success(f"CSVを読み込みました (開演時間を {st.session_state.tt_start_time} に設定)")
        except Exception as e:
            st.error(f"読み込みエラー: {e}")

    if st.session_state.tt_current_proj_id:
        
        # 設定エリア
        col_p1, col_p2, col_p3 = st.columns(3)

        # OPEN / START は read-only 表示(編集は概要タブで行う)。
        # Phase 2B-1b で widget key 競合(罠10)を解消するため selectbox を削除。
        open_time_display = st.session_state.get("tt_open_time") or "未設定"
        start_time_display = st.session_state.get("tt_start_time") or "未設定"
        with col_p1:
            st.metric(label="開場時間", value=open_time_display)
        with col_p2:
            st.metric(label="開演時間", value=start_time_display)

        with col_p3: st.number_input("物販開始オフセット(分)", min_value=0, key="tt_goods_offset", on_change=mark_dirty)

        st.caption("ℹ️ OPEN / START の変更はイベント概要タブで行ってください。")
        
        if st.button("🔄 時間を再計算して反映"):
            st.session_state.request_calc = True
            mark_dirty()

        with st.expander("📂 CSVから構成を読み込む"):
            st.file_uploader("CSVファイル", key="csv_upload_key")
            st.button("CSV反映", on_click=import_csv_callback)

        st.divider()

        # --- エディタ ---
        # Phase 2B-2-b commit 2 まとまり①②:
        # draft_rows を render 全体で 1 回取得し、左右カラムで共有する。
        # sentinel `tt_draft_authoritative` は draft_rows が空でないときだけ立てる
        # (空で立てると sync_session_to_draft 側の safety net が skip され、
        # 空が真実化してデータ消失に見えるため)。
        draft_rows = session_manager.get_draft_rows()
        if draft_rows:
            st.session_state["tt_draft_authoritative"] = True

        col_ui_left, col_ui_right = st.columns([1, 2.5])

        with col_ui_left:
            st.subheader("出演順")
            all_artists = db.query(Artist).filter(Artist.is_deleted == False).all()
            all_artists.sort(key=lambda x: x.name)
            existing_normal_names = {r.artist_name for r in draft_rows if not r.is_special_row}
            available_to_add = [a.name for a in all_artists if a.name not in existing_normal_names]

            c_add1, c_add2 = st.columns([3, 1])
            with c_add1: new_artist = st.selectbox("追加", [""] + available_to_add, label_visibility="collapsed")
            with c_add2:
                if st.button("＋"):
                    if new_artist:
                        # place="A" は旧 get_default_row_settings() の "PLACE": "A" と等価。
                        # 他フィールドは TimetableRowDraft のデフォルト (duration=20 等) で旧と一致。
                        new_row = TimetableRowDraft(artist_name=new_artist, place="A")
                        # 終演後物販行があればその直前 (= 通常行末尾) に挿入、なければ末尾。
                        post_idx = next((i for i, r in enumerate(draft_rows) if r.is_post_goods_row), None)
                        if post_idx is None:
                            draft_rows.append(new_row)
                        else:
                            draft_rows.insert(post_idx, new_row)
                        session_manager.set_draft_rows(draft_rows)
                        _bump_editor_seq()
                        mark_dirty()
                        st.rerun()

            st.caption("リスト操作")
            if sort_items:
                # 通常行のみ sort_items に渡す。特殊行は固定位置 (開演前=先頭、終演後=末尾)。
                normal_names = [r.artist_name for r in draft_rows if not r.is_special_row]
                sorted_items = sort_items(normal_names, direction="vertical")
                if sorted_items != normal_names:
                    pre_row = next((r for r in draft_rows if r.is_pre_goods_row), None)
                    post_row = next((r for r in draft_rows if r.is_post_goods_row), None)
                    name_to_row = {r.artist_name: r for r in draft_rows if not r.is_special_row}
                    new_rows = []
                    if pre_row:
                        new_rows.append(pre_row)
                    for n in sorted_items:
                        if n in name_to_row:
                            new_rows.append(name_to_row[n])
                    if post_row:
                        new_rows.append(post_row)
                    session_manager.set_draft_rows(new_rows)
                    _bump_editor_seq()
                    mark_dirty()
                    st.rerun()

            normal_names_for_del = [r.artist_name for r in draft_rows if not r.is_special_row]
            del_target = st.selectbox("削除対象", ["(選択なし)"] + normal_names_for_del)
            if del_target != "(選択なし)":
                if st.button("削除実行"):
                    new_rows = [
                        r for r in draft_rows
                        if not (r.artist_name == del_target and not r.is_special_row)
                    ]
                    session_manager.set_draft_rows(new_rows)
                    _bump_editor_seq()
                    mark_dirty()
                    st.rerun()

        with col_ui_right:
            st.subheader("タイムテーブル詳細")
            # 開演前物販トグル: draft_rows の先頭が pre_goods か否かを真実として扱う。
            has_pre = any(r.is_pre_goods_row for r in draft_rows)
            if st.checkbox("開演前物販を表示", value=has_pre, on_change=mark_dirty):
                if not has_pre:
                    draft_rows.insert(0, _make_pre_goods_row())
                    session_manager.set_draft_rows(draft_rows)
                    _bump_editor_seq()
                    mark_dirty()
                    st.rerun()
            else:
                if has_pre:
                    draft_rows = [r for r in draft_rows if not r.is_pre_goods_row]
                    session_manager.set_draft_rows(draft_rows)
                    _bump_editor_seq()
                    mark_dirty()
                    st.rerun()

            editor_df = draft_rows_to_df(draft_rows)
            current_key = f"tt_editor_{st.session_state.get('tt_editor_key', 0)}"

            edited_df = st.data_editor(
                editor_df, key=current_key, num_rows="fixed", width='stretch',
                column_config={
                    "IS_HIDDEN": st.column_config.CheckboxColumn("非表示", width="small"),
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

            # 編集内容を draft_rows に書き戻す (df_to_draft_rows 一本化、手動分解廃止)。
            # _normalize_edited_rows を != 比較の前に通すことで、特殊行の仕様固定
            # フィールド (開演前物販の goods_start_time/goods_duration 自動再計算など)
            # を毎 render で強制反映する (旧 L484-499 と等価)。編集なし時は round-trip
            # で edited_rows == draft_rows となり、set/mark_dirty 共に走らない。
            edited_rows = df_to_draft_rows(edited_df)
            _normalize_edited_rows(edited_rows)
            if edited_rows != draft_rows:
                session_manager.set_draft_rows(edited_rows)
                draft_rows = edited_rows
                mark_dirty()

            # Phase 2B-2-b commit 2 まとまり②: 終演後物販トグルの収束ロジック。
            # editor の IS_POST_GOODS チェック集約 (通常行のみ) と draft_rows 内の
            # 終演後物販行の存在の不一致を検知して append/pop で整合させる。
            # 旧 L520-522 の row_exists 判定を draft_rows ベースに置換。
            # 収束根拠: mutation 後は has_post_check ⇄ has_post_row が必ず一致するため、
            #           次 rerun で再度この不一致検知に入らない → 無限 rerun しない
            #           (scratch/probe_post_goods_convergence.py で multi-rerun 検証済み)。
            has_post_check = any(r.is_post_goods for r in draft_rows if not r.is_special_row)
            has_post_row = any(r.is_post_goods_row for r in draft_rows)
            if has_post_check and not has_post_row:
                draft_rows.append(_make_post_goods_row())
                session_manager.set_draft_rows(draft_rows)
                _bump_editor_seq()
                mark_dirty()
                st.rerun()
            elif not has_post_check and has_post_row:
                draft_rows = [r for r in draft_rows if not r.is_post_goods_row]
                session_manager.set_draft_rows(draft_rows)
                _bump_editor_seq()
                mark_dirty()
                st.rerun()

            # 後段 (再計算/データ表示) で使う集約フラグ。draft_rows ベース。
            current_has_post_check = has_post_check

            # --- 再計算 ---
            # Phase 2B-2-b ③ Edit ③-3: 6 状態への mutation を draft_rows mutation に置換。
            # 旧 bump (rebuild_table_flag = True; tt_editor_key += 1) を _bump_editor_seq() に直接化。
            # IS_POST_GOODS=True 通常行は duration/adjustment ぶん curr を進めるが
            # goods_start_time は書き換えない (旧と等価、scratch/probe_recalc_legacy_vs_new.py で数値一致確認済み)。
            # 開演前物販は計算外、終演後物販行は末尾 curr を書き込む。
            if st.session_state.request_calc:
                curr = datetime.strptime(st.session_state.tt_start_time, "%H:%M")
                for r in draft_rows:
                    if r.is_special_row:
                        continue
                    end_obj = curr + timedelta(minutes=r.duration)
                    if not r.is_post_goods:
                        g_start_obj = end_obj + timedelta(minutes=st.session_state.tt_goods_offset)
                        r.goods_start_time = g_start_obj.strftime("%H:%M")
                    curr = end_obj + timedelta(minutes=r.adjustment)
                # 終演後物販行があれば末尾の goods_start_time を curr に設定
                # (旧 tt_post_goods_settings["GOODS_START_MANUAL"] = curr.strftime(...) 相当)
                for r in draft_rows:
                    if r.is_post_goods_row:
                        r.goods_start_time = curr.strftime("%H:%M")
                        break
                session_manager.set_draft_rows(draft_rows)
                _bump_editor_seq()
                st.session_state.request_calc = False
                st.success("計算完了")
                st.rerun()

            # --- データ表示 ---
            calculated_df = calculate_timetable_flow(edited_df, st.session_state.tt_open_time, st.session_state.tt_start_time)
            st.dataframe(calculated_df[["TIME_DISPLAY", "ARTIST", "GOODS_DISPLAY", "PLACE"]], width='stretch', hide_index=True)
            
            # 画像生成用リスト (IS_HIDDEN対応)
            gen_list = []
            hidden_flags = []
            if "IS_HIDDEN" in edited_df.columns:
                hidden_flags = edited_df["IS_HIDDEN"].tolist()
            else:
                hidden_flags = [False] * len(edited_df)
            
            edited_row_idx = 0
            
            for _, row in calculated_df.iterrows():
                if row["ARTIST"] == "OPEN / START": 
                    continue
                
                is_hidden = False
                if edited_row_idx < len(hidden_flags):
                    is_hidden = hidden_flags[edited_row_idx]
                
                edited_row_idx += 1
                
                if is_hidden:
                    continue
                
                gen_list.append([row["TIME_DISPLAY"], row["ARTIST"], row["GOODS_DISPLAY"], row["PLACE"]])

            st.session_state.tt_gen_list = gen_list
            
            st.divider()

            # --- 画像生成エリア ---
            sorted_fonts = get_sorted_font_list(db)
            font_file_list = [item["filename"] for item in sorted_fonts]
            font_display_map = {item["filename"]: item["name"] for item in sorted_fonts}
            
            if not font_file_list:
                font_file_list = ["keifont.ttf"]
                font_display_map = {"keifont.ttf": "標準フォント (未設定)"}
            
            current_filename = st.session_state.get("tt_font", font_file_list[0])
            if current_filename not in font_file_list:
                current_filename = font_file_list[0]
                st.session_state.tt_font = current_filename

            with st.expander("🔤 フォント一覧見本を表示"):
                with st.container(height=300):
                    specimen_list = sorted(sorted_fonts, key=lambda x: x["filename"].lower())
                    specimen_img = create_font_specimen_img(db, specimen_list)
                    if specimen_img: st.image(specimen_img, width='stretch')
                    else: st.info("フォントが見つかりません")

            c_font, c_col = st.columns([2, 1])
            with c_font:
                st.selectbox(
                    "プレビュー用フォント", 
                    font_file_list,
                    format_func=lambda x: font_display_map.get(x, x),
                    key="tt_font" 
                )

            # ==========================================
            # ★自動判定: 24組以上の場合は強制的に2列にする
            # ==========================================
            artist_count = len(gen_list)
            
            if artist_count >= 24:
                # 24組以上の場合は警告を出し、選択肢を2列のみに固定
                st.warning("⚠️ 24組以上のため、可読性確保の観点から自動的に「2列」レイアウトで生成されます。")
                col_options = [2]
                if st.session_state.get("tt_columns", 2) != 2:
                    st.session_state.tt_columns = 2
            else:
                col_options = [1, 2]

            with c_col:
                st.radio(
                    "画像生成の列数",
                    options=col_options,
                    format_func=lambda x: f"{x}列",
                    horizontal=True,
                    key="tt_columns"
                )
            
            current_tt_params = {
                "gen_list": gen_list,
                "font": st.session_state.tt_font,
                "columns": st.session_state.tt_columns 
            }
            if "tt_last_generated_params" not in st.session_state: st.session_state.tt_last_generated_params = None

            # Phase 3 stop-autogen: render 時の TT 画像自動生成を廃止。
            # 生成は下記「🔄 設定反映 (プレビュー生成)」ボタン押下時のみ。
            # workspace の eager タブ描画でプロジェクトを開くだけで 20 秒級の
            # 画像生成が走る問題を解消する。生成関数本体・速度は無変更。

            if st.button("🔄 設定反映 (プレビュー生成)", type="primary", width='stretch', key="btn_tt_generate"):
                if import_error_msg:
                    st.error(f"ロジックファイルの読み込みに失敗しています: {import_error_msg}")
                elif generate_timetable_image:
                    if gen_list:
                        ensure_font_exists(db, st.session_state.tt_font)

                        with st.spinner("画像を生成＆保存中..."):
                            try:
                                font_path = os.path.join(os.path.abspath(FONT_DIR), st.session_state.tt_font)

                                # 画像生成
                                img = generate_timetable_image(gen_list, font_path=font_path, columns=st.session_state.tt_columns)
                                st.session_state.last_generated_tt_image = img
                                st.session_state.tt_last_generated_params = current_tt_params

                                # Phase 2B-1b: save_active_project() 経由で保存
                                # sync_session_to_draft が tt_open_time / tt_start_time / tt_goods_offset /
                                # tt_font / tt_columns を draft_project に同期 → apply_draft で DB へ書き出す。
                                if project_service.save_active_project():
                                    st.toast("保存＆プレビュー更新完了！", icon="✅")
                                else:
                                    st.error("保存に失敗しました")

                            except Exception as e:
                                st.error(f"生成エラー: {e}")
                    else:
                        st.warning("データがありません")
                else:
                    st.error("ロジックエラー: 理由不明のロード失敗です。アプリを再起動してください。")

            is_outdated = False
            if st.session_state.tt_last_generated_params is None: is_outdated = True
            elif st.session_state.tt_last_generated_params != current_tt_params: is_outdated = True

            if st.session_state.get("last_generated_tt_image"):
                if is_outdated:
                    st.warning("⚠️ 設定が変更されています。最新の状態にするには「設定反映」ボタンを押してください。")
                    st.caption("👇 前回生成時のプレビュー")
                else:
                    st.caption("👇 現在のプレビュー")
                st.image(st.session_state.last_generated_tt_image, width='stretch')
            else:
                # Phase 3 stop-autogen: 自動生成廃止に伴い、画像未生成時は常にプレースホルダ。
                st.info("👆 「設定反映」ボタンを押してプレビューを生成してください。")

    else:
        st.info("👈 上のボックスからプロジェクトを選択してください")
    
    db.close()
