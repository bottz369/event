"""Shared normal/multipart controls, saved through the unified project save."""
import streamlit as st
from models.timetable_style import DEFAULTS, LIMITS, normalize_style
from services import session_manager


def _change(field):
    style = normalize_style(st.session_state.get('tt_style'))
    style[field] = st.session_state['tt_style_' + field]
    st.session_state.tt_style = style


def _reset():
    st.session_state.tt_style = dict(DEFAULTS)
    for field, value in DEFAULTS.items():
        st.session_state['tt_style_' + field] = value


def render():
    draft = session_manager.get_draft_project()
    style = normalize_style(st.session_state.get('tt_style', (draft.settings if draft else {}).get('tt_style')))
    st.session_state.setdefault('tt_style', style)
    def slider(label, field):
        key = 'tt_style_' + field
        st.session_state.setdefault(key, style[field])
        st.slider(label, *LIMITS[field], step=1, key=key, on_change=_change, args=(field,))
    with st.expander('📏 タイムテーブルの列幅・文字サイズ'):
        slider('列全体の幅（基準比 %）', 'column_width')
        slider('2列の間隔（px）', 'column_gap')
        st.session_state.setdefault('tt_style_custom_widths', style['custom_widths'])
        st.checkbox('出演時間欄・物販欄の幅を個別に調整する', key='tt_style_custom_widths',
                    on_change=_change, args=('custom_widths',))
        if st.session_state.tt_style_custom_widths:
            slider('出演時間欄の幅（%）', 'time_width')
            slider('物販欄の幅（%）', 'goods_width')
            st.caption('残りがアーティスト名の幅になります。')
        slider('アーティスト名の文字サイズ（%）', 'artist_font')
        slider('出演時間の文字サイズ（%）', 'time_font')
        slider('物販時間・場所の文字サイズ（%）', 'goods_font')
        st.caption('100%が従来のサイズです。長い文字は欄内に収まるよう自動縮小します。保存すると画像を更新します。複数部では全ての部に適用します。')
        st.button('列幅・文字サイズを初期値に戻す', key='btn_tt_style_reset', on_click=_reset)
