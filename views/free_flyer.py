"""Explicit saved-image project editor. No API calls or writes on page render."""
from copy import deepcopy
import hmac

import streamlit as st
from services import free_flyer as ff


@st.cache_data(ttl=3600, max_entries=64, show_spinner=False)
def _photo(path):return ff.get_image(path)


def render(project_id):
    st.subheader(f'🖼️ 画像から制作したプロジェクト #{project_id}')
    st.info(ff.NOTICE)
    key=f'ff_editor_{project_id}'
    if key not in st.session_state:
        document,baseline=ff.load(project_id)
        st.session_state[key]=dict(doc=document,baseline=baseline,version=0)
    working=st.session_state[key];doc=working['doc'];prefix=f"{key}_{working['version']}"
    if st.button('保存内容を読み直す（未保存の変更を破棄）',key=prefix+'_reload'):
        st.session_state.pop(key,None);st.rerun()
    from database import get_image_url
    left,right=st.columns(2)
    left.image(_photo(doc['original']),caption='変更しない原本',width=420)
    right.image(_photo(doc['current']),caption='現在の完成プレビュー（新しく生成した画像は保存前）',width=420)
    a,b=st.columns(2)
    a.link_button('原本 PNG',get_image_url(doc['original']))
    b.link_button('完成 PNG',get_image_url(doc['current']))
    title=st.text_input('プロジェクト名（画像内の文字は変わりません）',working.get('pending_title',doc['title']),max_chars=200,key=prefix+'_title')
    working['pending_title']=title
    changes={}
    inputs=working.setdefault('input_values',{})
    st.caption('以下は確定時に選んだAI再編集可能項目です。変更後に画像生成と保存が必要です。')
    for field in doc['fields']:
        if field['id'] in doc['selected']:
            value=st.text_area(field['label'],inputs.get(field['id'],field['value']),max_chars=1500,key=prefix+'_'+field['id'])
            inputs[field['id']]=value
            if value!=field['value']:changes[field['id']]=value
    if ff.fingerprint(doc)!=working['baseline'] or changes or title!=doc['title']:
        st.warning('未保存の編集があります。完成画像を確認して保存してください。')
    if not doc['selected']:st.caption('編集項目は選ばれていません。LINEで「デザイン調整に戻る」→確定・編集項目の見直しができます。')
    with st.expander('固定部分・変更履歴'):
        st.write(doc.get('fixed_note',''))
        for entry in reversed(doc['history']):
            st.write(entry['at']+' · '+entry['prompt'])
            st.link_button('この時点の画像を開く',get_image_url(entry['image']),key=prefix+'_'+entry['image']+'_'+entry['at'])
        if doc.get('archives'):st.caption('古い履歴は原本と共に分割保存されています。')
    from views.image_studio import _settings
    api_key,access_code=_settings()
    code=st.text_input('AI編集の利用コード',type='password',key=prefix+'_code')
    instruction=st.text_area('自然な言葉で変更内容を伝える',key=prefix+'_instruction',max_chars=4000,
        placeholder='12/5の会場を〇〇に変更して。他の日程はそのまま。')
    ready=bool(api_key and access_code and hmac.compare_digest(str(access_code).encode(),code.encode()))
    if st.button('変更案を読む（API料金）',disabled=not(ready and instruction),key=prefix+'_interpret'):
        try:
            with st.spinner('編集可能項目に対応する変更案を確認しています…'):
                proposal=ff.interpret_changes(doc,instruction,api_key)
            working['proposal']=proposal
        except ValueError as exc:st.error(str(exc))
    proposal=changes or working.get('proposal')
    if proposal:
        try:
            replacements=ff.replacements(doc,proposal)
            for item in replacements:st.write(f"{item['label']}：{item['before']} → {item['after']}")
        except ValueError as exc:
            st.error(str(exc));replacements=[]
        if st.button('この変更で画像を生成（API料金）',disabled=not(ready and replacements),key=prefix+'_generate'):
            try:
                with st.spinner('画像を再編集しています…'):
                    result=ff.edit(_photo(doc['current']),_photo(doc['original']),
                        '以下の確定した項目のみを変更し、他の内容とデザインを維持してください。',api_key,
                        references=[_photo(a['path']) for a in doc['assets']],locked=replacements,
                        reference_names=[a['kind']+': '+a['name'] for a in doc['assets']])
                    # Retain paid output in memory even if upload fails; the recovery button does no API call.
                    working['result']=result;working['result_changes']=deepcopy(proposal)
                    _apply_result(working)
                st.rerun()
            except Exception as exc:st.error(str(exc) if isinstance(exc,ValueError) else '生成画像の保管に失敗しました。下の再保管ボタンを使ってください。')
    if working.get('result') and st.button('生成済み画像を再保管（API呼び出しなし）',key=prefix+'_recover'):
        try:_apply_result(working);st.rerun()
        except Exception:st.error('画像を保管できませんでした。新たに生成せず、再保管をお試しください。')
    if proposal:st.caption('入力した変更を画像に反映してから保存してください。')
    confirmed=st.checkbox('画像全体・変更内容・編集項目・日付・時刻・名前を確認しました（※必須）',key=prefix+'_confirmed')
    if st.button('この画像と編集内容を保存',disabled=not confirmed or bool(proposal),key=prefix+'_save',type='primary'):
        try:
            candidate=deepcopy(doc);candidate['title']=title;candidate['reviewed']=True
            ff.save(candidate,project_id,working['baseline'])
            working.update(doc=candidate,baseline=ff.fingerprint(candidate),version=working['version']+1)
            from views.project_browser import refresh
            from services import session_manager
            refresh();session_manager.reload_project(project_id)
            st.success('保存しました。LINEとアプリから同じ原本を使って再編集できます。')
            st.rerun()
        except Exception as exc:
            st.error(str(exc) if isinstance(exc,ValueError) else '保存を確認できませんでした。一覧で確認し、内容を読み直してください。')


def _apply_result(working):
    path=ff.put_image(working['result'])
    doc=ff.revision(working['doc'],path,'アプリの編集項目を変更',working['result_changes'])
    doc['reviewed']=True
    working.update(doc=doc,version=working['version']+1)
    working.pop('result');working.pop('result_changes');working.pop('proposal',None);working.pop('input_values',None)
