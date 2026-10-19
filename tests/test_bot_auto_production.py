"""No paid AI, LINE delivery, Storage or database writes in these tests."""
from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from bot import auto_production as ai,main

USER='Uowner'
CONFIG=main.BotConfig('secret','token',frozenset([USER]),frozenset())


def event(text=None,kind='text',data=None,uid=USER,source='user',**message):
    value=dict(type=kind,id=message.pop('id','m-'+str(event.n)),**message);event.n+=1
    if text is not None:value['text']=text
    result=dict(type='postback' if data else 'message',webhookEventId=str(event.n),replyToken='r'+str(event.n),
                source=dict(type=source,userId=uid),message=value)
    if data:result['postback']=dict(data=data)
    return result
event.n=0


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    ai.SESSIONS.clear();ai.SEEN.clear()
    monkeypatch.setattr(ai,'_spawn',lambda work:work())
    transport=SimpleNamespace(reply_text=Mock(),reply_messages=Mock(),
        upload_generated_png=Mock(return_value='https://example.com/a.png'),
        build_preview_png=Mock(return_value=b'preview'),build_image_message=main.build_image_message)
    monkeypatch.setattr(ai,'_transport',lambda:transport)
    push=Mock(return_value=True);monkeypatch.setattr(ai,'_push',push)
    monkeypatch.setattr(ai,'_credentials',lambda:('key','code','code'))
    yield transport,push
    ai.SESSIONS.clear();ai.SEEN.clear()


def press(s,action):return event(data=f'aip|{s.token}|{s.revision}|{action}')


def start():
    assert ai.handle(event(ai.START),CONFIG)
    return ai.SESSIONS[USER]


def result():
    from test_auto_production import result as fixture
    return fixture()


def package():
    return dict(images={'grid':b'grid','tt':b'tt'},draft=SimpleNamespace(title='Test',flyer_settings={}),
                rows=['row'],background=b'bg',logo=b'logo',asset_ids={},failures=[])


def test_unapproved_dm_and_groups_cannot_start(isolated):
    assert not ai.handle(event(ai.START,uid='Uother'),CONFIG)
    assert not ai.handle(event(ai.START,source='group'),CONFIG)
    assert not ai.SESSIONS
    isolated[0].reply_messages.assert_not_called()


def test_main_only_routes_verified_owner_dm_into_wizard(isolated):
    main.handle_event(event(ai.START),CONFIG)
    assert USER in ai.SESSIONS
    assert isolated[0].reply_messages.called


def test_parse_render_save_pipeline_and_repeated_buttons_are_idempotent(monkeypatch,isolated):
    from services import production_intake,production_service,asset_service
    analyze=Mock(return_value=result());monkeypatch.setattr(production_intake,'analyze',analyze)
    render=Mock(side_effect=lambda s:setattr(s,'package',package()) or setattr(s,'stage','preview'))
    monkeypatch.setattr(ai,'_render',render)
    upload=Mock(side_effect=[SimpleNamespace(id=50),SimpleNamespace(id=51)])
    monkeypatch.setattr(asset_service,'upload_image_asset',upload)
    save=Mock(return_value=99);monkeypatch.setattr(production_service,'persist_new_project',save)
    s=start()
    ai.handle(event('公演概要'),CONFIG);ai.handle(event('デザイン: 青と紫の光'),CONFIG)
    s.document='source text'
    analyze.assert_not_called();render.assert_not_called();save.assert_not_called()
    button=press(s,'analyze');ai.handle(button,CONFIG);ai.handle(button,CONFIG)
    analyze.assert_called_once();assert s.stage=='review'
    ai.handle(press(s,'analyze'),CONFIG);analyze.assert_called_once()
    assert '※必須' in ai._status(s)[-1]['text']
    preview=press(s,'preview');ai.handle(preview,CONFIG);ai.handle(preview,CONFIG)
    render.assert_called_once();assert s.stage=='preview';save.assert_not_called();upload.assert_not_called()
    button=press(s,'save');ai.handle(button,CONFIG);ai.handle(button,CONFIG);ai.handle(press(s,'save'),CONFIG)
    save.assert_called_once();assert s.project_id==99 and upload.call_count==2
    assert s.package['draft'].flyer_settings==dict(bg_id=50,logo_id=51)
    assert all(call.args[0]==USER for call in isolated[1].call_args_list)


def test_edits_invalidate_old_review_buttons_without_paid_calls(monkeypatch):
    render=Mock();monkeypatch.setattr(ai,'_render',render)
    s=start();s.result=result();s.stage='review';old=press(s,'preview')
    ai.handle(event('訂正: OPENは10:20'),CONFIG)
    assert s.stage=='collect' and s.correction=='OPENは10:20'
    ai.handle(old,CONFIG);render.assert_not_called()


def test_part_selection_keeps_only_requested_parts(monkeypatch):
    s=start();s.result=result();s.result['parts']*=3;s.stage='review'
    ai.handle(event('部数: 1'),CONFIG)
    assert s.selected==[0] and s.stage=='review'
    ai.handle(event('部数: 4'),CONFIG);assert s.selected==[0]


def test_expiration_and_restart_tokens_cannot_save(monkeypatch):
    s=start();button=press(s,'save');s.touched-=ai.TTL+1
    save=Mock();monkeypatch.setattr(ai,'_save',save)
    ai.handle(button,CONFIG);save.assert_not_called();assert USER not in ai.SESSIONS


def test_busy_blocks_edits_cancel_and_duplicate_work(monkeypatch):
    s=start();s.busy=True;s.overview='keep'
    ai.handle(event('概要: changed'),CONFIG);ai.handle(event('中止'),CONFIG)
    assert s.overview=='keep' and ai.SESSIONS[USER] is s


def test_unknown_save_outcome_cannot_be_retried(monkeypatch):
    from services import production_service,asset_service
    s=start();s.package=package();s.stage='preview'
    monkeypatch.setattr(asset_service,'upload_image_asset',Mock(return_value=SimpleNamespace(id=1)))
    save=Mock(side_effect=ValueError('保存を確認できません'));monkeypatch.setattr(production_service,'persist_new_project',save)
    ai.handle(press(s,'save'),CONFIG);assert s.uncertain
    ai.handle(press(s,'save'),CONFIG);save.assert_called_once()


def test_asset_failure_can_retry_without_reuploading_previous_asset(monkeypatch):
    from services import production_service,asset_service
    s=start();s.package=package();s.stage='preview'
    upload=Mock(side_effect=[SimpleNamespace(id=1),ValueError('素材保存失敗'),SimpleNamespace(id=2)])
    monkeypatch.setattr(asset_service,'upload_image_asset',upload)
    save=Mock(return_value=3);monkeypatch.setattr(production_service,'persist_new_project',save)
    ai.handle(press(s,'save'),CONFIG);save.assert_not_called();assert not s.uncertain
    ai.handle(press(s,'save'),CONFIG);save.assert_called_once();assert upload.call_count==3


def test_file_extraction_and_png_logo_as_file(monkeypatch):
    from services import production_intake,image_studio
    s=start();extract=Mock(return_value='extracted');monkeypatch.setattr(production_intake,'extract_document',extract)
    download=Mock(return_value=b'data');monkeypatch.setattr(ai,'_download',download)
    ai.handle(event(kind='file',fileName='tt.xlsx'),CONFIG)
    assert s.document=='extracted';extract.assert_called_once_with(b'data','tt.xlsx')
    ai.handle(event('ロゴ画像を送る'),CONFIG)
    monkeypatch.setattr(image_studio,'open_image',lambda _:object());monkeypatch.setattr(image_studio,'png',lambda _:b'alpha-png')
    ai.handle(event(kind='file',fileName='logo.png'),CONFIG)
    assert s.logo==b'alpha-png' and s.image_target==''


def test_download_rejects_oversized_stream_and_auth_stays_on_line_host(monkeypatch):
    response=Mock();response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
    response.iter_content.return_value=[b'12345',b'67890']
    get=Mock(return_value=response);monkeypatch.setattr(ai.requests,'get',get)
    with pytest.raises(ValueError,match='上限'):ai._download(dict(id='1234'),CONFIG,8)
    assert get.call_args.args[0]=='https://api-data.line.me/v2/bot/message/1234/content'
    with pytest.raises(ValueError):ai._download(dict(id='../../evil'),CONFIG,8)
    assert get.call_count==1


def test_render_reuses_background_after_failure_and_honors_template(monkeypatch):
    from services import production_service as production,artist_service,image_studio,template_service
    s=start();s.design='光 青 紫';s.result=result();s.stage='review'
    s.selected=[0]
    monkeypatch.setattr(artist_service,'list_artists',lambda:[])
    monkeypatch.setattr(template_service,'list_templates',lambda:[])
    monkeypatch.setattr(production,'read_default_logo',lambda:b'logo')
    bg=Mock(return_value=b'bg');monkeypatch.setattr(image_studio,'generate_background',bg)
    render=Mock(side_effect=[ValueError('layout'),package()]);monkeypatch.setattr(production,'render_package',render)
    with pytest.raises(ValueError):ai._render(s)
    ai._render(s)
    bg.assert_called_once();assert s.stage=='preview' and render.call_count==2
    from models.event_format import KEY
    assert not render.call_args.args[0].settings[KEY]['enabled']


def test_other_owner_cannot_reuse_another_users_buttons(isolated):
    s=start();s.stage='review';s.result=result()
    config=main.BotConfig('s','at',frozenset([USER,'Uowner2']),frozenset())
    ai.handle(event(ai.START,uid='Uowner2'),config)
    original_revision=ai.SESSIONS['Uowner2'].revision
    stolen=press(s,'preview');stolen['source']['userId']='Uowner2'
    ai.handle(stolen,config)
    assert ai.SESSIONS['Uowner2'].stage=='collect'
    assert ai.SESSIONS['Uowner2'].revision==original_revision


def test_no_paid_calls_for_missing_inputs_or_missing_bot_key(monkeypatch):
    from services import production_intake
    s=start();analyze=Mock();monkeypatch.setattr(production_intake,'analyze',analyze)
    ai.handle(press(s,'analyze'),CONFIG);analyze.assert_not_called()
    monkeypatch.undo()
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    with pytest.raises(ValueError,match='OPENAI_API_KEY'):ai._credentials()


def test_preview_delivery_failure_keeps_package_and_status_does_not_render(monkeypatch,isolated):
    s=start();s.package=package();s.stage='preview'
    isolated[0].upload_generated_png.return_value=None
    render=Mock();monkeypatch.setattr(ai,'_render',render)
    ai.handle(event('確認'),CONFIG)
    assert s.stage=='preview' and s.package is not None and not s.busy
    render.assert_not_called()
    isolated[0].upload_generated_png.return_value='https://example.com/img.png'
    ai.handle(event('確認'),CONFIG);render.assert_not_called()
    assert len(isolated[1].call_args.args[1])==3


def test_analysis_failure_is_explicitly_retryable_and_not_automatic(monkeypatch):
    s=start();s.overview='overview';s.document='text'
    analyze=Mock(side_effect=ValueError('解析できません'));monkeypatch.setattr(ai,'_analyze',analyze)
    ai.handle(press(s,'analyze'),CONFIG)
    analyze.assert_called_once();assert s.stage=='collect' and not s.busy


def test_cancel_and_expired_preview_buttons_do_not_write(monkeypatch):
    s=start();old=press(s,'save')
    ai.handle(event('中止'),CONFIG)
    save=Mock();monkeypatch.setattr(ai,'_save',save)
    ai.handle(old,CONFIG);save.assert_not_called()
    assert USER not in ai.SESSIONS


def test_async_worker_does_not_hold_webhook_or_use_reply_token_for_completion(monkeypatch,isolated):
    s=start();s.overview='overview';s.document='text'
    work=[];monkeypatch.setattr(ai,'_spawn',lambda task:work.append(task))
    analyze=Mock(side_effect=lambda state:setattr(state,'stage','collect'));monkeypatch.setattr(ai,'_analyze',analyze)
    ai.handle(press(s,'analyze'),CONFIG)
    assert s.busy and len(work)==1;analyze.assert_not_called()
    work[0]();assert not s.busy
    assert isolated[1].call_args.args[0]==USER


def test_push_batches_no_retry_and_uses_only_authenticated_user(monkeypatch,isolated):
    monkeypatch.undo()
    post=Mock(return_value=Mock(status_code=200));monkeypatch.setattr(ai.requests,'post',post)
    assert ai._push(USER,[ai._text('text')]*6,CONFIG)
    assert post.call_count==2
    assert [len(call.kwargs['json']['messages']) for call in post.call_args_list]==[5,1]
    assert all(call.kwargs['json']['to']==USER for call in post.call_args_list)
    assert post.call_args_list[0].kwargs['headers']['X-Line-Retry-Key']!=post.call_args_list[1].kwargs['headers']['X-Line-Retry-Key']
    post.reset_mock();post.side_effect=ai.requests.Timeout('SECRET')
    assert not ai._push(USER,[ai._text('test')],CONFIG)
    post.assert_called_once()


def test_credentials_remain_on_server_never_in_status(monkeypatch):
    s=start();monkeypatch.setenv('OPENAI_API_KEY','SECRETKEY')
    assert 'SECRETKEY' not in json.dumps(ai._status(s),ensure_ascii=False)
    assert '利用コード' not in json.dumps(ai._status(s),ensure_ascii=False)


def test_entering_ai_clears_only_owners_private_photo_wait(isolated):
    main.pending_store.put('dm:'+USER,1,'old private',ai.time.time())
    main.pending_store.put(USER,2,'group photo',ai.time.time())
    main.handle_event(event(ai.START),CONFIG)
    assert main.pending_store.pop_valid('dm:'+USER,ai.time.time()) is None
    assert main.pending_store.pop_valid(USER,ai.time.time())==(2,'group photo',main.PENDING_MODE_REPLACE)


def test_layout_failure_explains_stop_and_keeps_review_and_background(monkeypatch,isolated):
    s=start();s.result=result();s.stage='review';s.bg_cache=dict(hash='same',data=b'cached-background')
    monkeypatch.setattr(ai,'_render',Mock(side_effect=ValueError('配置の自動検査を通過しませんでした：subtitle／date：重なり')))
    ai.handle(press(s,'preview'),CONFIG)
    message=isolated[1].call_args.args[1][0]['text']
    assert '生成を停止' in message and '保持' in message and '確認' in message
    assert s.stage=='review' and s.result is not None and s.bg_cache['data']==b'cached-background' and not s.busy
