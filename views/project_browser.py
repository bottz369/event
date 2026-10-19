"""Unified, paginated project gallery. Viewing never regenerates or saves images."""
import math
import streamlit as st
from services import project_service, session_manager


def refresh():
    project_service.list_projects_for_selector.clear()
    project_service.list_project_cards.clear()


def open_project(project_id):
    if session_manager.has_unsaved_changes():
        st.session_state['browser_pending_id'] = project_id
        return
    _open(project_id)


def _open(project_id):
    if session_manager.reload_project(project_id):
        labels = dict(project_service.list_projects_for_selector())
        st.session_state['ws_project_selector_label'] = labels[project_id]
        st.session_state.pop('browser_pending_id', None)
    else:
        st.error('プロジェクトを開けませんでした。一覧を更新してください。')


def render():
    pending = st.session_state.get('browser_pending_id')
    if pending is not None:
        st.warning('現在のプロジェクトに未保存の変更があります。保存してから開くか、変更を破棄して切り替えてください。')
        a, b = st.columns(2)
        a.button('変更を破棄して開く', key='btn_browser_discard', on_click=_open, args=(pending,))
        b.button('切り替えをやめる', key='btn_browser_cancel', on_click=lambda:st.session_state.pop('browser_pending_id', None))
    with st.expander('🗂️ プロジェクト一覧・検索', expanded=session_manager.get_active_project_id() is None):
        st.button('🔄 一覧を更新', key='btn_browser_refresh', on_click=refresh)
        query = st.text_input('公演名・日付・会場・IDで検索', key='browser_search').strip().casefold()
        cards = project_service.list_project_cards()
        cards = [p for p in cards if query in ' '.join(str(p[k]) for k in ('id','title','subtitle','event_date','venue')).casefold()]
        st.caption(f'{len(cards)}件。画像は最後に生成・保存した状態です。LINE保存後に見つからない場合は「一覧を更新」を押してください。')
        if not cards:
            st.info('該当するプロジェクトはありません。');return
        page = st.number_input('ページ', min_value=1, max_value=max(1, math.ceil(len(cards)/6)), value=1, step=1)
        variant = st.radio('一覧のプレビュー', ['アー写グリッド','タイムテーブル'], horizontal=True, key='browser_variant')
        kind = 'grid' if variant=='アー写グリッド' else 'tt'
        for p in cards[(page-1)*6:page*6]:
            with st.container(border=True):
                image_col, info_col = st.columns([1, 3])
                with image_col:
                    image = p['images'].get(kind) or next(iter(p['images'].values()), None)
                    if image: st.image(image, width=160)
                    else: st.caption('プレビュー未保存')
                with info_col:
                    st.write(f"**{p['event_date']} · #{p['id']}**")
                    st.write(p['title'])
                    if p['subtitle']: st.write(p['subtitle'])
                    st.caption(p['venue'])
                    if not image: st.caption('フライヤーセットを生成・保存すると表示されます。')
                    st.button('このプロジェクトを開く', key=f"btn_browser_open_{p['id']}", on_click=open_project, args=(p['id'],))


def render_exports(project_id):
    with st.expander('📥 プロジェクトのPDF出力'):
        if st.button('PDFを用意する', key=f'btn_browser_pdf_{project_id}'):
            try:
                st.session_state['browser_pdf'] = (project_id, project_service.project_pdf_exports(project_id))
            except Exception:
                st.error('PDFを用意できませんでした。保存内容を確認してください。')
        ready = st.session_state.get('browser_pdf')
        if ready and ready[0] == project_id:
            for kind, data in ready[1].items():
                st.download_button('イベント概要PDF' if kind=='summary' else 'タイムテーブルPDF', data,
                                   f'{kind}_{project_id}.pdf', 'application/pdf', key=f'dl_browser_{kind}_{project_id}')
