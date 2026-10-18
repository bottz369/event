"""Explicit palette preview and new-asset save beside the flyer logo selector."""
import streamlit as st

from services import asset_service,session_manager
from services import logo_palette as palette
from views.image_studio import _settings


def _save(key,name_key):
    result=st.session_state.get(key)
    if not result or result.get('saved_id'):return
    if result['sources']!=(st.session_state.get('flyer_logo_id'),st.session_state.get('flyer_bg_id')):
        st.error('背景またはロゴが変わりました。配色プレビューを作り直してください。');return
    try:
        asset=asset_service.upload_image_asset(result['data'],'matched-logo.png','logo',
            st.session_state.get(name_key) or '背景に合わせたロゴ')
    except ValueError as exc:
        st.error(str(exc));return
    result['saved_id']=asset.id
    st.session_state[key]=result
    st.session_state['flyer_logo_id']=asset.id
    st.toast('新しいロゴをアセットに保存して選択しました。',icon='✅')


def render():
    prefix=f'logo_palette_{session_manager.get_active_project_id()}'
    with st.expander('✨ AIでロゴの色を背景に合わせる'):
        st.caption('選択中の背景とロゴからAIが配色を提案します。形・画像サイズ・透過はそのまま、色だけを調整します。')
        logo_id=st.session_state.get('flyer_logo_id');bg_id=st.session_state.get('flyer_bg_id')
        api_key,access_code=_settings();ready=bool(api_key and access_code)
        if not ready:st.info('AI接続設定後に利用できます。画像生成と共通の設定です。')
        if not logo_id or not bg_id:st.info('背景画像とロゴ画像を両方選択してください。')
        st.caption('ボタンを押した時だけ、背景とロゴの縮小画像をOpenAIへ送信します（API利用料が発生）。元の素材は残ります。')
        code=st.text_input('ロゴ配色の利用コード',type='password',key=prefix+'_code',disabled=not ready)
        if st.button('背景に合うロゴの色を提案する',key=prefix+'_generate',disabled=not(ready and logo_id and bg_id)):
            try:
                # Check access before downloading assets, too.
                import hmac
                if not hmac.compare_digest(str(access_code).encode(),str(code).encode()):raise ValueError('利用コードを確認してください。')
                with st.spinner('背景に合わせてロゴの色を調整しています…'):
                    logo=asset_service.read_image_asset(logo_id);bg=asset_service.read_image_asset(bg_id)
                    result=palette.match_logo(logo,bg,api_key,access_code,code)
                    result.update(sources=(logo_id,bg_id),before=palette.preview(logo,bg),after=palette.preview(result['data'],bg))
                st.session_state[prefix+'_result']=result
            except ValueError as exc:st.error(str(exc))
        result=st.session_state.get(prefix+'_result')
        if not result:return
        expected=(result.get('saved_id') or result['sources'][0],result['sources'][1])
        if expected!=(logo_id,bg_id):
            st.warning('背景またはロゴが変わりました。配色プレビューを作り直してください。');return
        before,after=st.columns(2)
        with before:st.image(result['before'],caption='変更前（配色確認用）',width='stretch')
        with after:st.image(result['after'],caption='AI配色（配色確認用）',width='stretch')
        st.caption(result['reason']+' ／ '+result['color'])
        st.download_button('調整ロゴPNGをダウンロード',result['data'],file_name='matched-logo.png',mime='image/png',key=prefix+'_download')
        st.text_input('配色ロゴの素材名',key=prefix+'_name')
        st.button('配色ロゴをアセットに保存して選択',key=prefix+'_save',on_click=_save,
            args=(prefix+'_result',prefix+'_name'),disabled=bool(result.get('saved_id')))
        if result.get('saved_id'):st.success('保存済みです。プロジェクトを保存してフライヤーを再生成してください。')
