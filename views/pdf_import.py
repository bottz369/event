"""Preview PDF imports before replacing the optional multipart draft. No DB writes."""
import hashlib

import pandas as pd
import streamlit as st

from models.event_format import schedule
from services import session_manager


def apply_preview(result, indices=None):
    from views import event_format
    config = event_format.config()
    from services.timetable_pdf_service import select_parts, normal_rows_from_part
    from models.event_format import new_part
    parts = select_parts(result, range(len(result["parts"])) if indices is None else indices)
    if len(parts) == 1:
        part = parts[0]
        draft = session_manager.get_draft_project()
        draft.open_time = part["open_time"]
        draft.start_time = part["start_time"]
        draft.goods_start_offset = int(part.get("goods_offset") or 0)
        session_manager.set_draft_project(draft)
        session_manager.set_draft_rows(normal_rows_from_part(part))
        st.session_state.tt_open_time = draft.open_time
        st.session_state.tt_start_time = draft.start_time
        st.session_state.tt_goods_offset = draft.goods_start_offset
        from views.timetable import _bump_editor_seq
        _bump_editor_seq()
        st.session_state.request_calc = False
        st.session_state.tt_unsaved_changes = True
        config.update(enabled=False, initialized=False, count=2,
                      parts=[new_part(0), new_part(1)])
    else:
        config.update(enabled=True, initialized=True, count=len(parts), parts=parts)
    event_format._put(config)
    pid = session_manager.get_active_project_id()
    # Callback runs before widgets are recreated; imported times replace old widget values.
    for key in list(st.session_state):
        if key.startswith((f"eventfmt_{pid}_", f"eventfmt_rows_{pid}_", f"eventfmt_revision_{pid}_", f"eventfmt_grid_{pid}_")) or key == f"eventfmt_selected_{pid}":
            st.session_state.pop(key, None)
    st.session_state.pop("event_format_preview", None)
    for key in ("last_generated_grid_image", "last_generated_tt_image", "flyer_result_grid", "flyer_result_tt"):
        st.session_state.pop(key, None)
    st.toast("PDFの構成を下書きに反映しました。確認後、上の保存ボタンで保存してください。")


def render():
    from services import artist_service
    from services.timetable_pdf_service import read_pdf, match_artists
    pid = session_manager.get_active_project_id()
    result_key = f"eventfmt_pdf_result_{pid}"
    with st.expander("📄 PDFからタイムテーブルを読み込む"):
        st.caption("Excelから出力した今回の形式（2〜6部・文字を選択できるPDF）に対応。控室・人数・仕込み情報は取り込みません。")
        upload = st.file_uploader("タイムテーブルPDF（10MB以下・10ページ以内）", type=["pdf"],
                                  key=f"eventfmt_pdf_upload_{pid}")
        if upload is None:
            return
        data = upload.getvalue()
        digest = hashlib.sha256(data).hexdigest()
        if st.button("PDFを読み取り、内容を確認する", key=f"btn_pdf_parse_{pid}"):
            st.session_state.pop(result_key, None)
            try:
                with st.spinner("PDFを読み取り中..."):
                    result = read_pdf(data)
                    result = match_artists(result, [a.name for a in artist_service.list_artists()])
                st.session_state[result_key] = dict(digest=digest, result=result)
            except ValueError as exc:
                st.error(str(exc))
        cached = st.session_state.get(result_key) or {}
        if cached.get("digest") != digest:
            return
        result = cached["result"]
        st.caption("読み込む部にチェックを入れてください。1部だけなら通常イベント、2部以上なら複数部イベントとして反映します。")
        selected = []
        for index, part in enumerate(result["parts"]):
            if st.checkbox(f"{part['name']}を読み込む", value=True,
                           key=f"eventfmt_pdf_select_{pid}_{digest}_{index}"):
                selected.append(index)
            st.markdown(f"**{part['name']}：OPEN {part['open_time']} / START {part['start_time']}**")
            rows, _ = schedule(part)
            st.dataframe(pd.DataFrame([dict(アーティスト=r["ARTIST"], 開始=r["start"], 終了=r["end"],
                転換分=r["ADJUSTMENT"], 物販=r["goods"], 場所=r["PLACE"], 終演後=r["IS_POST_GOODS"]) for r in rows]),
                hide_index=True, height="content")
            if part.get("post_duration"):
                st.caption(f"終演後特典会：{part['post_start']}から{part['post_duration']}分")
            if part.get("note"):
                st.text(part["note"])
        for warning in result["warnings"]:
            st.warning(warning)
        if result["unmatched"]:
            st.warning("登録名と一致しない出演者：" + "、".join(result["unmatched"]) +
                       "。名前はそのまま取り込みます。アー写は登録・名前の修正後に反映できます。")
        if len(selected) == 1:
            st.info("選択した1部を通常イベントとして取り込みます。現在の通常タイムテーブルを置き換えます。")
        elif selected:
            st.info(f"選択した{len(selected)}部を複数部イベントとして取り込みます。現在の複数部構成を置き換え、通常タイムテーブルは保持します。")
        else:
            st.warning("読み込む部を1つ以上選択してください。")
        st.caption("料金・画像設定は保持します。DBへの保存は上の「プロジェクトを保存する」で行います。")
        st.button("確認した内容をタイムテーブルに反映する", key=f"btn_pdf_apply_{pid}",
                  on_click=apply_preview, args=(result, selected), disabled=not selected)
