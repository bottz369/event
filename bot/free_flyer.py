"""Owner-private image workshop, separate from the normal flyer-set wizard."""
from copy import deepcopy
import hashlib
import hmac
import os
import re
import threading
import time
import uuid

from services import free_flyer as ff, free_flyer_store as store

LOCK=threading.RLock()
SESSIONS={}
STARTS=('画像からフライヤー','フライヤー画像を編集','自由フライヤー制作')
RESUME='画像制作を再開'


def _owner(user,config):
    return hmac.new(config.channel_secret.encode(),user.encode(),hashlib.sha256).hexdigest()


def _spawn(work):
    threading.Thread(target=work,daemon=True).start()


def _key():
    value=os.environ.get('OPENAI_API_KEY','')
    if not value:raise ValueError('BotのOpenAI接続設定が必要です。')
    return value


def _text(value):return dict(type='text',text=value)


def _controls(s,text,actions):
    from bot import main
    return dict(type='text',text=text,quickReply=dict(items=[dict(type='action',action=dict(type='postback',
        label=main._truncate_label(label),data=f"ff|{s['token']}|{s['revision']}|{action}",displayText=label))
        for label,action in actions]))


def _checkpoint(s):
    s['revision']+=1;s['touched']=time.time()
    store.save(s['owner'],{k:v for k,v in s.items() if not k.startswith('_')})


def _status(s,page=0):
    from bot.auto_production import _chunks
    if s['phase']=='busy':return [_text('処理中です。再起動などで結果が不明な場合も自動再試行はしません。後ほど「確認」で結果を確認してください。')]
    if s['phase']=='cancelled':return [_text('画像制作は終了しています。「画像からフライヤー」で新しく始められます。')]
    if not s.get('doc'):return [_text('作りたいフライヤーを画像で送信してください。PNG・JPEG・WebP、20MB・800万画素以内です。')]
    doc=s['doc'];lines=[doc['title'],f"画像制作 · 履歴 {len(doc['history'])}件"+(f" · 更新先 #{s['project_id']}" if s.get('project_id') else ''),ff.NOTICE]
    actions=[]
    if s['phase']=='fields':
        lines+=['■後からAI再編集できる項目（チェックしたものだけ）。長文は先頭のみ。全文は「項目確認: f1」で確認。']
        lines += [f"{'☑' if f['id'] in doc['selected'] else '□'} {f['id']} {f['label']}：{f['value'][:150]}" for f in doc['fields'][page*8:(page+1)*8]]
        actions += [(('☑' if f['id'] in doc['selected'] else '□')+' '+f['label'], 'toggle:'+f['id']) for f in doc['fields'][page*8:(page+1)*8]]
        if page:actions.append(('前の項目','page:'+str(page-1)))
        if (page+1)*8<len(doc['fields']):actions.append(('次の項目','page:'+str(page+1)))
        actions += [('項目・内容を確認した','review')]
        lines += ['固定画像部分：'+doc.get('fixed_note',''), '読み違いは「項目訂正: f1=正しい全文」、不足は「項目追加: 日付=11/29(日)」。文字を訂正しても画像は変わらないため、画像自体に誤りがあればデザイン調整へ戻って直してください。', '全件をまとめて選ぶには「編集項目: f1,f2,...」、選ばない場合は「編集項目: なし」。項目が無い場合も内容確認が必要です。']
    elif s['phase']=='save_review':
        lines += ['■選んだ編集項目（長文は先頭のみ。「項目確認: f1」で全文を確認）']+[f"{f['id']} {f['label']}：{f['value'][:100]}" for f in doc['fields'] if f['id'] in doc['selected']]
        lines += ['選択外の項目・装飾・ロゴ・アー写は画像の一部として保存します。原本は残し、完成画像・変更履歴と一緒にアプリへ保管します。日付・料金・時刻・名前・文字の誤りと画像全体を確認した上で保存してください。']
        actions += [('この内容で保存' if not s.get('project_id') else 'このプロジェクトを更新','save'),('編集項目を選び直す','fields')]
    elif s['phase']=='proposal':
        lines+=['■変更案（まだ生成していません）。長文は先頭のみ。「項目確認: f1」で全文を確認。']+[f"{c['label']}：{c['before'][:80]} → {c['after'][:80]}" for c in ff.replacements(doc,s['changes'])]
        actions += [('この変更を生成(API料金)','apply')]
    elif s['phase']=='uncertain':
        lines += ['前回の結果が不明です。'+s.get('error',''), '自動再試行はしません。']
        if s.get('_result_bytes'):actions += [('生成済み画像を再保管','recover')]
    elif s['phase']=='saved':
        lines += [f"アプリの一覧で #{s['project_id']} を確認できます。修正内容を自然な言葉で送信してください。選んだ編集項目の変更案を確認してからAI再編集します。"]
    else:
        lines += ['変更したい内容を自由に送信してください。例：「立体感を増やして」「雰囲気を青に」「デザインはそのまま12/5の会場だけ変更」。']
        if s.get('pending'):lines+=['■次の依頼',s['pending']]
        actions += [('この指示で生成(API料金)','generate'),('このデザインで確定(API解析)','analyze'),('登録素材を選ぶ','catalog:0')]
    if s['phase']=='saved' and s.get('pending'):actions += [('変更案を読む(API料金)','interpret')]
    if s['phase'] not in ('edit',):actions += [('デザイン調整に戻る','design')]
    if len(actions)<12:actions += [('中止','cancel')]
    messages=_chunks('\n'.join(lines))
    if actions:messages.append(_controls(s,'操作を選んでください。',actions))
    return messages


def _image_message(doc):
    from bot import main
    from database import get_image_url
    url=get_image_url(doc['current'])
    # A persisted small thumbnail avoids sending the full original for chat previews.
    thumb=get_image_url(doc.get('chat_preview') or doc['current'])
    return main.build_image_message(url,thumb)


def _work(user,s,action,message,config):
    from bot import main,auto_production
    try:
        doc=s.get('doc')
        if action=='image':
            data,_=main.download_image(message['id'],config.channel_access_token)
            path=ff.put_image(data)
            if s.get('attachment_kind'):
                if len(doc['assets'])>=6:raise ValueError('参照素材は6枚までです。')
                doc['assets'].append(dict(path=path,kind=s['attachment_kind'],name=s.get('attachment_name') or '追加素材',register=True))
                s['attachment_kind']=''
            else:
                s['doc']=ff.new_document(path);s['doc']['owner']=s['owner'];doc=s['doc']
            s['phase']='edit'
        elif action=='reference':
            if len(doc['assets'])>=6:raise ValueError('参照素材は6枚までです。')
            kind,value=s['ref_request']
            if kind=='アー写':
                from services.artist_service import get_artists_by_names
                from database import get_image_url
                from services.image_studio import MAX_BYTES
                from services.free_flyer import fetch_image_bytes
                artists=get_artists_by_names([value])
                if len(artists)!=1 or artists[0].is_deleted or not artists[0].image_filename:raise ValueError('登録アー写が見つかりません。')
                data=fetch_image_bytes(get_image_url(artists[0].image_filename),MAX_BYTES)
                name=value;asset_kind='flyer'
            else:
                from services.asset_service import read_image_asset,get_asset_view
                asset=get_asset_view(int(value))
                if not asset:raise ValueError('素材が見つかりません。')
                data=read_image_asset(int(value));name=asset.name or '登録素材';asset_kind='flyer'
            doc['assets'].append(dict(path=ff.put_image(data),name=name,kind=asset_kind,register=False))
            s['phase']='edit'
        elif action in ('generate','apply'):
            original=ff.get_image(doc['original']);current=ff.get_image(doc['current'])
            changes=s.get('changes') if action=='apply' else None
            locked=ff.replacements(doc,changes) if changes else None
            instruction=s['pending'] if not locked else '次の確定した項目だけを変更。その他の内容・デザインを維持。'
            result=ff.edit(current,original,instruction,_key(),[ff.get_image(a['path']) for a in doc['assets']],locked,reference_names=[a['kind']+': '+a['name'] for a in doc['assets']])
            # Never regenerate after a delivery/storage failure. Keep result in memory for recovery.
            s['_result_bytes']=result
            s['_result_prompt']=instruction
            s['_result_changes']=changes
            path=ff.put_image(result)
            updated=ff.revision(doc,path,instruction,changes)
            if not changes:updated.update(fields=[],selected=[],fixed_note='')
            s['doc']=updated;s['pending']='';s.pop('changes',None);s.pop('_result_bytes',None)
            try:
                preview=main.build_preview_png(result)
                updated['chat_preview']=ff.put_image(preview)
            except Exception:updated.pop('chat_preview',None)
            s['phase']='save_review' if changes else 'edit'
            if changes:updated['reviewed']=True  # Final explicit save reviews the new image too.
        elif action=='recover':
            result=s['_result_bytes'];path=ff.put_image(result)
            changes=s.get('_result_changes')
            s['doc']=ff.revision(doc,path,s.get('_result_prompt',''),changes)
            s['doc'].pop('chat_preview',None)
            if not changes:s['doc'].update(fields=[],selected=[],fixed_note='')
            s['phase']='save_review' if changes else 'edit'
            s['doc']['reviewed']=bool(changes)
        elif action=='analyze':
            result=ff.analyze(ff.get_image(doc['current']),_key())
            doc.update(result,selected=[],reviewed=False);s['phase']='fields'
        elif action=='interpret':
            s['changes']=ff.interpret_changes(doc,s['pending'],_key());s['phase']='proposal'
        elif action=='save':
            pid=ff.save(doc,s.get('project_id'),s.get('baseline'))
            s.update(project_id=pid,baseline=ff.fingerprint(doc),phase='saved')
        elif action=='resume_project':
            doc,baseline=ff.load(s['requested_project'])
            if doc.get('owner')!=s['owner']:raise ValueError('この個人トークで保存した画像プロジェクトだけを再開できます。')
            s.update(doc=doc,project_id=s['requested_project'],baseline=baseline,phase='saved')
        with LOCK:
            s.pop('_result_bytes',None);_checkpoint(s)
        messages=([_image_message(s['doc'])] if s.get('doc') and action not in ('interpret',) else [])+_status(s)
        auto_production._push(user,messages,config)
    except Exception as exc:
        main.logger.exception('image workshop action failed')
        with LOCK:
            # Ambiguous paid/save outcomes are never automatically repeated.
            s['phase']='uncertain' if action in ('generate','apply','analyze','interpret','save') else 'edit'
            s['error']=str(exc)[:600] if isinstance(exc,ValueError) else '処理を完了できませんでした。'
            try:
                # Bytes cannot enter JSON; preserve source/current recipe, not a broken checkpoint.
                _checkpoint(s)
            except Exception:pass
        auto_production._push(user,[_text(s['error']+'\n自動再試行はしません。「確認」で現在の画像を確認してください。保存結果が不明ならアプリの一覧で確認してください。新たな生成は「デザイン調整に戻る」で明示的に開始できます。')],config)


def _handle(event,config):
    from bot import main,auto_production
    source=event.get('source') or {};user=source.get('userId')
    if source.get('type')!='user' or not main._is_owner(user,config):return False
    message=event.get('message') or {};text=str(message.get('text') or '').strip()
    data=(event.get('postback') or {}).get('data','')
    owner=_owner(user,config);resume=re.fullmatch(r'画像プロジェクト[：:]?\s*#?(\d+)',text)
    with LOCK:
        s=SESSIONS.get(owner)
        if s and time.time()-s.get('touched',0)>store.TTL:
            SESSIONS.pop(owner,None);s=None
        photo_first=message.get('type')=='image' and (not s or s['phase']=='cancelled')
        if photo_first and (main.pending_store.has_valid('dm:'+user,time.time()) or
                (auto_production.SESSIONS.get(user) and not auto_production.SESSIONS[user].project_id)):
            return False
        if s and s['phase']=='saved' and text in (*auto_production.UPDATE_STARTS,auto_production.START,'フライヤー','アー写変更','新規作成'):
            s['phase']='cancelled';_checkpoint(s);return False
        trigger=text in STARTS or text==RESUME or bool(resume) or photo_first
        if not trigger and not data.startswith('ff|') and (not s or s['phase']=='cancelled'):return False
        def reply(messages):
            main.reply_messages(event.get('replyToken',''),messages if len(messages)<=5 else messages[:4]+messages[-1:],config.channel_access_token)
        if trigger:
            other=auto_production.SESSIONS.get(user)
            if other and not other.project_id:
                reply([_text('AIおまかせ制作が進行中です。そちらで「中止」または保存してから始めてください。')]);return True
            if text==RESUME:
                s=s or store.load(owner)
                if not s:reply([_text('再開できる下書きがありません。「画像からフライヤー」で始めてください。')]);return True
                SESSIONS[owner]=s
                reply(([_image_message(s['doc'])] if s.get('doc') else [])+_status(s));return True
            if s and s['phase'] not in ('cancelled','saved'):
                reply([_text('進行中の画像制作があります。「確認」で続行、「画像制作を中止」で終了できます。')]);return True
            s=dict(owner=owner,token=uuid.uuid4().hex[:16],revision=0,touched=time.time(),phase='edit',doc=None,pending='',seen=[])
            SESSIONS[owner]=s
            if photo_first:
                action='image'
            elif resume:
                s['requested_project']=int(resume[1]);action='resume_project'
            else:
                try:_checkpoint(s)
                except Exception:SESSIONS.pop(owner,None);reply([_text('下書きを保管できませんでした。少し待って再度お試しください。')]);return True
                reply([_text('画像から自由にフライヤーを制作します。画像と希望を送信し、生成ボタンで実行します。生成・読み取りには画像がOpenAIに送られAPI料金が発生します。原本は保持します。\n'+ff.NOTICE),*_status(s)]);return True
        else:
            if not s:
                s=store.load(owner)
                if s:SESSIONS[owner]=s
            if not s:reply([_text('下書きがありません。「画像制作を再開」で再表示してください。')]);return True
            event_id=event.get('webhookEventId')
            if event_id and event_id in s['seen']:reply([_text('受付済みの操作です。「確認」で結果を確認してください。')]);return True
            if data:
                parts=data.split('|')
                if len(parts)!=4 or parts[1]!=s['token'] or parts[2]!=str(s['revision']):
                    reply([_text('古いボタンです。「確認」で最新の状態を表示してください。')]);return True
                action=parts[3]
            elif text in ('確認','画像制作を確認'):
                reply(([_image_message(s['doc'])] if s.get('doc') else [])+_status(s));return True
            elif re.fullmatch(r'項目確認[：:]\s*f\d+',text) and s.get('doc'):
                key=re.search(r'f\d+',text)[0]
                field=next((f for f in s['doc']['fields'] if f['id']==key),None)
                if not field:reply([_text('項目が見つかりません。')]);return True
                value=s.get('changes',{}).get(key,field['value'])
                reply([_text(field['label']+'\n'+value)]);return True
            elif text in ('中止','画像制作を中止'):action='cancel'
            elif text in (*STARTS,*auto_production.UPDATE_STARTS,auto_production.START):
                reply([_text('先に「画像制作を中止」と送ってください。')]);return True
            elif message.get('type') in ('image','file'):
                if s.get('doc') and not s.get('attachment_kind'):
                    reply([_text('原本は置き換えません。追加素材なら「素材画像: ロゴ: 素材名」（背景・フライヤーも可）を先に送ってください。')]);return True
                action='image'
            elif text and s.get('doc'):
                action='text'
            else:reply(_status(s));return True
        if s['phase']=='busy':reply(_status(s));return True
        if action=='catalog' or action.startswith('catalog:'):
            from services.asset_service import list_assets_by_type
            page=int(action.split(':')[1]) if ':' in action else 0
            catalog=[dict(id=a.id,name=(a.name or '素材')[:80],kind=kind)
                     for kind in ('logo','background','flyer') for a in list_assets_by_type(kind)]
            page=max(0,min(page,max(0,(len(catalog)-1)//8)))
            s['catalog']=catalog[page*8:(page+1)*8]
            _checkpoint(s)
            actions=[(a['name'],'reference:'+str(a['id'])) for a in catalog[page*8:(page+1)*8]]
            if page:actions.append(('前の素材','catalog:'+str(page-1)))
            if (page+1)*8<len(catalog):actions.append(('次の素材','catalog:'+str(page+1)))
            actions.append(('制作に戻る','status'))
            reply([_controls(s,'共通アセットのロゴ・背景・フライヤー素材です。選ぶと次の生成で参照に使います。アー写は「アー写: 登録名」で追加できます。',actions)])
            return True
        if action=='status':reply(_status(s));return True
        if action.startswith('reference:'):
            ident=int(action.split(':')[1])
            if ident not in [a['id'] for a in s.get('catalog',[])]:
                reply([_text('素材一覧から選び直してください。')]);return True
            s['ref_request']=['素材ID',str(ident)];action='reference'
        if action=='cancel':
            s['phase']='cancelled';_checkpoint(s);reply([_text('画像制作を終了しました。保存済みのプロジェクトは残ります。')]);return True
        if action.startswith('page:') and s['phase']=='fields':
            page=int(action.split(':')[1]);reply(_status(s,max(0,min(page,7))));return True
        if action=='design' and s.get('doc'):
            s['phase']='edit';s['doc']['reviewed']=False;_checkpoint(s);reply(_status(s));return True
        if action=='fields' and s.get('doc'):
            s['phase']='fields';s['doc']['reviewed']=False;_checkpoint(s);reply(_status(s));return True
        if action.startswith('toggle:') and s['phase']=='fields':
            field=action.split(':')[1];doc=s['doc']
            if field not in [f['id'] for f in doc['fields']]:reply([_text('項目が見つかりません。')]);return True
            doc['selected']=[f for f in doc['selected'] if f!=field] if field in doc['selected'] else doc['selected']+[field]
            _checkpoint(s);reply(_status(s,[f['id'] for f in doc['fields']].index(field)//8));return True
        if action=='review' and s['phase']=='fields':
            s['doc']['reviewed']=True;s['phase']='save_review';_checkpoint(s)
            reply([_image_message(s['doc'])]+_status(s));return True
        if action=='text':
            if text=='素材一覧':
                s['pending_catalog']=True
                reply([_controls(s,'登録素材を選べます。',[('登録素材を選ぶ','catalog:0')])]);return True
            if not 1<=len(text)<=4000:reply([_text('依頼は4000文字以内で送ってください。')]);return True
            asset=re.fullmatch(r'素材画像[：:]\s*(ロゴ|背景|フライヤー)[：:]\s*(.{1,100})',text)
            ref=re.fullmatch(r'(素材ID|アー写)[：:]\s*(.{1,100})',text)
            if asset:
                s['attachment_kind']={'ロゴ':'logo','背景':'background','フライヤー':'flyer'}[asset[1]];s['attachment_name']=asset[2]
                _checkpoint(s);reply([_text('次に素材画像を送ってください。確定保存時に共通アセットにも登録します。')]);return True
            if ref:
                if ref[1]=='素材ID' and not ref[2].isdigit():reply([_text('素材IDは数字で指定してください。')]);return True
                s['ref_request']=[ref[1],ref[2]];action='reference'
            elif s['phase']=='fields':
                doc=deepcopy(s['doc']);change=re.fullmatch(r'項目訂正[：:]\s*(f\d+)=(.+)',text,re.S)
                extra=re.fullmatch(r'項目追加[：:]\s*([^=]{1,100})=(.+)',text,re.S)
                select=re.fullmatch(r'編集項目[：:]\s*(.*)',text,re.S)
                if change:
                    matches=[f for f in doc['fields'] if f['id']==change[1]]
                    if not matches:reply([_text('項目IDを確認してください。')]);return True
                    matches[0]['value']=change[2]
                elif extra and len(doc['fields'])<60:
                    number=max([int(f['id'][1:]) for f in doc['fields']]+[0])+1
                    doc['fields'].append(dict(id='f'+str(number),label=extra[1],value=extra[2]))
                elif select:
                    doc['selected']=[] if select[1]=='なし' else re.findall(r'f\d+',select[1])
                else:reply([_text('編集項目をボタンで選択してください。画像の修正は「デザイン調整に戻る」から行えます。')]);return True
                try:ff.validate(doc)
                except ValueError as exc:reply([_text(str(exc))]);return True
                s['doc']=doc
                _checkpoint(s);reply(_status(s));return True
            else:
                s['pending']=text
                if s['phase']=='saved':pass
                else:s['phase']='edit';s['doc']['reviewed']=False
                _checkpoint(s);reply(_status(s));return True
        allowed={'image':('edit','saved'),'reference':('edit','saved'),'generate':('edit',),'analyze':('edit',),
                 'interpret':('saved',),'apply':('proposal',),'save':('save_review',),'resume_project':('edit',),'recover':('uncertain',)}
        if s['phase'] not in allowed.get(action,()):reply([_text('現在の段階では使えない操作です。「確認」で続行してください。')]);return True
        if action=='generate' and not s.get('pending'):reply([_text('先に変更したい内容を送ってください。')]);return True
        if action in ('generate','analyze') and not s.get('doc'):reply(_status(s));return True
        if action=='interpret' and not s.get('pending'):reply([_text('変更内容を送ってください。')]);return True
        if event.get('webhookEventId'):s['seen']=(s['seen']+[event['webhookEventId']])[-50:]
        s['phase']='busy'
        try:_checkpoint(s)
        except Exception:reply([_text('操作を保管できなかったため実行しません。再開して状態を確認してください。')]);return True
        reply([_text('受け付けました。完了後にこの個人トークへ通知します。')])
        _spawn(lambda:_work(user,s,action,message,config))
        return True


def handle(event,config):
    try:return _handle(event,config)
    except Exception:
        from bot import main
        main.logger.exception('image workshop request failed')
        main.reply_messages(event.get('replyToken',''),[_text('画像制作の状態を保管できませんでした。実行結果が不明な場合は自動再試行せず、「確認」で現在の画像、保存した場合はアプリの一覧を確認してください。')],config.channel_access_token)
        return True
