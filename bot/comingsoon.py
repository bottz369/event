"""Existing-project comingsoon edits. Called only after ordinary LINE auth guards."""
import re
import secrets
import threading
import time

TTL = 600
LOCK = threading.RLock()
SESSIONS = {}


def command(text):
    match = re.search(r'coming\s*soon|カミングスーン', text or '', re.I)
    if not match:
        return None
    name = re.sub(r'(?:を|の|は|[:：])\s*$', '', text[:match.start()].strip()).strip('「」 ')
    enabled = not bool(re.search(r'解除|戻|やめ|取り消|取消|オフ|\boff\b', text, re.I))
    return name, enabled


def handle(event, config, cleaned=None):
    from bot import main
    source = event.get('source') or {}
    user = source.get('userId')
    scope = source.get('groupId') or source.get('roomId') or 'dm'
    if not user:
        return False
    key = (scope, user)
    data = ((event.get('postback') or {}).get('data')) or ''
    request = command(cleaned) if cleaned is not None else None
    if request is None and not data.startswith('cs|'):
        return False
    reply = event.get('replyToken', '')
    def respond(text, buttons=()):
        message = dict(type='text', text=text)
        if buttons:
            message['quickReply'] = dict(items=[dict(type='action', action=dict(
                type='postback', label=main._truncate_label(label), data=value,
                displayText=label)) for label, value in buttons])
        main.reply_messages(reply, [message], config.channel_access_token)
    with LOCK:
        now = time.time()
        for expired in [k for k, s in SESSIONS.items() if now - s['time'] > TTL]:
            SESSIONS.pop(expired)
        if request is not None:
            if len(SESSIONS) >= 256 and key not in SESSIONS:
                respond('依頼が混み合っています。少し待って再度お試しください。'); return True
            name, enabled = request
            from services import event_service
            events, more = event_service.list_recent_events(page=0, limit=10)
            session = dict(token=secrets.token_hex(8), time=now, name=name,
                           enabled=enabled, events=events, page=0, more=more, stage='event')
            SESSIONS[key] = session
            show_events(session, respond)
            return True
        session = SESSIONS.get(key)
        fields = data.split('|')
        if len(fields) != 4 or not session or fields[1] != session['token']:
            respond('選択の期限が切れました。comingsoonの依頼からやり直してください。'); return True
        action, value = fields[2:]
        try:
            number = int(value)
            if action == 'events' and session['stage'] == 'event' and number >= 0:
                from services import event_service
                events, more = event_service.list_recent_events(page=number, limit=10)
                session.update(events=events, page=number, more=more)
                show_events(session, respond)
            elif action == 'project' and session['stage'] == 'event':
                if number not in [e.project_id for e in session['events']]:
                    raise ValueError('イベントを選び直してください。')
                from services.comingsoon import project_slots
                slots = project_slots(number)
                if session['name']:
                    slots = [s for s in slots if s['artist'] == session['name']]
                if not slots:
                    raise ValueError('対象の出演者が見つかりません。「comingsoonにする」から選び直してください。')
                session.update(project=number, slots=slots, stage='slot')
                show_slots(session, respond, 0)
            elif action == 'slots' and session['stage'] == 'slot' and number >= 0:
                show_slots(session, respond, number)
            elif action == 'select' and session['stage'] == 'slot' and 0 <= number < len(session['slots']):
                session.update(selected=number, stage='confirm')
                slot = session['slots'][number]
                effect = 'comingsoonにする' if session['enabled'] else 'comingsoonを解除する'
                respond(f"{slot['label']} を{effect}、でよろしいですか？", [
                    ('確定して画像を更新', f"cs|{session['token']}|confirm|0"),
                    ('中止', f"cs|{session['token']}|cancel|0")])
            elif action == 'confirm' and session['stage'] == 'confirm':
                from services.comingsoon import set_project_slot
                set_project_slot(session['project'], session['slots'][session['selected']], session['enabled'])
                session['stage'] = 'done'  # Consume before regeneration; retries never toggle.
                main._spawn_regeneration(session['project'], reply, config)
            elif action == 'cancel':
                SESSIONS.pop(key, None); respond('編集を中止しました。')
            else:
                respond('処理済みのボタンです。新しく依頼してください。')
        except (ValueError, IndexError) as exc:
            respond(str(exc))
        except Exception:
            main.logger.exception('comingsoon edit failed')
            respond('編集を完了できませんでした。少し待ってもう一度お試しください。')
        return True


def show_events(session, respond):
    token = session['token']; page = session['page']
    buttons = [(f"#{e.project_id} {main_label(e)}", f"cs|{token}|project|{e.project_id}")
               for e in session['events'][:10]]
    if page:
        buttons.append(('前のイベント', f'cs|{token}|events|{page-1}'))
    if session['more']:
        buttons.append(('次のイベント', f'cs|{token}|events|{page+1}'))
    respond('comingsoonを編集するイベントを選んでください。', buttons)


def main_label(event):
    from bot import main
    return main._event_label(event)[1]


def show_slots(session, respond, page):
    token = session['token']; slots = session['slots']
    buttons = [(s['label'], f'cs|{token}|select|{i}')
               for i, s in enumerate(slots) if page*10 <= i < (page+1)*10]
    if page:
        buttons.append(('前の出演者', f'cs|{token}|slots|{page-1}'))
    if (page+1)*10 < len(slots):
        buttons.append(('次の出演者', f'cs|{token}|slots|{page+1}'))
    respond('対象の出演枠を選んでください。', buttons)
