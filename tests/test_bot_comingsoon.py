from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from bot import comingsoon as cs
from bot import main


@pytest.mark.parametrize('text,expected', [('Secretをcomingsoonにして',('Secret',True)),('Secretのcomingsoonを解除して',('Secret',False)),('comingsoonにする',('',True)),('SecretをCOMINGSOONにして',('Secret',True)),('再生成',None)])
def test_commands(text,expected):
    assert cs.command(text)==expected


def test_confirm_bound_to_user_consumed_once_and_regenerates(monkeypatch):
    from services import event_service, comingsoon
    cs.SESSIONS.clear()
    monkeypatch.setattr(event_service,'list_recent_events',lambda **_ :([SimpleNamespace(project_id=12,title='Test',event_date=None)],False))
    monkeypatch.setattr(comingsoon,'project_slots',lambda _:[dict(part=None,index=0,artist='Secret',label='Secret',enabled=False)])
    save=Mock();regen=Mock();sent=[]
    monkeypatch.setattr(comingsoon,'set_project_slot',save)
    monkeypatch.setattr(main,'_spawn_regeneration',regen)
    monkeypatch.setattr(main,'reply_messages',lambda _,messages,*args:sent.extend(messages))
    cfg=SimpleNamespace(channel_access_token='test')
    event=dict(type='message',source=dict(type='user',userId='owner'),replyToken='reply')
    assert cs.handle(event,cfg,'Secretをcomingsoonにして')
    token=cs.SESSIONS[('dm','owner')]['token']
    def press(action,user='owner'):
        return cs.handle(dict(type='postback',source=dict(type='user',userId=user),replyToken='reply',postback=dict(data=f'cs|{token}|{action}')),cfg)
    press('project|12');press('select|0')
    assert 'よろしいですか' in sent[-1]['text'];save.assert_not_called()
    press('confirm|0','other');save.assert_not_called()
    press('confirm|0');press('confirm|0')
    save.assert_called_once_with(12,dict(part=None,index=0,artist='Secret',label='Secret',enabled=False),True)
    regen.assert_called_once()


@pytest.mark.parametrize('kind,owner,mentioned,active,allowed',[
    ('user',True,False,False,True),('user',False,False,False,False),
    ('group',False,True,True,True),('group',False,False,True,False),
    ('group',False,True,False,False)])
def test_ordinary_bot_authorization_guards_apply(monkeypatch,kind,owner,mentioned,active,allowed):
    cfg=main.BotConfig(channel_secret='s',channel_access_token='t',owner_user_ids=frozenset(['owner']),allowed_group_ids=frozenset())
    handler=Mock(return_value=True)
    monkeypatch.setattr(cs,'handle',handler)
    monkeypatch.setattr(main,'_passes_group_guard',lambda *_:kind=='group')
    monkeypatch.setattr(main,'_is_group_active',lambda _:active)
    monkeypatch.setattr(main,'is_self_mentioned',lambda _:mentioned)
    monkeypatch.setattr(main,'reply_text',Mock())
    source=dict(type=kind,userId='owner' if owner else 'member')
    if kind=='group':source['groupId']='group'
    main.handle_event(dict(type='message',source=source,replyToken='r',message=dict(type='text',text='comingsoonにする')),cfg)
    assert handler.called is allowed
