"""Image studio: no external paid requests, no storage/DB writes in tests."""
import base64
import io
from unittest.mock import Mock

import numpy as np
from PIL import Image
import pytest


def picture(size=(24,16)):
    image=Image.new('RGBA',size)
    image.putdata([(i%256,(i*3)%256,(i*7)%256,(i*11)%256) for i in range(size[0]*size[1])])
    out=io.BytesIO();image.save(out,format='PNG');return out.getvalue()


@pytest.mark.parametrize('color',['#e4a637','#2686dc','#d23428'])
def test_recolor_preserves_every_alpha_pixel_dimensions_and_source(color):
    from services import image_studio as service
    original=picture()
    result=service.recolor(original,color)
    a=np.array(Image.open(io.BytesIO(original)))
    b=np.array(Image.open(io.BytesIO(result)))
    assert a.shape==b.shape
    assert np.array_equal(a[:,:,3],b[:,:,3])
    assert not np.array_equal(a[:,:,:3],b[:,:,:3])
    assert picture()==original
    assert np.array_equal(a,np.array(Image.open(io.BytesIO(service.recolor(original,color,0)))))


@pytest.mark.parametrize('data',[b'',b'invalid'])
def test_invalid_input_is_reported(data):
    from services import image_studio as service
    with pytest.raises(ValueError):service.recolor(data,'#e4a637')


def test_pixel_limit_prevents_large_processing(monkeypatch):
    from services import image_studio as service
    monkeypatch.setattr(service,'MAX_PIXELS',10)
    with pytest.raises(ValueError,match='800万画素'):service.open_image(picture())


@pytest.mark.parametrize('key,code,supplied',[('', 'a','a'),('key','','a'),('key','secret','wrong')])
def test_unconfigured_or_unauthorized_generation_never_calls_api(monkeypatch,key,code,supplied):
    from services import image_studio as service
    post=Mock();monkeypatch.setattr(service.requests,'post',post)
    with pytest.raises(ValueError):service.generate_background('お祭り','青',key,code,supplied)
    post.assert_not_called()


@pytest.mark.parametrize('reference',[None,picture()])
def test_generate_one_background_calls_expected_endpoint_without_retries(monkeypatch,reference):
    from services import image_studio as service
    result=picture()
    response=Mock(status_code=200)
    response.json.return_value={'data':[{'b64_json':base64.b64encode(result).decode()}]}
    post=Mock(return_value=response);monkeypatch.setattr(service.requests,'post',post)
    data=service.generate_background('お祭り','赤','key','code','code',reference)
    assert service.open_image(data).size==(24,16)
    post.assert_called_once()
    url=post.call_args.args[0];kw=post.call_args.kwargs
    assert url.endswith('/edits' if reference else '/generations')
    payload=kw['data'] if reference else kw['json']
    assert payload['n']==1 and payload['model']=='gpt-image-2'
    assert payload['size']=='1024x1280' and payload['quality']=='medium'
    assert 'NO lettering' in payload['prompt']
    assert kw['allow_redirects'] is False


@pytest.mark.parametrize('status',[401,403,429,500])
def test_api_errors_are_sanitized_and_not_retried(monkeypatch,status):
    from services import image_studio as service
    post=Mock(return_value=Mock(status_code=status,text='PRIVATE API KEY'))
    monkeypatch.setattr(service.requests,'post',post)
    with pytest.raises(ValueError) as exc:service.generate_background('夜景','青','key','code','code')
    assert 'PRIVATE' not in str(exc.value)
    post.assert_called_once()


def test_timeout_is_not_retried(monkeypatch):
    from services import image_studio as service
    post=Mock(side_effect=service.requests.Timeout('SECRET'))
    monkeypatch.setattr(service.requests,'post',post)
    with pytest.raises(ValueError,match='自動再試行はしません'):service.generate_background('祭','青','key','code','code')
    post.assert_called_once()


def test_studio_ui_requires_explicit_preview_and_save(app_test,monkeypatch):
    from tests.conftest import select_tab
    from views.workspace import TAB_FLYER,TAB_TT
    from views import image_studio
    from services import asset_service
    from models.asset import AssetView
    monkeypatch.setattr(image_studio,'_settings',lambda:('',''))
    recolor=Mock(return_value=picture());monkeypatch.setattr(image_studio.studio,'recolor',recolor)
    read=Mock(return_value=picture());monkeypatch.setattr(asset_service,'read_image_asset',read)
    saved=AssetView(id=98765,name='金ロゴ',image_filename='new.png')
    upload=Mock(return_value=saved);monkeypatch.setattr(asset_service,'upload_image_asset',upload)
    original=asset_service.list_assets_by_type
    monkeypatch.setattr(asset_service,'list_assets_by_type',lambda kind:original(kind)+([saved] if upload.called and kind=='logo' else []))
    at=app_test.run()
    label=next(x for x in at.selectbox(key='ws_project_selector_label').options
               if x not in ('(選択してください)','➕ 新規プロジェクト作成'))
    at.selectbox(key='ws_project_selector_label').select(label).run()
    select_tab(at,TAB_FLYER)
    pid=at.session_state['ws_active_project_id'];prefix=f'image_studio_{pid}'
    assert at.button(key=prefix+'_generate').disabled
    assert not read.called and not recolor.called and not upload.called
    at.radio(key=prefix+'_source_mode').set_value('現在選択中の素材').run()
    # Select a logo locally when an old project has none.
    at.session_state['flyer_logo_id']=11
    at.run()
    at.button(key=prefix+'_recolor').click().run()
    assert not at.exception
    recolor.assert_called_once();read.assert_called_once();upload.assert_not_called()
    at.slider(key=prefix+'_strength').set_value(50).run()
    recolor.assert_called_once()
    at.text_input(key=prefix+'_color_preview_name').input('金ロゴ').run()
    at.button(key=prefix+'_color_preview_save').click().run()
    assert not at.exception
    upload.assert_called_once()
    assert at.session_state['flyer_logo_id']==98765
    assert at.button(key=prefix+'_color_preview_save').disabled
    select_tab(at,TAB_TT);select_tab(at,TAB_FLYER)
    assert not at.exception
    assert at.session_state['flyer_logo_id']==98765
    upload.assert_called_once()


def test_background_ui_generates_only_on_button_and_keeps_preview_on_error(app_test,monkeypatch):
    from tests.conftest import select_tab
    from views.workspace import TAB_FLYER
    from views import image_studio
    monkeypatch.setattr(image_studio,'_settings',lambda:('test-key','test-code'))
    generate=Mock(return_value=picture());monkeypatch.setattr(image_studio.studio,'generate_background',generate)
    at=app_test.run()
    label=next(x for x in at.selectbox(key='ws_project_selector_label').options
               if x not in ('(選択してください)','➕ 新規プロジェクト作成'))
    at.selectbox(key='ws_project_selector_label').select(label).run()
    select_tab(at,TAB_FLYER)
    prefix=f"image_studio_{at.session_state['ws_active_project_id']}"
    at.text_area(key=prefix+'_description').input('青い花火と提灯').run()
    at.text_input(key=prefix+'_access').input('test-code').run()
    generate.assert_not_called()
    at.button(key=prefix+'_generate').click().run()
    assert not at.exception
    generate.assert_called_once()
    result=at.session_state[prefix+'_bg_result']['data']
    at.selectbox(key=prefix+'_palette').select('赤・朱色・金').run()
    assert generate.call_count==1
    generate.side_effect=ValueError('一時的に利用できません')
    at.button(key=prefix+'_generate').click().run()
    assert not at.exception
    assert generate.call_count==2
    assert at.session_state[prefix+'_bg_result']['data']==result
