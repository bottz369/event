"""Flyer-integrated studio. Never generate/save on render or slider movement."""
import os

import streamlit as st

from services import asset_service, session_manager
from services import image_studio as studio


def _settings():
    try:
        cfg = st.secrets.get('openai', {})
    except (FileNotFoundError, KeyError):
        cfg = {}
    return (os.environ.get('OPENAI_API_KEY') or cfg.get('api_key', ''),
            os.environ.get('AI_STUDIO_ACCESS_CODE') or cfg.get('access_code', ''))


def _save(result_key, name_key, target):
    result = st.session_state.get(result_key)
    if not result or result.get('saved_id'):
        return
    try:
        asset = asset_service.upload_image_asset(result['data'], 'studio.png', target,
                                                 st.session_state.get(name_key) or '作成した素材')
    except ValueError as exc:
        st.error(str(exc))
        return
    st.session_state['flyer_bg_id' if target == 'background' else 'flyer_logo_id'] = asset.id
    result['saved_id'] = asset.id
    st.session_state[result_key] = result
    st.toast('アセットに保存して選択しました。プロジェクトを保存すると画像を更新します。', icon='✅')


def _preview(result_key, prefix, target):
    result = st.session_state.get(result_key)
    if not result:
        return
    st.image(result['data'], width='stretch')
    st.caption('直近に作成したプレビュー：' + result['caption'])
    st.caption('設定を変更した場合は、プレビューを作り直してから保存してください。')
    st.download_button('PNGをダウンロード', result['data'], file_name='studio-'+target+'.png',
                       mime='image/png', key=prefix+'_download')
    st.text_input('保存する素材名', key=prefix+'_name')
    st.button('アセットに保存して選択', key=prefix+'_save', on_click=_save,
              args=(result_key, prefix+'_name', target), disabled=bool(result.get('saved_id')))
    if result.get('saved_id'):
        st.success('保存済みです。元の素材は変更していません。')


def render():
    pid = session_manager.get_active_project_id()
    prefix = f'image_studio_{pid}'
    with st.expander('✨ AI背景作成・素材の色調整'):
        st.caption('作成した素材を確認してから、アセットに保存できます。元画像は上書きしません。')
        tab_bg, tab_color = st.tabs(['背景をAIで作る', '素材の色を変える'])
        with tab_bg:
            api_key, access_code = _settings()
            ready = bool(api_key and access_code)
            if not ready:
                st.info('背景のAI生成は接続設定後に利用できます。色調整は今すぐ使えます。')
            st.caption('生成ボタン1回につき1枚を作成します（API利用料が発生します）。入力した指示と参考画像をOpenAIへ送信します。')
            description = st.text_area('作りたい背景のイメージ', key=prefix+'_description', max_chars=2000,
                placeholder='例：お祭り風。提灯と花火は周囲に、中央は文字が読みやすい暗めの背景。')
            palette = st.selectbox('背景の色合い', ['青・紺・金', '赤・朱色・金', '黒・金', 'ピンク・紫', '指示に合わせる'], key=prefix+'_palette')
            reference = st.file_uploader('構図を合わせる参考背景（任意）',type=['png','jpg','jpeg','webp'],key=prefix+'_reference')
            code = st.text_input('画像生成の利用コード',type='password',key=prefix+'_access',disabled=not ready)
            if st.button('背景を1枚生成する',key=prefix+'_generate',disabled=not ready or not description.strip()):
                try:
                    with st.spinner('背景を生成しています。数分かかることがあります…'):
                        data = studio.generate_background(description,palette,api_key,access_code,code,
                                                          reference.getvalue() if reference else None)
                    st.session_state[prefix+'_bg_result'] = dict(data=data,caption='AI生成した背景。文字やロゴはフライヤー側で重ねます。')
                except ValueError as exc:
                    st.error(str(exc))
            _preview(prefix+'_bg_result',prefix+'_bg','background')
        with tab_color:
            st.caption('画像を描き直さずに色を変えます。縦横のピクセル数・輪郭・透過を維持します。AIの利用料はかかりません。')
            target_label = st.radio('保存先の種類',['ロゴ','背景'],horizontal=True,key=prefix+'_target')
            target = 'logo' if target_label=='ロゴ' else 'background'
            source_mode = st.radio('元画像の選び方',['画像をアップロード','現在選択中の素材'],horizontal=True,key=prefix+'_source_mode')
            source = st.file_uploader('色を変える元画像',type=['png','jpg','jpeg','webp'],key=prefix+'_source') if source_mode=='画像をアップロード' else None
            current_id = st.session_state.get('flyer_logo_id' if target=='logo' else 'flyer_bg_id')
            if source_mode=='現在選択中の素材':
                st.caption('基本設定で選択している' + target_label + 'を使用します。')
            preset = st.selectbox('仕上がりの色',list(studio.PALETTES)+['好きな色'],key=prefix+'_preset')
            color = st.color_picker('好きな色を指定', '#e4a637', key=prefix+'_color') if preset=='好きな色' else studio.PALETTES[preset]
            strength = st.slider('色の置き換え量（%）',0,100,100,key=prefix+'_strength')
            brightness = st.slider('明るさ（%）',50,150,100,key=prefix+'_brightness')
            if st.button('色調整のプレビューを作る',key=prefix+'_recolor',disabled=(source is None if source_mode=='画像をアップロード' else not current_id)):
                try:
                    with st.spinner('色を調整しています…'):
                        original = source.getvalue() if source_mode=='画像をアップロード' else asset_service.read_image_asset(current_id)
                        data = studio.recolor(original,color,strength,brightness)
                        size = studio.open_image(data).size
                    st.session_state[prefix+'_color_result'] = dict(data=data,target=target,
                        caption=f'{size[0]}×{size[1]}px／元画像と同じサイズ・透過を維持')
                except ValueError as exc:
                    st.error(str(exc))
            result=st.session_state.get(prefix+'_color_result')
            if result:
                _preview(prefix+'_color_result',prefix+'_color_preview',result['target'])
