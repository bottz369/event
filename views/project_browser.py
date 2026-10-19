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


PAGE_SIZE = 10


def _change_page(delta):
    st.session_state['browser_page'] = max(1, st.session_state.get('browser_page', 1) + delta)


def _request_delete(project):
    st.session_state['browser_delete_target'] = {k:project[k] for k in ('id','title','subtitle','event_date')}
    st.session_state['browser_delete_confirmed'] = False


def _cancel_delete():
    st.session_state.pop('browser_delete_target', None)
    st.session_state['browser_delete_confirmed'] = False


def _delete_confirmed(project_id):
    target = st.session_state.get('browser_delete_target')
    if not target or target['id'] != project_id or not st.session_state.get('browser_delete_confirmed'):
        return
    try:
        if not project_service.delete_project_by_id(project_id):
            st.error('プロジェクトが見つかりません。一覧を更新してください。')
            return
    except Exception:
        st.error('削除できませんでした。一覧を更新して状態を確認してください。')
        return
    if session_manager.get_active_project_id() is None:
        st.session_state['ws_project_selector_label'] = '(選択してください)'
    if st.session_state.get('browser_pending_id') == project_id:
        st.session_state.pop('browser_pending_id', None)
    ready = st.session_state.get('browser_pdf')
    if ready and ready[0] == project_id:
        st.session_state.pop('browser_pdf', None)
    _cancel_delete()
    refresh()
    st.toast(f'プロジェクト #{project_id} を削除しました。')


def _delete_confirmation():
    target = st.session_state.get('browser_delete_target')
    if not target:
        return
    name = target['title'] + (' - ' + target['subtitle'] if target['subtitle'] else '')
    with st.container(border=True):
        st.warning(f"#{target['id']} · {target['event_date']} · {name} を削除します。タイムテーブルも削除され、元に戻せません。")
        confirmed = st.checkbox('このプロジェクトを削除することを確認しました', key='browser_delete_confirmed')
        yes, no = st.columns(2)
        yes.button('削除を確定する', key='btn_browser_delete_confirm', type='primary', disabled=not confirmed,
                   on_click=_delete_confirmed, args=(target['id'],))
        no.button('キャンセル', key='btn_browser_delete_cancel', on_click=_cancel_delete)


def render():
    pending = st.session_state.get('browser_pending_id')
    if pending is not None:
        st.warning('現在のプロジェクトに未保存の変更があります。保存してから開くか、変更を破棄して切り替えてください。')
        a, b = st.columns(2)
        a.button('変更を破棄して開く', key='btn_browser_discard', on_click=_open, args=(pending,))
        b.button('切り替えをやめる', key='btn_browser_cancel', on_click=lambda:st.session_state.pop('browser_pending_id', None))
    with st.expander('🗂️ プロジェクト一覧・検索', expanded=session_manager.get_active_project_id() is None):
        st.button('🔄 一覧を更新', key='btn_browser_refresh', on_click=refresh)
        query = st.text_input('公演名・日付・会場・IDで検索', key='browser_search',
                              on_change=lambda:st.session_state.update(browser_page=1)).strip().casefold()
        cards = project_service.list_project_cards()
        cards = [p for p in cards if query in ' '.join(str(p[k]) for k in ('id','title','subtitle','event_date','venue')).casefold()]
        st.caption(f'{len(cards)}件。画像は最後に生成・保存した状態です。LINE保存後に見つからない場合は「一覧を更新」を押してください。')
        _delete_confirmation()
        if not cards:
            st.info('該当するプロジェクトはありません。');return
        pages = max(1, math.ceil(len(cards) / PAGE_SIZE))
        page = min(pages, max(1, st.session_state.get('browser_page', 1)))
        st.session_state['browser_page'] = page
        for p in cards[(page-1)*PAGE_SIZE:page*PAGE_SIZE]:
            with st.container(border=True):
                grid_col, tt_col, info_col = st.columns([1, 1, 5])
                for col, kind, label in ((grid_col, 'grid', 'グリッド'), (tt_col, 'tt', 'タイムテーブル')):
                    with col:
                        st.caption(label)
                        image = p['images'].get(kind)
                        if image: st.image(image, width=100)
                        else: st.caption('プレビュー未保存')
                with info_col:
                    st.caption(f"{p['event_date']} · #{p['id']}")
                    st.write(p['title'] + (' - ' + p['subtitle'] if p['subtitle'] else ''))
                    st.caption(p['venue'])
                    open_col, grid_dl, tt_dl, delete_col = st.columns([1, 1.4, 1.7, 2.1])
                    open_col.button('開く', key=f"btn_browser_open_{p['id']}", on_click=open_project, args=(p['id'],), width='stretch')
                    for col, kind, label in ((grid_dl, 'grid', 'グリッド PNG'), (tt_dl, 'tt', 'タイムテーブル PNG')):
                        url = p.get('downloads', {}).get(kind)
                        if url: col.link_button(label, url, width='stretch')
                    delete_col.button('プロジェクトを削除', key=f"btn_browser_delete_{p['id']}",
                                      on_click=_request_delete, args=(p,), width='stretch')
        previous, position, following = st.columns([1, 1, 1])
        previous.button('前のページ', key='btn_browser_prev', disabled=page<=1, on_click=_change_page, args=(-1,), width='stretch')
        position.caption(f'{page} / {pages} ページ · 1ページ{PAGE_SIZE}件')
        following.button('次のページ', key='btn_browser_next', disabled=page>=pages, on_click=_change_page, args=(1,), width='stretch')


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
