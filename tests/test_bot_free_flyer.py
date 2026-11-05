from copy import deepcopy
import hashlib
import io
from unittest.mock import Mock
import pytest
from PIL import Image
from bot import main,free_flyer as bot,auto_production
from services import free_flyer as ff


def png(color='red'):
    output=io.BytesIO();Image.new('RGB',(100,140),color).save(output,'PNG');return output.getvalue()


@pytest.fixture
def flow(monkeypatch):
    bot.SESSIONS.clear();auto_production.SESSIONS.clear()
    cfg=main.BotConfig(channel_secret='secret',channel_access_token='token',owner_user_ids=frozenset(['owner']),allowed_group_ids=frozenset())
    sent=[];pushed=[];jobs=[];disk={};images={}
    monkeypatch.setattr(bot.store,'save',lambda owner,state:disk.update({owner:deepcopy(state)}))
    monkeypatch.setattr(bot.store,'load',lambda owner:deepcopy(disk.get(owner)))
    monkeypatch.setattr(bot,'_spawn',jobs.append)
    monkeypatch.setattr(main,'reply_messages',lambda _,messages,*args:sent.extend(messages))
    monkeypatch.setattr(auto_production,'_push',lambda _,messages,*args:pushed.extend(messages))
    monkeypatch.setattr(main,'download_image',lambda *a:(png(),'image/png'))
    import database
    monkeypatch.setattr(database,'get_image_url',lambda path:'https://example.com/'+path)
    def put(data):
        path=ff.PREFIX+hashlib.sha256(data).hexdigest()+'.png';images[path]=data;return path
    monkeypatch.setattr(ff,'put_image',put);monkeypatch.setattr(ff,'get_image',lambda path:images[path])
    edit=Mock(return_value=png('blue'));analyze=Mock(return_value=dict(title='Tour',fields=[dict(id='f1',label='日付',value='11/29(日)'),dict(id='f2',label='会場',value='Venue')],fixed_note='装飾とロゴは画像の一部'))
    save=Mock(return_value=55);interpret=Mock(return_value={'f1':'12/5(土)'})
    monkeypatch.setattr(ff,'edit',edit);monkeypatch.setattr(ff,'analyze',analyze);monkeypatch.setattr(ff,'save',save);monkeypatch.setattr(ff,'interpret_changes',interpret)
    monkeypatch.setenv('OPENAI_API_KEY','fake-test-key')
    owner=bot._owner('owner',cfg)
    def send(text='',action=None,image=False,user='owner',kind='user',data=None,event_id=None):
        if action:
            s=bot.SESSIONS[owner];data=f"ff|{s['token']}|{s['revision']}|{action}"
        event=dict(type='postback' if data else 'message',replyToken='reply',source=dict(type=kind,userId=user),
            message=dict(type='image',id='photo') if image else dict(type='text',text=text),postback=dict(data=data or ''))
        if event_id:event['webhookEventId']=event_id
        return bot.handle(event,cfg)
    def run():
        jobs.pop(0)()
    def start():
        send('画像からフライヤー');send(image=True);run()
        return bot.SESSIONS[owner]
    return dict(cfg=cfg,sent=sent,pushed=pushed,jobs=jobs,disk=disk,images=images,edit=edit,analyze=analyze,save=save,interpret=interpret,send=send,run=run,start=start,owner=owner)


def test_full_loop_confirm_scope_save_resume_and_natural_edit(flow):
    f=flow;s=f['start']();original=s['doc']['original']
    f['edit'].assert_not_called();f['save'].assert_not_called()
    f['send']('立体感を増やして');f['send'](action='generate');f['run']()
    assert s['doc']['original']==original and s['doc']['current']!=original
    assert len(s['doc']['history'])==1
    f['send']('少し青く');f['send'](action='generate');f['run']()
    assert f['edit'].call_count==2
    f['send'](action='save');f['save'].assert_not_called()
    f['send'](action='analyze');f['run']()
    assert s['phase']=='fields' and not s['doc']['selected']
    f['send'](action='toggle:f1');f['send'](action='review')
    assert s['phase']=='save_review' and s['doc']['selected']==['f1']
    f['send'](action='save');f['run']()
    assert s['project_id']==55 and s['phase']=='saved'
    saved=deepcopy(f['save'].call_args.args[0]);assert saved['original']==original
    f['send']('日付を12/5(土)に');f['send'](action='interpret');f['run']()
    assert s['phase']=='proposal';f['send'](action='apply');f['run']()
    assert s['phase']=='save_review' and s['doc']['fields'][0]['value']=='12/5(土)'
    assert f['edit'].call_args.kwargs['reference_names']==[]
    f['send'](action='save');f['run']()
    assert f['save'].call_args.args[1]==55
    bot.SESSIONS.clear();f['send']('画像制作を再開')
    assert bot.SESSIONS[f['owner']]['project_id']==55
    assert f['edit'].call_count==3
    assert all(len(message.get('text',''))<=5000 for message in f['sent'])


def test_old_duplicate_and_other_owner_buttons_cannot_generate(flow):
    f=flow;s=f['start']();f['send']('青に')
    stale=f"ff|{s['token']}|{s['revision']}|generate"
    f['send'](data=stale,event_id='one');f['send'](data=stale,event_id='one')
    assert len(f['jobs'])==1
    f['run']();f['send'](data=stale)
    assert f['edit'].call_count==1
    assert not f['send'](data=stale,user='other')
    assert not f['send'](data=stale,kind='group')


def test_missing_image_or_instruction_never_calls_paid_api(flow):
    f=flow;f['send']('画像からフライヤー');f['send'](action='generate')
    assert not f['jobs']
    f['send'](image=True);f['run']();f['send'](action='generate')
    f['edit'].assert_not_called();f['analyze'].assert_not_called()


def test_error_is_uncertain_and_status_does_not_retry(flow):
    f=flow;s=f['start']();f['edit'].side_effect=ValueError('timeout')
    f['send']('青に');f['send'](action='generate');f['run']()
    assert s['phase']=='uncertain'
    f['send']('確認');f['send'](action='generate')
    f['edit'].assert_called_once();assert not f['jobs']
    f['save'].assert_not_called()


def test_paid_image_storage_recovery_does_not_generate_again(flow,monkeypatch):
    f=flow;s=f['start']();put=ff.put_image
    monkeypatch.setattr(ff,'put_image',Mock(side_effect=ValueError('storage')))
    f['send']('青に');f['send'](action='generate');f['run']()
    assert s['phase']=='uncertain' and s.get('_result_bytes')
    assert '_result_bytes' not in f['disk'][f['owner']]
    monkeypatch.setattr(ff,'put_image',put)
    f['send'](action='recover');f['run']()
    assert s['phase']=='edit' and not s.get('_result_bytes')
    f['edit'].assert_called_once()


def test_field_selection_and_correction_do_not_alter_image(flow):
    f=flow;s=f['start']();f['send'](action='analyze');f['run']();current=s['doc']['current']
    f['send']('編集項目: f99');assert s['doc']['selected']==[]
    f['send']('項目訂正: f1=12/5(土)');f['send']('項目追加: 料金=5000円')
    assert s['doc']['fields'][-1]['label']=='料金' and s['doc']['current']==current
    f['edit'].assert_not_called();f['save'].assert_not_called()
    f['send']('編集項目: f1,f3');assert s['doc']['selected']==['f1','f3']


def test_original_not_replaced_without_new_session(flow):
    f=flow;s=f['start']();original=s['doc']['original']
    f['send'](image=True);assert not f['jobs'] and s['doc']['original']==original
    f['send']('素材画像: ロゴ: Tour logo');f['send'](image=True);f['run']()
    assert s['doc']['assets'][0]['kind']=='logo' and s['doc']['assets'][0]['register']
    assert s['doc']['original']==original


def test_checkpoint_failure_stops_before_api(flow,monkeypatch):
    f=flow;s=f['start']();f['send']('青に')
    monkeypatch.setattr(bot.store,'save',Mock(side_effect=RuntimeError('offline')))
    f['send'](action='generate')
    assert not f['jobs'];f['edit'].assert_not_called()


def test_no_interception_of_regular_work_without_free_session(flow):
    assert not flow['send']('AIおまかせ制作')
    assert not flow['send']('フライヤー')


def test_main_owner_dispatch(flow,monkeypatch):
    handler=Mock(return_value=True);monkeypatch.setattr(bot,'handle',handler)
    main.handle_event(dict(type='message',source=dict(type='user',userId='owner'),replyToken='r',message=dict(type='text',text='画像からフライヤー')),flow['cfg'])
    handler.assert_called_once()


def test_saved_project_refuses_foreign_line_owner(flow,monkeypatch):
    f=flow;doc=ff.new_document(ff.PREFIX+'a'*64+'.png');doc['owner']='other'
    monkeypatch.setattr(ff,'load',lambda _: (doc,'base'))
    f['send']('画像プロジェクト: #55');f['run']()
    assert bot.SESSIONS[f['owner']].get('doc') is None
    f['edit'].assert_not_called()


def test_photo_can_be_first_message_without_command(flow):
    f=flow;assert f['send'](image=True);f['run']()
    assert bot.SESSIONS[f['owner']]['doc']['original']
    f['edit'].assert_not_called();f['save'].assert_not_called()


def test_pending_artist_photo_is_not_stolen(flow):
    f=flow
    main.pending_store.put('dm:owner',99,'Artist',__import__('time').time())
    try:
        assert not f['send'](image=True)
        assert main.pending_store.has_valid('dm:owner',__import__('time').time())
        assert not f['jobs']
    finally:main.pending_store.pop_valid('dm:owner',__import__('time').time())


def test_resume_while_job_running_does_not_replace_in_memory_session(flow):
    f=flow;s=f['start']();f['send']('青に');f['send'](action='generate')
    f['send']('画像制作を再開')
    assert bot.SESSIONS[f['owner']] is s
    f['run']();assert s['phase']=='edit'


def test_shared_catalog_and_artist_reference_use_existing_data(flow,monkeypatch):
    from services import asset_service,artist_service
    from types import SimpleNamespace
    f=flow;s=f['start']()
    monkeypatch.setattr(asset_service,'list_assets_by_type',lambda kind:[SimpleNamespace(id=7,name='登録ロゴ')] if kind=='logo' else [])
    monkeypatch.setattr(asset_service,'get_asset_view',lambda _:SimpleNamespace(id=7,name='登録ロゴ'))
    monkeypatch.setattr(asset_service,'read_image_asset',lambda _:png('green'))
    f['send'](action='catalog:0');f['send'](action='reference:7');f['run']()
    assert s['doc']['assets'][0]['name']=='登録ロゴ' and not s['doc']['assets'][0]['register']
    monkeypatch.setattr(artist_service,'get_artists_by_names',lambda _:[SimpleNamespace(is_deleted=False,image_filename='artist.png')])
    fetch=Mock(return_value=png('yellow'));monkeypatch.setattr(ff,'fetch_image_bytes',fetch)
    f['send']('アー写: Artist');f['run']()
    assert s['doc']['assets'][1]['name']=='Artist'
    fetch.assert_called_once();f['edit'].assert_not_called()


def test_saved_free_flow_can_yield_to_normal_creation(flow):
    f=flow;s=f['start']();s['phase']='saved';s['project_id']=55
    assert not f['send']('AIおまかせ制作')
    assert s['phase']=='cancelled'
