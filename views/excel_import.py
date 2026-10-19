"""Excel preview and explicit draft-only apply in the workspace timetable tab."""
from collections import Counter
from copy import deepcopy
import hashlib

import pandas as pd
import streamlit as st

from models.event_format import schedule
from services import session_manager


def prepare_apply(result, draft, old_rows):
    """Preserve display settings for unique existing names; use Excel timing verbatim."""
    from services.timetable_excel_service import _minute
    result = deepcopy(result)
    part = result['parts'][0]
    if draft.open_time and _minute(draft.open_time, '現在のOPEN') > _minute(part['start_time'], 'START'):
        raise ValueError('現在のOPENがエクセルのSTARTより後です。イベント概要でOPENを修正してください。')
    part['open_time'] = draft.open_time or ''
    part['goods_offset'] = draft.goods_start_offset
    counts = Counter(row.artist_name for row in old_rows if not row.is_special_row)
    previous = {row.artist_name: row for row in old_rows if not row.is_special_row and counts[row.artist_name] == 1}
    ordered_rows = sorted((row for row in old_rows if not row.is_special_row),
                          key=lambda row: row.grid_no if row.grid_no is not None else float('inf'))
    order = list(dict.fromkeys(row.artist_name for row in ordered_rows)) or draft.grid_settings.get('order', [])
    positions = {name: i+1 for i, name in enumerate(order)}
    next_position = len(positions)+1
    for raw in part['rows']:
        old = previous.get(raw['ARTIST'])
        if old is not None:
            raw.update(COMINGSOON=old.is_comingsoon, IS_HIDDEN=old.is_hidden, GRID_HIDDEN=old.is_grid_hidden)
        if raw['ARTIST'] not in positions:
            positions[raw['ARTIST']] = next_position
            next_position += 1
        raw['GRID_NO'] = positions[raw['ARTIST']]
    return result


def apply_preview(result):
    from views import pdf_import
    try:
        prepared = prepare_apply(result, session_manager.get_draft_project(), session_manager.get_draft_rows())
    except ValueError as exc:
        st.error(str(exc))
        return
    pdf_import.apply_preview(prepared, [0], source='エクセル')


def render():
    from services import timetable_excel_service as service, artist_service
    from services.timetable_pdf_service import match_artists
    pid = session_manager.get_active_project_id()
    key = f'excel_import_{pid}'
    with st.expander('📊 エクセルからタイムテーブルを読み込む'):
        st.caption('START・END・グループ名の列がある.xlsxに対応。シートを選んで確認後に反映します。AI解析の料金はかかりません。')
        upload = st.file_uploader('タイムテーブルのエクセル（.xlsx・10MB以下）', type=['xlsx'], key=key+'_upload')
        if upload is None:
            return
        data = upload.getvalue()
        digest = hashlib.sha256(data).hexdigest()
        meta = st.session_state.get(key+'_sheets') or {}
        if meta.get('digest') != digest:
            try:
                names = service.sheet_names(data)
            except ValueError as exc:
                st.error(str(exc))
                return
            meta = dict(digest=digest, names=names)
            st.session_state[key+'_sheets'] = meta
        sheet = st.selectbox('読み込むシート', meta['names'], key=key+'_sheet_'+digest)
        if st.button('エクセルを読み取り、内容を確認する', key=key+'_parse'):
            st.session_state.pop(key+'_result', None)
            try:
                result = service.read_excel(data, sheet)
                result = match_artists(result, [a.name for a in artist_service.list_artists()])
                st.session_state[key+'_result'] = dict(digest=digest, sheet=sheet, result=result)
            except ValueError as exc:
                st.error(str(exc))
        cached = st.session_state.get(key+'_result') or {}
        if cached.get('digest') != digest or cached.get('sheet') != sheet:
            return
        result = cached['result']
        part = result['parts'][0]
        rows, _ = schedule(part)
        st.markdown(f"**{len(rows)}組：START {part['start_time']} ／ 終演 {rows[-1]['end']}**")
        st.caption(f"OPENは現在の設定（{session_manager.get_draft_project().open_time or '未設定'}）を保持します。公演日・料金・背景・ロゴは変更しません。")
        st.dataframe(pd.DataFrame([dict(アーティスト=row['ARTIST'], 開始=row['start'], 終了=row['end'],
            転換分=row['ADJUSTMENT'], 物販=row['goods'], 場所=row['PLACE']) for row in rows]),
            hide_index=True, height='content')
        for warning in result['warnings']:
            st.warning(warning)
        if result['unmatched']:
            st.warning('登録名と一致しない出演者：'+'、'.join(result['unmatched'])+'。名前はそのまま取り込みます。アー写は登録・名前の修正後に反映できます。')
        blocked = False
        try:
            prepare_apply(result, session_manager.get_draft_project(), session_manager.get_draft_rows())
        except ValueError as exc:
            st.error(str(exc)); blocked = True
        st.info('選択シートを通常イベントとして取り込み、現在の通常タイムテーブルを置き換えます。複数部イベントの場合は通常イベントに切り替わります。')
        st.caption('同名の既存出演者のcomingsoon・非表示・アー写順は引き継ぎます。反映後、上の「プロジェクトを保存する」で保存してください。')
        st.button('確認したエクセルをタイムテーブルに反映する', key=key+'_apply',
                  on_click=apply_preview, args=(result,), disabled=blocked)
