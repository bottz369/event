"""Explicit recipe save/load callbacks, separate from existing manual editing."""
from copy import deepcopy
import streamlit as st
from services import session_manager,template_service,production_templates as recipes


def _capture():
    from views.flyer import gather_flyer_settings_from_session
    session_manager.sync_session_to_draft()
    project=deepcopy(session_manager.get_draft_project())
    if project is None:raise ValueError('プロジェクトを選択してください。')
    project.flyer_settings=gather_flyer_settings_from_session()
    for key in ('grid_font','tt_font','tt_columns','tt_style'):
        if key in st.session_state:project.settings[key]=deepcopy(st.session_state[key])
    for key in ('rows','row_counts_str','layout_mode','alignment'):
        if 'grid_'+key in st.session_state:project.grid_settings[key]=st.session_state['grid_'+key]
    return recipes.capture(project,{v:st.session_state.get('last_generated_'+v+'_image') for v in ('grid','tt')})


def _save():
    try:
        recipes.save(st.session_state.get('recipe_name',''),_capture(),st.session_state.get('recipe_default',False))
        st.toast('制作テンプレートを保存しました。',icon='✅')
    except Exception as exc:
        st.error(str(exc) if isinstance(exc,ValueError) else 'テンプレートの保存に失敗しました。')


def _load():
    selected=st.session_state.get('recipe_load')
    item=next((t for t in template_service.list_templates() if t.id==selected),None)
    if item is None:return
    _apply_data(item.data_json)

def _apply_data(data):
    try:
        project=recipes.apply(session_manager.get_draft_project(),session_manager.get_draft_rows(),data)
        session_manager.set_draft_project(project)
        for key,value in project.flyer_settings.items():st.session_state['flyer_'+key]=value
        for key in ('grid_font','tt_font','tt_columns','tt_style'):
            if key in project.settings:st.session_state[key]=deepcopy(project.settings[key])
        for key in ('rows','row_counts_str','layout_mode','alignment'):st.session_state['grid_'+key]=project.grid_settings[key]
        st.toast('制作テンプレートを編集中の設定に読み込みました。保存で反映されます。',icon='✨')
    except ValueError as exc:st.error(str(exc))


def render():
    with st.expander('🎨 制作テンプレート（AIおまかせ・手動編集共通）'):
        st.caption('現在の書体・配色・配置、グリッド方式、行分け、タイムテーブルの列幅・文字サイズを保存します。イベント名や出演者は保存しません。AI制作時は組数に合わせて収まりを自動調整します。')
        st.text_input('制作テンプレート名',key='recipe_name',placeholder='例：通常公演・青紫')
        st.checkbox('AI制作で最初に選ぶ標準テンプレートにする',key='recipe_default')
        st.button('現在の設定を制作テンプレートとして保存',key='btn_recipe_save',on_click=_save)
        templates=template_service.list_templates()
        choices=[]
        for item in templates:
            try:
                if recipes.decode(item.data_json)[recipes.META].get('grid'):choices.append(item)
            except ValueError:continue
        if choices:
            labels={t.id:t.name for t in choices}
            st.selectbox('手動編集に読み込む制作テンプレート',list(labels),format_func=labels.get,key='recipe_load')
            st.button('現在の編集に読み込む',key='btn_recipe_load',on_click=_load)
