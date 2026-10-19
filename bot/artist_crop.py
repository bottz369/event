"""Owner-DM artist crop preview, incremental controls and explicit global save."""
import io
import re
import secrets
import threading
import time

LOCK = threading.RLock()
SESSIONS = {}
TTL = 600


def command(text):
    if len(text or '') > 200 or '■' in (text or ''):
        return None
    match = re.fullmatch(r'(.+?)(?:のアー写(?:配置|位置)?|アー写配置|アー写位置)(?:を|：|:)?\s*(.*)', text.strip())
    if match:
        return match[1].strip('「」 '), match[2].strip() or '全体を収める'
    return None


def _spawn(work):
    threading.Thread(target=work, daemon=True).start()


def _message(session, text, actions):
    from bot import main
    return dict(type='text', text=text, quickReply=dict(items=[dict(type='action', action=dict(
        type='postback', label=main._truncate_label(label),
        data=f"ac|{session['token']}|{action}", displayText=label)) for label, action in actions]))


def _preview(user, session, instruction, config):
    from bot import main, auto_production
    from services import artist_crop
    try:
        from database import get_image_url
        from logic_grid import load_image_from_url, apply_manual_crop
        image = session.get('image')
        if image is None:
            image = load_image_from_url(get_image_url(session['artist'].image_filename))
        if image is None:
            raise ValueError('アー写を取得できませんでした。画像登録を確認してください。')
        crop = artist_crop.adjust(image, session['crop'], instruction)
        from services.face_framing import protect
        crop = protect(image, session['artist'].image_filename, crop)
        preview = apply_manual_crop(image, *crop)
        output = io.BytesIO(); preview.save(output, format='PNG')
        url = main.upload_generated_png(output.getvalue(), 0, 'artist_crop_'+session['token'])
        if not url:
            raise ValueError('プレビューを配信できませんでした。保存せずに終了しました。')
        with LOCK:
            if SESSIONS.get(user) is not session:
                return
            session.update(image=image, crop=crop, stage='ready', time=time.time(), token=secrets.token_hex(8))
            controls = _message(session,
                f"{session['artist'].name} の調整プレビュー（未保存）です。\n"
                '「右30」「縮小15%」のような追加指示もできます。\n'
                '顔の見切れ防止を自動適用します。黒い余白は許容します。元画像ですでに切れている顔は復元できません。\n'
                '保存するとアーティスト管理の共通設定が変わり、このアーティストを使う全プロジェクトの次回生成に反映されます。保存済みの完成画像は再生成するまで変わりません。',
                [('縮小10%', '縮小10%'), ('拡大10%', '拡大10%'), ('左20', '左20'), ('右20', '右20'),
                 ('上20', '上20'), ('下20', '下20'), ('全体を収める', '全体を収める'),
                 ('リセット', 'リセット'), ('この配置を保存', 'save'), ('中止', 'cancel')])
            messages = [main.build_image_message(url, url), controls]
        auto_production._push(user, messages, config)
    except Exception as exc:
        main.logger.exception('artist crop preview failed')
        with LOCK:
            if SESSIONS.get(user) is session:
                session['stage'] = 'failed'
        auto_production._push(user, [dict(type='text', text=str(exc) if isinstance(exc, ValueError)
            else '配置プレビューを作れませんでした。保存していません。新しく依頼してください。')], config)


def handle(event, config):
    from bot import main
    source = event.get('source') or {}
    user = source.get('userId')
    if source.get('type') != 'user' or not main._is_owner(user, config):
        return False
    text = ((event.get('message') or {}).get('text')) or ''
    data = ((event.get('postback') or {}).get('data')) or ''
    request = command(text)
    followup = bool(re.fullmatch(r'(?:全体を収める|リセット|(?:縮小|拡大)(?:\d+(?:\.\d+)?[%％]?)?|[左右上下]\d*(?:px|ピクセル)?)', text.strip()))
    if request is None and not data.startswith('ac|') and not followup:
        return False
    def reply(message):
        main.reply_messages(event.get('replyToken', ''), [message if isinstance(message, dict)
            else dict(type='text', text=message)], config.channel_access_token)
    with LOCK:
        for key in [k for k, s in SESSIONS.items() if time.time()-s['time'] > TTL and s['stage'] != 'busy']:
            SESSIONS.pop(key, None)
        session = SESSIONS.get(user)
        if request:
            if session and session['stage'] == 'busy':
                reply('プレビューを作成中です。完了をお待ちください。'); return True
            from services import artist_service
            name, instruction = request
            artists = [a for a in artist_service.list_artists() if a.name == name]
            if len(artists) != 1 or not artists[0].image_filename:
                reply('登録名と完全一致するアー写が1件必要です。「花いろはのアー写を全体を収める」のように指定してください。'); return True
            from services.artist_crop import snapshot
            artist = artists[0]
            session = dict(token=secrets.token_hex(8), time=time.time(), artist=artist,
                baseline=snapshot(artist), crop=(artist.crop_scale, artist.crop_x, artist.crop_y), stage='busy')
            SESSIONS[user] = session
        else:
            if followup and not data:
                if not session:
                    return False
                data = f"ac|{session['token']}|{text.strip()}"
            fields = data.split('|')
            if len(fields) != 3 or not session or fields[1] != session['token']:
                reply('古いボタンか期限切れです。新しくアー写の調整を依頼してください。'); return True
            instruction = fields[2]
            if instruction == 'cancel' and session['stage'] != 'busy':
                SESSIONS.pop(user, None); reply('調整を中止しました。保存していません。'); return True
            if session['stage'] != 'ready':
                reply('処理中または処理済みです。最新のプレビューをご確認ください。'); return True
            if instruction == 'save':
                from services.artist_crop import save
                session['stage'] = 'done'  # Consume before any write, including ambiguous outcomes.
                try:
                    save(session['artist'].id, session['baseline'], session['crop'])
                    reply('配置を保存しました！アプリのアーティスト管理にも反映されます。完成画像にはプロジェクトの画像再生成が必要です。')
                except ValueError as exc:
                    reply(str(exc))
                except Exception:
                    main.logger.exception('artist crop save failed')
                    reply('保存結果をアプリのアーティスト管理で確認してください。このボタンでは再保存できません。')
                return True
            if not re.fullmatch(r'(?:全体を収める|リセット|(?:縮小|拡大)(?:\d+(?:\.\d+)?[%％]?)?|[左右上下]\d*(?:px|ピクセル)?)', instruction):
                reply('無効な操作です。最新のボタンを使ってください。'); return True
            session['stage'] = 'busy'
        reply('配置プレビューを作ります。完了後にこの個人トークへ通知します。まだ保存しません。')
        _spawn(lambda: _preview(user, session, instruction, config))
        return True
