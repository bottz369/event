from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from models.artist import ArtistView
from bot import artist_crop as ac, main


@pytest.mark.parametrize('text,result', [
    ('花いろはのアー写を顔が切れないように', ('花いろは', '顔が切れないように')),
    ('Testのアー写位置：縮小20%右30', ('Test', '縮小20%右30')),
    ('再生成', None), ('■概要\nTestのアー写を縮小', None)])
def test_command(text,result):
    assert ac.command(text) == result


def setup(monkeypatch):
    from services import artist_service
    ac.SESSIONS.clear()
    cfg = SimpleNamespace(channel_access_token='t', owner_user_ids=frozenset(['owner']))
    sent=[]
    monkeypatch.setattr(main,'reply_messages', lambda _, messages, *args: sent.extend(messages))
    monkeypatch.setattr(artist_service,'list_artists', lambda: [ArtistView(5,'Test','photo.png',False,1.,0,0)])
    jobs=[]; monkeypatch.setattr(ac,'_spawn',jobs.append)
    def send(text='',data='',user='owner',kind='user'):
        return ac.handle(dict(type='postback' if data else 'message',source=dict(type=kind,userId=user),
            replyToken='r',message=dict(type='text',text=text),postback=dict(data=data)),cfg)
    return cfg,sent,jobs,send


def test_owner_only_and_no_write_before_preview(monkeypatch):
    cfg,sent,jobs,send=setup(monkeypatch)
    assert not send('Testのアー写を縮小',user='other')
    assert not send('Testのアー写を縮小',kind='group')
    assert send('Testのアー写を縮小')
    assert len(jobs)==1 and ac.SESSIONS['owner']['stage']=='busy'
    assert 'まだ保存しません' in sent[-1]['text']


def test_actual_preview_then_increment_and_confirm_once(monkeypatch):
    from PIL import Image
    from services import artist_crop
    from bot import auto_production
    import logic_grid, database
    cfg,sent,jobs,send=setup(monkeypatch)
    pushed=[]
    monkeypatch.setattr(database,'get_image_url',lambda _: 'https://example.com/photo.png')
    monkeypatch.setattr(logic_grid,'load_image_from_url',lambda _:Image.new('RGB',(600,900),'white'))
    upload=Mock(return_value='https://example.com/preview.png'); monkeypatch.setattr(main,'upload_generated_png',upload)
    monkeypatch.setattr(auto_production,'_push',lambda _,messages,*a:pushed.extend(messages))
    save=Mock();monkeypatch.setattr(artist_crop,'save',save)
    send('Testのアー写を顔が見切れないように'); jobs.pop()()
    s=ac.SESSIONS['owner']; old=s['token']
    assert s['stage']=='ready' and s['crop'][0]<1
    assert pushed[0]['type']=='image' and '全プロジェクト' in pushed[1]['text']
    save.assert_not_called()
    send(data=f'ac|{old}|右20'); jobs.pop()()
    assert s['crop'][1]==20 and s['token']!=old
    send(data=f'ac|{old}|save');save.assert_not_called()
    token=s['token'];send(data=f'ac|{token}|save',user='other');save.assert_not_called()
    send(data=f'ac|{token}|save');send(data=f'ac|{token}|save')
    save.assert_called_once_with(5,s['baseline'],s['crop'])


def test_cancel_expiry_and_failed_preview_cannot_save(monkeypatch):
    from bot import auto_production
    from services import artist_crop
    import logic_grid,database
    cfg,sent,jobs,send=setup(monkeypatch)
    monkeypatch.setattr(database,'get_image_url',lambda _:None)
    monkeypatch.setattr(logic_grid,'load_image_from_url',lambda _:None)
    monkeypatch.setattr(auto_production,'_push',Mock())
    save=Mock();monkeypatch.setattr(artist_crop,'save',save)
    send('Testのアー写を縮小');jobs.pop()();s=ac.SESSIONS['owner']
    send(data=f"ac|{s['token']}|save");save.assert_not_called()
    send(data=f"ac|{s['token']}|cancel");assert 'owner' not in ac.SESSIONS
    send('Testのアー写を縮小');s=ac.SESSIONS['owner'];s.update(stage='ready',time=0)
    send(data=f"ac|{s['token']}|save");save.assert_not_called()


def test_save_failure_consumed_and_not_retried(monkeypatch):
    from services import artist_crop
    cfg,sent,jobs,send=setup(monkeypatch)
    send('Testのアー写を縮小');s=ac.SESSIONS['owner'];s['stage']='ready'
    save=Mock(side_effect=RuntimeError('unknown'));monkeypatch.setattr(artist_crop,'save',save)
    send(data=f"ac|{s['token']}|save");send(data=f"ac|{s['token']}|save")
    save.assert_called_once()


def test_text_followup_uses_unsaved_crop_without_hijacking_other_commands(monkeypatch):
    cfg,sent,jobs,send=setup(monkeypatch)
    assert not send('右30')
    send('Testのアー写を縮小');s=ac.SESSIONS['owner'];s['stage']='ready';s['crop']=(.8,20,0)
    assert not send('プロジェクト更新')
    assert send('右30') and s['stage']=='busy'
    assert s['crop']==(.8,20,0)  # Worker will apply once to this draft.
    assert len(jobs)==2


def test_main_dispatches_only_owner_dm(monkeypatch):
    cfg=main.BotConfig(channel_secret='s',channel_access_token='t',owner_user_ids=frozenset(['owner']),allowed_group_ids=frozenset())
    handler=Mock(return_value=True);monkeypatch.setattr(ac,'handle',handler)
    main.handle_event(dict(type='message',source=dict(type='user',userId='owner'),replyToken='r',
        message=dict(type='text',text='Testのアー写を全体を収める')),cfg)
    handler.assert_called_once()
    main.handle_event(dict(type='message',source=dict(type='user',userId='other'),replyToken='r',
        message=dict(type='text',text='Testのアー写を全体を収める')),cfg)
    handler.assert_called_once()
