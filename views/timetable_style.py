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
    for key in list(st.session_state):
        if key.startswith('tt_style_photo_y_'):
            del st.session_state[key]


def _change_photo(name, key):
    style = normalize_style(st.session_state.get('tt_style'))
    positions = style.setdefault('photo_positions', {})
    value = round(1 - st.session_state[key] / 100, 2)
    if value == .5:
        positions.pop(name, None)
    else:
        positions[name] = value
    st.session_state.tt_style = normalize_style(style)


def render():
    draft = session_manager.get_draft_project()
    style = normalize_style(st.session_state.get('tt_style', (draft.settings if draft else {}).get('tt_style')))
    st.session_state.setdefault('tt_style', style)
    def slider(label, field):
        key = 'tt_style_' + field
        st.session_state.setdefault(key, style[field])
        st.slider(label, *LIMITS[field], step=1, key=key, on_change=_change, args=(field,))
    with st.expander('📏 タイムテーブルの列幅・文字サイズ・写真表示'):
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
        for label, field in [('写真を横幅いっぱいに表示する', 'photo_cover'),
                             ('物販の記載がない欄は空欄にする', 'blank_goods')]:
            st.session_state.setdefault('tt_style_' + field, style[field])
            st.checkbox(label, key='tt_style_' + field, on_change=_change, args=(field,))
        st.caption('横幅いっぱいの表示では、写真の上下がトリミングされます。')
        if style['photo_cover']:
            from models.event_format import options, active_parts, draft_rows
            rows = session_manager.get_draft_rows()
            config = options(draft.settings if draft else {})
            if config.get('enabled'):
                rows = [r for part in active_parts(config) for r in draft_rows(part)]
            names = list(dict.fromkeys(r.artist_name for r in rows if r.artist_name and not r.is_special_row))
            if names:
                name = st.selectbox('写真の表示位置を調整するアーティスト', names, key='tt_style_photo_artist')
                key = 'tt_style_photo_y_' + name
                st.session_state.setdefault(key, round((1 - style.get('photo_positions', {}).get(name, .5)) * 100))
                st.slider('写真を移動（0＝上へ／50＝中央／100＝下へ）', 0, 100,
                          key=key, on_change=_change_photo, args=(name, key))
                st.caption('この公演のタイムテーブル内の写真だけに適用します。アー写グリッドの配置は変わりません。')
        st.caption('100%が従来のサイズです。長い文字は欄内に収まるよう自動縮小します。保存すると画像を更新します。複数部では全ての部に適用します。')
        st.button('タイムテーブルの表示設定を初期値に戻す', key='btn_tt_style_reset', on_click=_reset)
