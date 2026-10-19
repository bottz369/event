"""Owner-DM production wizard. Existing services own parsing, rendering and persistence.

Drafts are process-local, bounded, expiring and isolated by authenticated LINE user.
No DB writes before an explicit, versioned save action; no automatic paid retries.
"""
from dataclasses import dataclass,field
import hashlib
import os
import re
import threading
import time
import uuid

import requests

TTL=7200
LOCK=threading.RLock()
SESSIONS={}
SEEN={}
START='AIおまかせ制作'
UPDATE_STARTS=('プロジェクト更新','AIおまかせ更新','既存プロジェクトを更新')
HELP=('公演概要を送信し、PDF・Excel（.xlsx）・CSVをファイル添付してください。\n'
      '「デザイン: 青と紫の放射状の光」のように希望を送れます。指定しなければ標準テンプレートの背景・ロゴを使います。\nロゴの色は「ロゴ色: 背景に合わせる」などで指定できます。\n'
      '「背景画像を送る」「ロゴ画像を送る」の後に画像を送るとその素材を使います。\n'
      '構図の参考だけに使う画像は「背景参考画像を送る」の後に送信してください。\n'
      '概要・資料が揃ったら「資料をAIで解析」ボタンを押してください（OpenAIへ送信・API料金が発生）。\n'
      '長い処理の完了は個人トークへ通知します。「確認」で再表示、「中止」で終了できます。\n'
      '下書きは2時間・サーバー再起動まで保持。保存までは新規プロジェクトを作りません。')


@dataclass
class Session:
    token:str=field(default_factory=lambda:uuid.uuid4().hex[:16])
    revision:int=0
    touched:float=field(default_factory=time.time)
    stage:str='collect'
    busy:bool=False
    overview:str=''
    document:str=''
    design:str=''
    correction:str=''
    image_target:str=''
    background:bytes=None
    logo:bytes=None
    logo_tint:str='元の色'
    reference:bytes=None
    logo_cache:dict=field(default_factory=dict)
    bg_cache:dict=field(default_factory=dict)
    result:dict=None
    selected:list=None
    aliases:dict=field(default_factory=dict)
    package:dict=None
    project_id:int=None
    uncertain:bool=False
    target_id:int=None
    baseline:dict=None
    targets:list=field(default_factory=list)
    target_page:int=0
    target_more:bool=False
    document_name:str=''


def _transport():
    from bot import main
    return main


def _spawn(work):
    thread=threading.Thread(target=work,daemon=True);thread.start();return thread


def _credentials():
    key=os.environ.get('OPENAI_API_KEY','')
    if not key:raise ValueError('BotサーバーのOPENAI_API_KEYが未設定です。管理者に設定を依頼してください。')
    # The verified owner-DM gate is the access control here; never request a key in chat.
    return key,'owner-dm','owner-dm'


def _push(user,messages,config):
    for i in range(0,len(messages),5):
        try:
            response=requests.post('https://api.line.me/v2/bot/message/push',
                headers={'Authorization':'Bearer '+config.channel_access_token,
                         'X-Line-Retry-Key':str(uuid.uuid4())},
                json={'to':user,'messages':messages[i:i+5]},timeout=(10,30))
            if response.status_code!=200:return False
        except requests.RequestException:return False
    return True


def _text(text):return dict(type='text',text=text)


def _button(s,label,action):
    return dict(type='action',action=dict(type='postback',label=label,
        data=f'aip|{s.token}|{s.revision}|{action}',displayText=label))


def _controls(s,text,actions):
    return {**_text(text),'quickReply':dict(items=[_button(s,label,action) for label,action in actions])}


def _chunks(text):return [_text(text[i:i+4500]) for i in range(0,len(text),4500)]


def _review(s):
    e=s.result['event'];parts=s.result['parts']
    lines=[f"{e.get('event_name','')} {e.get('subtitle','')}",f"{e.get('event_date','')} ／ {e.get('venue','')}",'■料金']
    lines += [f"{t['name']} {t['price']} {t['note']}" for t in e.get('tickets',[])]
    lines += [e.get('ticket_common_note',''),'■グリッド掲載順',' → '.join(e.get('artists',[]))]
    if e.get('free_viewing'):lines += ['■観覧無料',e.get('free_text',''),e.get('free_notices','')]
    for i,p in enumerate(parts):
        chosen=s.selected is None or i in s.selected
        lines += [f"■{i+1}: {p['name']} {'【対象】' if chosen else '【除外】'} OPEN {p['open_time']} / START {p['start_time']}"]
        for r in p['rows']:
            goods='終演後物販' if r['post_goods'] else f"{r['goods_start']}〜{r['goods_end']}"
            lines += [f"{r['start']}〜{r['end']} {r['artist']} ／ {goods} ({r['place']})"
                      + (f" ／追加 {r['add_start']}〜{r['add_end']} ({r['add_place']})" if r['add_start'] else '')]
        if p['post_start']:lines += [f"終演後物販 {p['post_start']}〜{p['post_end']}"]
    for entry in e.get('free_texts',[]):lines += [entry['title'],entry['body']]
    lines += ['■デザイン',s.design or ('現在の背景・ロゴを引き継ぐ' if s.target_id else ('アップロードした背景' if s.background else '標準テンプレートの背景・ロゴ')), 'ロゴ色：'+s.logo_tint]
    lines += ['■要確認']+s.result.get('questions',[])+s.result.get('warnings',[])
    if s.target_id:
        old=s.baseline['draft']
        lines=[f'■更新先 #{s.target_id} {old.title} - {old.subtitle}',
               '新しい概要・資料で更新します。既存のデザイン・comingsoon設定は引き継ぎます。',
               'まだ保存していません。完成プレビューの確認後に更新を確定してください。']+lines
    if s.document_name:lines.insert(0,'■資料 '+s.document_name)
    return '\n'.join(lines)


def _preview_messages(s):
    main=_transport();messages=[]
    for variant,data in s.package['images'].items():
        name='ai_'+s.token+'_'+str(s.revision)+'_'+variant
        original=main.upload_generated_png(data,0,name)
        thumbnail=main.upload_generated_png(main.build_preview_png(data),0,name+'_preview')
        if not original or not thumbnail:raise ValueError('完成画像を配信できませんでした。「確認」で再表示してください。画像生成は再実行しません。')
        messages.append(main.build_image_message(original,thumbnail))
    failures=[f.get('name','') for f in s.package.get('failures',[]) if f.get('name')]
    if failures:messages+=_chunks('アー写を確認：'+'、'.join(dict.fromkeys(failures)))
    label='このプロジェクトを更新' if s.target_id else '保存する'
    text=(f'完成プレビューです。「{label}」でプロジェクト #{s.target_id} の概要・タイムテーブル・完成画像を更新します。'
          if s.target_id else '完成プレビューです。「保存する」で新規プロジェクトと素材を保存します。')
    messages.append(_controls(s,text+'\n修正は「訂正: …」、デザインの変更は「デザイン: …」。修正後は再確認が必要です。', [(label,'save')]))
    return messages


def _status(s):
    if s.busy:return [_text('処理中です。完了後に通知します。')]
    if s.stage=='choose':return _project_choices_message(s)
    if s.project_id:return [_text(f'プロジェクト #{s.project_id} '+('を更新しました。' if s.target_id else 'に保存済みです。')+'アプリの一覧からも確認・編集できます。')]
    if s.uncertain:return [_text('保存結果をアプリの一覧で確認してください。重複防止のため、この下書きは再保存できません。')]
    if s.stage=='preview':return _preview_messages(s)
    if s.stage=='review':
        messages=_chunks(_review(s))
        messages.append(_controls(s,'日付・料金・出演順・時刻・名前を確認してください（※必須）。\n'
            '「確認して生成」で確認済みとして完成画像を作ります。AI背景・AIロゴ配色の場合は追加API料金が発生します。\n'
            '修正：「訂正: OPENは10:20」／部の選択：「部数: 1,3」／登録名：「名寄せ: 原文名=>登録名」',
            [('確認して生成','preview')]))
        return messages
    missing=[]
    if not s.overview:missing.append('公演概要')
    if not s.document:missing.append('タイムテーブル資料')
    target=(f"更新先 #{s.target_id}：{s.baseline['draft'].title} - {s.baseline['draft'].subtitle}\n既存の背景・ロゴ・デザインを使います。新しい概要とPDF・Excel（.xlsx）・CSVを送ってください。\n" if s.target_id else '')
    received=('受領資料：'+s.document_name+'\n') if s.document_name else ''
    help_text=HELP
    if s.target_id:
        help_text=help_text.replace('指定しなければ標準テンプレートの背景・ロゴを使います。','指定しなければ現在の背景・ロゴを引き継ぎます。').replace('保存までは新規プロジェクトを作りません。','更新を確定するまで保存済みプロジェクトは変更しません。')
    return [_controls(s,target+received+'受け取り待ち：'+('、'.join(missing) or 'なし')+'\n'+help_text,[('資料をAIで解析','analyze')])]


def _load_projects(s,page=0):
    from services import event_service
    targets,more=event_service.list_recent_events(limit=10,page=page)
    s.targets=targets;s.target_page=page;s.target_more=more


def _project_choices_message(s):
    actions=[];lines=['更新する既存プロジェクトを選んでください。ID・開催日を確認してください。']
    for target in s.targets:
        date=target.event_date.isoformat() if target.event_date else '日付未定'
        title=f'#{target.project_id} {date} {str(target.title)[:160]}'
        lines.append(title)
        actions.append((title if len(title)<=20 else title[:19]+'…',f'target:{target.project_id}'))
    if s.target_page:actions.append(('前のページ',f'projects:{s.target_page-1}'))
    if s.target_more:actions.append(('次のページ',f'projects:{s.target_page+1}'))
    if not s.targets:lines.append('該当するプロジェクトがありません。')
    return [_controls(s,'\n'.join(lines)+'\n「中止」で終了できます。',actions)]


def _download(message,config,limit):
    mid=message.get('id','')
    if not re.fullmatch(r'[0-9A-Za-z_-]{1,128}',mid):raise ValueError('添付ファイルを取得できませんでした。送り直してください。')
    if message.get('fileSize',0)>limit:raise ValueError('資料は10MB、画像は20MB以下で送信してください。')
    try:
        with requests.get(f'https://api-data.line.me/v2/bot/message/{mid}/content',
                headers={'Authorization':'Bearer '+config.channel_access_token},stream=True,timeout=(10,30),allow_redirects=False) as response:
            response.raise_for_status();data=bytearray()
            for chunk in response.iter_content(65536):
                data.extend(chunk)
                if len(data)>limit:raise ValueError('添付ファイルのサイズ上限を超えました。')
        return bytes(data)
    except requests.RequestException as exc:raise ValueError('添付ファイルを取得できませんでした。送り直してください。') from exc


def _invalidate(s,parsed=False):
    s.revision+=1;s.package=None
    s.stage='review' if parsed and s.result else 'collect'


def _analyze(s):
    from services import production_intake as intake
    if not s.overview or not s.document:raise ValueError('公演概要とタイムテーブル資料を送ってください。')
    s.result=intake.analyze(s.overview+'\n'+s.correction,s.document,*_credentials())
    s.stage='review';s.package=None;s.selected=None


def _render(s):
    from services import production_service as production,artist_service,image_studio,template_service
    from services.production_templates import decode,META
    parts=[p for i,p in enumerate(s.result['parts']) if s.selected is None or i in s.selected]
    names=list(dict.fromkeys([r['artist'] for p in parts for r in p['rows']]+s.result['event']['artists']))
    aliases=production.match_names(names,[a.name for a in artist_service.list_artists()]);aliases.update(s.aliases)
    draft,rows=production.compile_plan(s.result['event'],parts,aliases)
    if s.target_id:
        from services import production_update
        production_update.ensure_current(s.target_id,s.baseline['revision'])
        draft,rows=production_update.merge_plan(s.baseline['draft'],s.baseline['rows'],draft,rows)
    template=None
    for item in ([] if s.target_id else template_service.list_templates()):
        try:value=decode(item.data_json)
        except ValueError:continue
        if value[META].get('default'):template=value;break
    if s.target_id:
        from services.production_templates import capture
        template=capture(s.baseline['draft'])
    # Default templates affect appearance; explicitly requested materials override their assets.
    bg=s.background
    reused={}
    materials=s.baseline['draft'].flyer_settings if s.target_id else (template or {})
    if not bg and not s.design:
        from services import asset_service
        asset_id=materials.get('bg_id')
        if asset_id:
            bg=asset_service.read_image_asset(asset_id);reused['background']=asset_id
        elif not s.target_id:
            raise ValueError('標準テンプレートに背景がありません。「デザイン: …」か背景画像を送るか、アプリで背景入りの標準テンプレートを保存してください。')
    if not bg and s.design:
        fingerprint=hashlib.sha256(s.design.encode()+(s.reference or b'')).hexdigest()
        if s.bg_cache.get('hash')==fingerprint:bg=s.bg_cache['data']
        else:
            bg=image_studio.generate_background(s.design,'指示に合わせる',*_credentials(),reference=s.reference)
            s.bg_cache=dict(hash=fingerprint,data=bg)
    logo=s.logo
    if not logo:
        from services import asset_service
        asset_id=materials.get('logo_id')
        if asset_id:
            logo=asset_service.read_image_asset(asset_id)
            if s.logo_tint=='元の色':reused['logo']=asset_id
        elif not s.target_id:logo=production.read_default_logo()
    if s.logo_tint!='元の色' and not logo:raise ValueError('配色するロゴ画像を送ってください。')
    if s.logo_tint=='背景に合わせる':
        if not bg:raise ValueError('配色に使う背景画像を送ってください。')
        from services.logo_palette import match_logo
        fingerprint=hashlib.sha256(logo+bg).hexdigest()
        if s.logo_cache.get('hash')==fingerprint:logo=s.logo_cache['data']
        else:
            logo=match_logo(logo,bg,*_credentials())['data']
            s.logo_cache=dict(hash=fingerprint,data=logo)
    elif s.logo_tint!='元の色':logo=image_studio.recolor(logo,image_studio.PALETTES[s.logo_tint])
    s.package=production.render_package(draft,rows,bg,logo,template=template)
    s.package['asset_ids'].update(reused)
    s.stage='preview'


def _save(s):
    from services import production_service as production,asset_service
    if s.project_id or s.uncertain:raise ValueError('保存済み、または保存結果の確認待ちです。アプリの一覧を確認してください。')
    package=s.package
    if s.target_id:
        from services import production_update
        if package['draft'].id!=s.target_id:raise ValueError('更新先が一致しません。プロジェクトを選び直してください。')
        production_update.ensure_current(s.target_id,s.baseline['revision'])
    for kind,key in (('background','bg_id'),('logo','logo_id')):
        data=package.get(kind)
        if data and kind not in package['asset_ids']:
            asset=asset_service.upload_image_asset(data,kind+'.png',kind,package['draft'].title+' '+kind)
            package['asset_ids'][kind]=asset.id
        if kind in package['asset_ids']:package['draft'].flyer_settings[key]=package['asset_ids'][kind]
    s.uncertain=True  # Set BEFORE inserting, including an unknown network outcome.
    from services.project_previews import OutputStorageError
    try:
        if s.target_id:
            s.project_id=production_update.persist_update(package['draft'],package['rows'],package['images'],s.baseline['revision'])
        else:
            s.project_id=production.persist_new_project(package['draft'],package['rows'],images=package['images'])
    except OutputStorageError:
        s.uncertain=False
        raise
    except Exception as exc:
        from services.production_update import ProjectChanged
        if isinstance(exc,ProjectChanged):s.uncertain=False
        raise
    s.uncertain=False;s.stage='saved'


def _run(user,s,config,action,message=None):
    try:
        if action=='target':
            from services import production_update
            baseline=production_update.load_target(int(message['project_id']))
            s.target_id=baseline['draft'].id;s.baseline=baseline;s.revision+=1;s.stage='collect'
        elif action=='analyze':_analyze(s)
        elif action=='preview':_render(s)
        elif action=='save':_save(s)
        elif action=='file':
            from services.production_intake import extract_document
            text=extract_document(_download(message,config,10*1024*1024),message['fileName'])
            s.document=text;s.document_name=str(message['fileName'])[:200];s.result=None;s.selected=None;_invalidate(s)
        elif action=='image':
            from services.image_studio import open_image,png
            data=png(open_image(_download(message,config,20*1024*1024)))
            setattr(s,s.image_target,data);s.image_target='';_invalidate(s,parsed=True)
        with LOCK:s.busy=False;s.touched=time.time()
        _push(user,_status(s),config)
    except Exception as exc:
        with LOCK:s.busy=False;s.touched=time.time()
        # Never expose transport bodies, credentials or internal exceptions to LINE.
        error=str(exc) if isinstance(exc,ValueError) else '処理を完了できませんでした。「確認」で状態を確認してください。'
        if action=='preview':
            error+='\n生成を停止しました。解析結果と作成済み背景はこの下書きに保持しています。「確認」で内容を表示できます。'
        _push(user,[_text(error)],config)


def handle(event,config):
    """Return True only for a private AI-production conversation owned by this sender."""
    source=event.get('source') or {};user=source.get('userId')
    if source.get('type')!='user' or not user or user not in config.owner_user_ids:return False
    message=event.get('message') or {};text=str(message.get('text','')).strip()
    data=str((event.get('postback') or {}).get('data',''))
    trigger=event.get('type')=='message' and message.get('type')=='text' and text in (START,)+UPDATE_STARTS
    with LOCK:
        now=time.time()
        for uid,state in list(SESSIONS.items()):
            if not state.busy and now-state.touched>TTL:SESSIONS.pop(uid)
        for key,stamp in list(SEEN.items()):
            if now-stamp>TTL:SEEN.pop(key)
        s=SESSIONS.get(user)
        if not (trigger or s or data.startswith('aip|')):return False
        # Only AI postbacks belong here. Ordinary bot buttons continue to work.
        if event.get('type')=='postback' and not data.startswith('aip|'):return False
        event_id=event.get('webhookEventId') or message.get('id') or event.get('replyToken')
        unique=(user,event_id)
        if event_id and unique in SEEN:return True
        if len(SEEN)>=4096:SEEN.pop(next(iter(SEEN)))
        if event_id:SEEN[unique]=now
        reply=event.get('replyToken','')
        main=_transport()
        def respond(messages):
            # LINE reply accepts at most five; longer review is sent in private push batches.
            if len(messages)<=5:main.reply_messages(reply,messages,config.channel_access_token)
            else:
                main.reply_text(reply,'読み取り結果を個人トークへ送ります。',config.channel_access_token)
                _spawn(lambda:_push(user,messages,config))
        if s and s.busy:
            respond([_text('処理中です。完了までお待ちください。')]);return True
        if trigger:
            if s and not s.project_id:
                respond([_text('進行中の制作があります。「確認」で続行、「中止」で終了してから新しく始めてください。')]);return True
            if len(SESSIONS)>=4 and user not in SESSIONS:
                respond([_text('制作処理が混み合っています。時間をおいてお試しください。')]);return True
            s=Session();SESSIONS[user]=s
            if text in UPDATE_STARTS:
                try:_load_projects(s)
                except Exception:
                    SESSIONS.pop(user,None);respond([_text('プロジェクト一覧を取得できませんでした。少し待って再度お試しください。')]);return True
                s.stage='choose'
            respond(_status(s));return True
        if not s:
            respond([_text('制作下書きの期限が切れたか、Botが再起動しました。「AIおまかせ制作」または「プロジェクト更新」から始めてください。保存済みのプロジェクトは残ります。')]);return True
        s.touched=now
        if s.uncertain:
            respond(_status(s));return True
        if text=='中止':
            SESSIONS.pop(user);respond([_text('AI制作を終了しました。保存済みプロジェクトと元の素材は変更していません。')]);return True
        if s.project_id:
            respond(_status(s));return True
        if text=='確認':
            # image publishing may take time, so never hold the webhook for it.
            if s.stage=='preview':action='status'
            else:respond(_status(s));return True
        elif event.get('type')=='postback':
            match=re.fullmatch(r'aip\|([0-9a-f]{16})\|(\d{1,6})\|(analyze|preview|save|target:\d{1,12}|projects:\d{1,6})',data)
            if not match or match[1]!=s.token or int(match[2])!=s.revision:
                respond([_text('古い確認ボタンです。「確認」で現在の内容を表示してください。')]);return True
            action=match[3]
            if action.startswith('projects:') and s.stage=='choose':
                try:_load_projects(s,int(action.split(':')[1]))
                except Exception:
                    respond([_text('プロジェクト一覧を取得できませんでした。再度お試しください。')]);return True
                s.revision+=1;respond(_status(s));return True
            if action.startswith('target:') and s.stage=='choose':
                pid=int(action.split(':')[1])
                if pid not in [target.project_id for target in s.targets]:
                    respond([_text('現在表示されている一覧から選んでください。')]);return True
                message={'project_id':pid};action='target'
            if s.stage!=dict(analyze='collect',preview='review',save='preview',target='choose').get(action):
                respond([_text('この操作は処理済みか、現在の段階では使えません。「確認」で続行してください。')]);return True
        elif s.stage=='choose':
            respond(_status(s));return True
        elif message.get('type')=='file':
            filename=str(message.get('fileName',''))
            ext=filename.rsplit('.',1)[-1].lower()
            if s.image_target and ext in ('png','jpg','jpeg','webp'):
                action='image'
            elif ext not in ('pdf','xlsx','csv'):
                respond([_text('PDF・.xlsx・CSVをファイルとして送信してください。')]);return True
            else:action='file'
        elif message.get('type')=='image':
            if s.image_target not in ('background','logo','reference'):
                respond([_text('先に「背景画像を送る」または「ロゴ画像を送る」と送信してください。')]);return True
            action='image'
        elif message.get('type')=='text':
            if s.project_id:respond(_status(s));return True
            if text in ('背景画像を送る','ロゴ画像を送る','背景参考画像を送る'):
                s.image_target={'背景画像を送る':'background','ロゴ画像を送る':'logo','背景参考画像を送る':'reference'}[text]
                respond([_text('次に画像を送ってください。透過ロゴはPNGを「ファイル」として送ると透過を保てます。')]);return True
            command=re.match(r'^(デザイン|ロゴ色|訂正|部数|名寄せ|概要)[：:]\s*(.*)',text,re.S)
            if command:
                label,value=command.groups()
                if label=='デザイン' and 1<=len(value)<=2000:
                    s.design=value;s.background=None;_invalidate(s,parsed=True)
                elif label=='ロゴ色' and value in ('元の色','背景に合わせる','ゴールド','アイボリー','シルバー','ブルー','レッド'):
                    s.logo_tint=value;_invalidate(s,parsed=True)
                elif label=='概要' and 1<=len(value)<=16000:
                    s.overview=value;s.result=None;_invalidate(s)
                elif label=='訂正' and 1<=len(value)<=4000:
                    s.correction=value;_invalidate(s)
                elif label=='部数' and s.result:
                    indices=[int(v)-1 for v in re.findall(r'\d+',value)]
                    if not indices or any(i<0 or i>=len(s.result['parts']) for i in indices):
                        respond([_text('表示された部の番号を「部数: 1,3」のように指定してください。')]);return True
                    s.selected=sorted(set(indices));_invalidate(s,parsed=True)
                elif label=='名寄せ' and s.result and '=>' in value:
                    original,registered=[v.strip() for v in value.split('=>',1)]
                    from services import artist_service
                    if registered not in [a.name for a in artist_service.list_artists()]:
                        respond([_text('その登録名が見つかりません。アーティスト管理の正式名で指定してください。')]);return True
                    s.aliases[original]=registered;_invalidate(s,parsed=True)
                else:
                    respond([_text('入力の長さ・形式を確認してください。概要16000文字、デザイン2000文字、訂正4000文字以内です。')]);return True
            elif not s.overview and 1<=len(text)<=16000:s.overview=text;_invalidate(s)
            else:
                respond([_text('「概要: …」「デザイン: …」「訂正: …」「部数: 1,2」「確認」「中止」を使えます。')]);return True
            respond(_status(s));return True
        else:
            respond([_text('公演概要のテキスト、PDF・Excel・CSV、または素材画像を送信してください。')]);return True
        s.busy=True
        main.reply_text(reply,'受け付けました。完了後にこの個人トークへ通知します。',config.channel_access_token)
        _spawn(lambda:_run(user,s,config,action,message))
        return True
