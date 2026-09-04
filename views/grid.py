import streamlit as st
import os
import io

import pandas as pd

from database import IMAGE_DIR
from constants import FONT_DIR
from models.timetable import build_grid_hidden_from_rows, build_grid_order_from_rows
from services import (
    project_service,
    artist_service,
    font_service,
    session_manager,
)

# 段階②: streamlit_sortables のドラッグ&ドロップ並べ替えは廃止した。
# 並び順の唯一の正はタイムテーブルの「アー写グリッド表示順」列(番号)で、
# ここは build_grid_order_from_rows の結果を表示するだけ。

try:
    from logic_grid import generate_grid_image, load_image_from_url
except ImportError:
    generate_grid_image = None
    load_image_from_url = None


# =========================================================
# 保存ハンドラから呼ばれる公開関数(統合保存ボタン用)
# =========================================================
def regenerate_grid_preview():
    """保存後の状態からアー写グリッド画像を作り直す。成功で True。

    並び順は TT の GRID_NO 由来 (fold_grid_order_from_rows が session の
    grid_order へ畳んだもの) を使うので、プレビュー・生成画像・DB 保存値の
    3 つが必ず一致する。生成はこの関数(= 保存ハンドラ)からのみ呼ぶ
    (レンダー毎の自動生成は罠16 / Phase 3 stop-autogen で禁止)。
    """
    if generate_grid_image is None:
        st.error("ロジックファイル (logic_grid) の読み込みに失敗しています")
        return False

    order = list(st.session_state.get("grid_order") or [])
    target_artists = artist_service.get_artists_by_names(order)
    if not target_artists:
        st.warning("表示するアーティストデータがありません。")
        return False

    font_service.ensure_font_available(st.session_state.grid_font)

    try:
        parsed_counts = [
            int(x.strip())
            for x in str(st.session_state.grid_row_counts_str).split(",")
            if x.strip()
        ]
    except Exception:
        parsed_counts = []

    try:
        is_brick = (st.session_state.grid_layout_mode == "レンガ (サイズ統一)")
        align_map = {"左揃え": "left", "中央揃え": "center", "右揃え": "right"}
        align_val = align_map.get(st.session_state.grid_alignment, "center")
        abs_font_path = os.path.join(
            os.path.abspath(FONT_DIR), st.session_state.grid_font
        )
        img = generate_grid_image(
            target_artists,
            IMAGE_DIR,
            font_path=abs_font_path,
            row_counts=parsed_counts or None,
            is_brick_mode=is_brick,
            alignment=align_val,
        )
    except Exception as e:
        st.error(f"アー写グリッド画像の生成エラー: {e}")
        return False

    if not img:
        st.error("アー写グリッド画像の生成に失敗しました")
        return False

    st.session_state.last_generated_grid_image = img
    st.session_state.grid_last_generated_params = {
        "order": order,
        "row_counts": st.session_state.grid_row_counts_str,
        "layout_mode": st.session_state.grid_layout_mode,
        "alignment": st.session_state.grid_alignment,
        "font": st.session_state.grid_font,
        "rows": st.session_state.grid_rows,
    }
    return True


def render_grid_page():
    if "ws_active_project_id" not in st.session_state or st.session_state.ws_active_project_id is None:
        st.title("🖼️ アー写グリッド作成")

    if generate_grid_image is None:
        st.error("⚠️ `logic_grid.py` の読み込みに失敗しています。")

    try:
        selected_id = st.session_state.get("ws_active_project_id")
        
        # --- (プロジェクト選択ロジック) ---
        if not selected_id:
            pairs = project_service.list_projects_for_selector()
            if pairs:
                id_to_label = {pid: label for pid, label in pairs}
                options = [None] + [pid for pid, _ in pairs]
                selected_id = st.selectbox(
                    "プロジェクト選択",
                    options,
                    format_func=lambda pid: "(選択)" if pid is None else id_to_label[pid],
                )

        # セッション初期化 (デフォルト値)
        if "grid_order" not in st.session_state: st.session_state.grid_order = []
        if "grid_rows" not in st.session_state: st.session_state.grid_rows = 5
        
        # ★★★ 自動クリーニング処理 (ここを追加) ★★★
        # セッション内のリストにスペースが含まれていたら、強制的に削除して上書きする
        if st.session_state.grid_order:
            cleaned_order = [name.strip() for name in st.session_state.grid_order if name]
            # 変更があれば反映
            if st.session_state.grid_order != cleaned_order:
                st.session_state.grid_order = cleaned_order
                st.toast("リスト内の不要なスペースを自動削除しました 🧹", icon="✨")
        # ★★★★★★★★★★★★★★★★★★★★★★★★★

        if "grid_row_counts_str" not in st.session_state: st.session_state.grid_row_counts_str = "5,5,5,5,5"
        if "grid_alignment" not in st.session_state: st.session_state.grid_alignment = "中央揃え"
        if "grid_layout_mode" not in st.session_state: st.session_state.grid_layout_mode = "レンガ (サイズ統一)"
        if "grid_font" not in st.session_state: st.session_state.grid_font = "keifont.ttf"
        if "grid_last_generated_params" not in st.session_state: st.session_state.grid_last_generated_params = None
        
        if selected_id:
            # 段階②: 旧「grid_order が空なら TT の逆順で埋める」初期化を撤去。
            # 並び順は build_grid_order_from_rows(draft_rows) から毎 render 導出するため、
            # ここで session の grid_order を書くと TT の番号と競合する writer になる
            # (他タブの保存で sync_session_to_draft が拾い、DB の order が TT と食い違う)。
            st.divider()
            
            # --- 設定エリア ---
            def reset_grid_settings():
                current_id_in_cb = st.session_state.get("ws_active_project_id")
                if not current_id_in_cb: return

                try:
                    # 段階②: 並び順(grid_order)の書き戻しは撤去。順序は TT の
                    # 「アー写グリッド表示順」が唯一の正なので、ここで上書きすると
                    # TT と食い違う。リセットするのはレイアウト設定だけ。
                    # grid_just_reset も撤去(sort_items の stale 戻り値対策専用だった)。
                    st.session_state.grid_rows = 5
                    st.session_state.grid_row_counts_str = "5,5,5,5,5"
                    st.session_state.grid_font = "keifont.ttf"
                    st.toast("レイアウト設定を初期値に戻しました", icon="🔄")

                except Exception as e:
                    print(f"Reset Error: {e}")
                    st.error(f"リセットエラー: {e}")

            c_set1, c_set2 = st.columns([1, 2])
            with c_set1: 
                new_rows = st.number_input("行数", min_value=1, key="grid_rows")
            with c_set2:
                st.button("レイアウト設定をリセット", key="btn_grid_reset", on_click=reset_grid_settings)

            # --- 行ごとの枚数設定 ---
            # widget を SSOT (grid_row_counts_str) に直バインド。value=/手動書き戻しは付けない。
            st.text_input(
                "各行の枚数設定 (カンマ区切り)",
                help="例: 3,4,6 と入力すると、1行目3枚、2行目4枚、3行目6枚になります。",
                key="grid_row_counts_str"
            )

            # 生成に渡す値は行数(new_rows)に合わせてローカル整形する（SSOT には焼き戻さない）。
            try:
                parsed_counts = [int(x.strip()) for x in st.session_state.grid_row_counts_str.split(",") if x.strip()]
            except Exception:
                st.error("数値とカンマで入力してください")
                parsed_counts = [5] * new_rows

            if len(parsed_counts) < new_rows:
                parsed_counts += [5] * (new_rows - len(parsed_counts))
            elif len(parsed_counts) > new_rows:
                parsed_counts = parsed_counts[:new_rows]

            # --- レイアウト詳細設定 ---
            with st.expander("📐 レイアウト調整 (揃え・モード)", expanded=True):
                c_lay1, c_lay2 = st.columns(2)
                with c_lay1:
                    st.radio("配置モード", ["レンガ (サイズ統一)", "両端揃え (拡大縮小)"], key="grid_layout_mode", horizontal=True)
                with c_lay2:
                    disabled = (st.session_state.grid_layout_mode == "両端揃え (拡大縮小)")
                    st.radio("行の配置 (レンガモード時)", ["左揃え", "中央揃え", "右揃え"], key="grid_alignment", horizontal=True, disabled=disabled)

            # --- 並び順プレビュー(読み取り専用) ---
            # 段階②: ドラッグ&ドロップ並べ替えを撤去した。理由:
            #  - 1 ドラッグごとに component の値返し + st.rerun() で 2 回スクリプトが
            #    走り、workspace の st.tabs が全 4 タブを毎回 eager 描画するため重い。
            #  - sort_items を key 無しで呼んでいたため、items が変わるたびに
            #    コンポーネントが再マウントして状態を失い、古い戻り値と新しい値が
            #    ping-pong して操作不能になることがあった(grid_just_reset は
            #    その場当たり対処。併せて撤去)。
            # 並び順の唯一の正は TT の「アー写グリッド表示順」列。ここは表示のみで、
            # session_state への書き込みも st.rerun() も行わない。
            _tt_rows = session_manager.get_draft_rows()
            tt_order = build_grid_order_from_rows(_tt_rows)
            tt_grid_hidden = build_grid_hidden_from_rows(_tt_rows)
            st.caption(
                "並び順はタイムテーブルの「アー写グリッド表示順」列で決まります"
                "(番号の昇順で左上から詰めます。空欄の人は末尾)。ここは確認用の表示です。"
            )
            if tt_grid_hidden:
                st.caption(
                    "アー写グリッド非表示: %s" % " / ".join(tt_grid_hidden)
                )
            if not tt_order:
                st.info("タイムテーブルに表示対象のアーティストがいません。")
            else:
                # 行分割は logic_grid.generate_grid_image と同じ規則にする
                # (row_counts を順に消費し、余りは 5 枚ずつの「予備」行)。
                preview_rows = []
                curr = 0
                for r_idx, count in enumerate(parsed_counts):
                    cap = count if count > 0 else 1
                    items = tt_order[curr:curr + cap]
                    curr += len(items)
                    preview_rows.append({
                        "行": f"行{r_idx + 1}",
                        "枚数": f"{len(items)}/{cap}",
                        "並び (左 → 右)": " / ".join(items),
                    })
                    if curr >= len(tt_order):
                        break
                while curr < len(tt_order):
                    items = tt_order[curr:curr + 5]
                    curr += len(items)
                    preview_rows.append({
                        "行": "予備",
                        "枚数": f"{len(items)}/5",
                        "並び (左 → 右)": " / ".join(items),
                    })
                st.dataframe(pd.DataFrame(preview_rows), width='stretch', hide_index=True)

            st.divider()

            # --- 画像生成・プレビューエリア ---
            sorted_fonts = font_service.list_sorted_fonts()
            font_file_list = [item["filename"] for item in sorted_fonts]
            font_display_map = {item["filename"]: item["name"] for item in sorted_fonts}
            
            if not font_file_list:
                font_file_list = ["keifont.ttf"]
                font_display_map = {"keifont.ttf": "標準フォント (未設定)"}

            # フォント選択状態の確保
            if st.session_state.grid_font not in font_file_list:
                st.session_state.grid_font = font_file_list[0]

            # 見本表示
            with st.expander("🔤 フォント一覧見本を表示"):
                with st.container(height=300):
                    specimen_list = sorted(sorted_fonts, key=lambda x: x["filename"].lower())
                    specimen_img = font_service.build_specimen(specimen_list)
                    if specimen_img:
                        st.image(specimen_img, width='stretch')
                    else:
                        st.info("フォントが見つかりません。")

            # フォント選択
            st.selectbox(
                "プレビュー用フォント", 
                font_file_list,
                format_func=lambda x: font_display_map.get(x, x),
                key="grid_font" 
            )
            
            # 現在の設定パラメータ
            current_params = {
                # 段階②: TT の番号を変えたら「設定が変更されています」が出るよう、
                # session の grid_order ではなく TT 由来の順序で比較する。
                "order": tt_order,
                "row_counts": st.session_state.grid_row_counts_str,
                "layout_mode": st.session_state.grid_layout_mode,
                "alignment": st.session_state.grid_alignment,
                "font": st.session_state.grid_font,
                "rows": st.session_state.grid_rows
            }

            # 生成/保存ボタンはここには無い。保存はワークスペース唯一の
            # 「💾 プロジェクトを保存する」に集約され、プレビューはその保存
            # ハンドラが保存後の状態から作り直す。レンダー毎の自動生成は禁止
            # (罠16 / Phase 3 stop-autogen)。
            _grid_img = st.session_state.get("last_generated_grid_image")
            if not _grid_img:
                st.info("プロジェクトを保存するとプレビューが表示されます。")
            elif st.session_state.get("grid_last_generated_params") != current_params:
                st.caption("👇 直近に保存したときのプレビュー")
                st.warning("変更を保存するとプレビューが更新されます。")
                st.image(_grid_img, width='stretch')
            else:
                st.caption("👇 現在のプレビュー")
                st.image(_grid_img, width='stretch')

    except Exception as main_e:
        st.error(f"予期せぬエラー: {main_e}")

# ★重要: 他のファイルからimportされる関数を定義
def generate_grid_image_buffer(artists, cols, rows, font_path, alignment, layout_mode, row_counts_str):
    """
    外部呼び出し用: アーティストリストと設定を受け取り、画像のBytesIOを返す
    """
    if not generate_grid_image: return None
    try:
        try:
            parsed_counts = [int(x.strip()) for x in row_counts_str.split(",") if x.strip()]
        except Exception:
            parsed_counts = [5] * rows

        is_brick = (layout_mode == "レンガ (サイズ統一)")
        align_map = {"左揃え": "left", "中央揃え": "center", "右揃え": "right"}
        align_val = align_map.get(alignment, "center")

        img = generate_grid_image(
            artists, IMAGE_DIR, 
            font_path=font_path, 
            row_counts=parsed_counts, is_brick_mode=is_brick, alignment=align_val
        )
        if img:
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            buf.seek(0)
            return img # BytesIOではなくImageオブジェクトを返す仕様に変更（flyer側でsaveするため）
    except Exception as e:
        print(f"Background generation error: {e}")
    return None
