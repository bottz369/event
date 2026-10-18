"""Reviewed AI production wizard. No writes until explicit new-project creation."""
from copy import deepcopy
import hashlib
import io
import json
import zipfile

import pandas as pd
import streamlit as st

from services import asset_service,artist_service,project_service,session_manager
from services import production_intake as intake,production_service as production,image_studio
from views.image_studio import _settings

STATE='auto_production_state'


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,default=str).encode()).hexdigest()


def bytes_hash(value):
    return hashlib.sha256(value).hexdigest() if value else ''


def _create(expected):
    state=st.session_state.get(STATE,{})
    package=state.get('package')
    if state.get('save_uncertain'):
        st.error('保存結果をプロジェクト一覧で確認してください。');return
    if not package or state.get('preview_hash')!=expected or state.get('project_id'):
        st.error('最新の完成プレビューを確認してください。');return
    # Resume asset registration on a recoverable failure, without recreating saved assets.
    for kind,key in (('background','bg_id'),('logo','logo_id')):
        data=package.get(kind)
        if data and kind not in package['asset_ids']:
            try:
                asset=asset_service.upload_image_asset(data,kind+'.png',kind,package['draft'].title+' '+('背景' if kind=='background' else 'ロゴ'))
                package['asset_ids'][kind]=asset.id
            except ValueError as exc:
                st.error(str(exc));return
        if kind in package['asset_ids']:package['draft'].flyer_settings[key]=package['asset_ids'][kind]
    try:
        new_id=production.persist_new_project(package['draft'],package['rows'])
    except ValueError as exc:
        # Unknown commit outcome must not trigger an automatic duplicate insert.
        state['save_uncertain']=True;st.session_state[STATE]=state
        st.error(str(exc));return
    state['project_id']=new_id;st.session_state[STATE]=state
    project_service.list_projects_for_selector.clear()
    if session_manager.reload_project(new_id):
        labels=dict(project_service.list_projects_for_selector())
        st.session_state['ws_project_selector_label']=labels.get(new_id,'(選択してください)')
        st.session_state['ws_active_tab']='📑 フライヤーセット'
        from PIL import Image
        from views.flyer import _flyer_preview_signature
        st.session_state.flyer_result_grid=Image.open(io.BytesIO(package['images']['grid'])).convert('RGBA')
        st.session_state.flyer_result_tt=Image.open(io.BytesIO(package['images']['tt'])).convert('RGBA')
        st.session_state.flyer_last_generated_params=_flyer_preview_signature()
        st.toast('新しいプロジェクトとフライヤーセットを保存しました。',icon='✅')
    else:
        st.warning('新規保存は完了しました。プロジェクト一覧から開いてください。')


def _asset_select(label,kind,key):
    assets=asset_service.list_assets_by_type(kind)
    labels={a.id:a.name for a in assets}
    return st.selectbox(label,[0]+list(labels),format_func=lambda i:labels.get(i,'指定なし'),key=key)


def _image_source(kind,prefix):
    label='背景' if kind=='background' else 'ロゴ'
    choices=['AIで新しく作る','アセットから選ぶ','画像をアップロード','指定なし'] if kind=='background' else ['標準ロゴを使う','アセットから選ぶ','画像をアップロード','イベント名をロゴにする']
    mode=st.selectbox(label+'の用意方法',choices,key=prefix+'_mode')
    asset_id=0;data=None
    if mode=='アセットから選ぶ':asset_id=_asset_select(label+'素材',kind,prefix+'_asset')
    elif mode=='画像をアップロード':
        upload=st.file_uploader(label+'画像',type=['png','jpg','jpeg','webp'],key=prefix+'_upload')
        data=upload.getvalue() if upload else None
    return dict(mode=mode,asset_id=asset_id,data=data)


def render():
    with st.expander('✨ AIおまかせ制作（新規プロジェクト）'):
        st.caption('概要＋PDF／Excel＋デザインの希望から、完成プレビューまで作ります。既存プロジェクトは上書きしません。')
        api_key,access_code=_settings()
        ready=bool(api_key and access_code)
        if not ready:st.info('AI接続設定後に利用できます。設定は素材作成機能と共通です。')
        overview=st.text_area('公演概要を貼り付け',key='autoprod_overview',height=180,max_chars=16000)
        document=st.file_uploader('タイムテーブル資料（PDF・.xlsx・CSV）',type=['pdf','xlsx','csv'],key='autoprod_document')
        st.caption('資料は10MB以下。文字を選択できるPDFは10ページ以内、Excelは6シート・各1000行×40列以内。旧.xls・画像だけのPDFには未対応です。')
        correction=st.text_area('不足情報・訂正（解析し直す時に追記）',key='autoprod_correction',max_chars=4000)
        code=st.text_input('AI制作の利用コード',type='password',key='autoprod_access',disabled=not ready)
        st.caption('「資料をAIで解析」で概要と資料の文字をOpenAIに送信します（API利用料が発生）。アー写の照合・時刻計算はアプリ内で行います。')
        source_hash=digest(dict(overview=overview,correction=correction,document=bytes_hash(document.getvalue()) if document else ''))
        if st.button('資料をAIで解析する',key='btn_autoprod_analyze',disabled=not ready or not overview.strip() or document is None):
            try:
                text=intake.extract_document(document.getvalue(),document.name)
                with st.spinner('概要とタイムテーブルを読み取っています…'):
                    result=intake.analyze(overview+'\n'+correction,text,api_key,access_code,code)
                old=st.session_state.get(STATE,{})
                st.session_state[STATE]=dict(result=result,source_hash=source_hash,revision=old.get('revision',0)+1)
            except ValueError as exc:st.error(str(exc))
        state=st.session_state.get(STATE)
        if not state:return
        if state.get('project_id'):
            st.success(f'プロジェクト #{state["project_id"]} を作成済みです。下の編集画面で調整できます。')
            if st.button('別の新規制作を始める',key='btn_autoprod_restart'):
                st.session_state.pop(STATE,None);st.rerun()
            return
        if state['source_hash']!=source_hash:
            st.warning('入力資料が変わりました。もう一度解析してから進めてください。');return
        result=state['result'];revision=state['revision'];prefix=f'autoprod_{revision}'
        st.subheader('① 読み取り内容を確認・修正')
        for item in result.get('questions',[]):st.warning('要確認：'+str(item))
        for item in result.get('warnings',[]):st.info(str(item))
        event=deepcopy(result['event'])
        for label,field in [('イベント名','event_name'),('サブタイトル','subtitle'),('開催日（YYYY-MM-DD）','event_date'),('会場名','venue'),('会場URL','venue_url')]:
            event[field]=st.text_input(label,value=str(event.get(field) or ''),key=prefix+'_'+field)
        event['tickets']=st.data_editor(pd.DataFrame(event.get('tickets',[]),columns=['name','price','note']),
            column_config={'name':'チケット名','price':'料金','note':'備考'},num_rows='dynamic',hide_index=True,key=prefix+'_tickets').fillna('').to_dict('records')
        event['ticket_common_note']=st.text_area('料金の共通備考',value=event.get('ticket_common_note',''),key=prefix+'_ticket_note')
        event['free_viewing']=st.checkbox('観覧無料を表示する',value=bool(event.get('free_viewing')),key=prefix+'_free')
        event['free_text']=st.text_input('観覧無料の補足',value=event.get('free_text',''),key=prefix+'_free_text')
        event['free_notices']=st.text_area('観覧無料の下の注意書き',value=event.get('free_notices',''),key=prefix+'_notices')
        with st.expander('入場・注意事項の読み取り内容'):
            for i,entry in enumerate(event.get('free_texts',[])):
                entry['title']=st.text_input('見出し',value=entry.get('title',''),key=f'{prefix}_notice_title_{i}')
                entry['body']=st.text_area('内容',value=entry.get('body',''),key=f'{prefix}_notice_body_{i}')
        parts=[]
        for index,raw in enumerate(result['parts']):
            if not st.checkbox((raw.get('name') or f'{index+1}部')+'を制作対象にする',value=True,key=f'{prefix}_part_{index}'):
                continue
            with st.expander(raw.get('name') or f'{index+1}部',expanded=True):
                part=deepcopy(raw)
                for label,field in [('部の名前','name'),('OPEN（HH:MM）','open_time'),('START（HH:MM）','start_time'),('終演後物販の開始','post_start'),('終演後物販の終了','post_end')]:
                    part[field]=st.text_input(label,value=str(part.get(field) or ''),key=f'{prefix}_part_{index}_{field}')
                frame=pd.DataFrame(part.get('rows',[]))
                if not frame.empty:
                    frame=frame.drop(columns=['evidence'],errors='ignore')
                    part['rows']=st.data_editor(frame,hide_index=True,height='content',key=f'{prefix}_part_{index}_rows',
                        column_config={'artist':'アーティスト','start':'出演開始','end':'出演終了','goods_start':'物販開始','goods_end':'物販終了',
                            'place':'場所','post_goods':st.column_config.CheckboxColumn('終演後'),'add_start':'追加開始','add_end':'追加終了','add_place':'追加場所'}).fillna('').to_dict('records')
                else:st.error('出演者行を読み取れませんでした。資料を確認して解析し直してください。')
                parts.append(part)
        if not parts:st.warning('制作対象の部を1つ以上選んでください。')
        st.caption('1部だけなら通常イベント、2部以上なら複数部イベントとして作成します。')
        performance_names=[str(r.get('artist') or '') for p in parts for r in p.get('rows',[]) if r.get('artist')]
        names=list(dict.fromkeys(performance_names+[str(n) for n in event.get('artists',[]) if n]))
        registered=[a.name for a in artist_service.list_artists()]
        aliases=production.match_names(names,registered)
        for name in names:
            if name not in aliases:
                choice=st.selectbox('登録名を確認：'+name,['原文のまま（アー写未登録の枠）']+registered,key=f'{prefix}_alias_'+digest(name)[:12])
                if choice!='原文のまま（アー写未登録の枠）':aliases[name]=choice
        show_transitions=st.checkbox('転換を画像に表示する',value=False,key=prefix+'_transitions')
        confirmed=st.checkbox('日付・料金・出演順・時刻・名前の確認事項を確認しました',key=prefix+'_confirmed')
        st.subheader('② フライヤーのイメージ')
        design=st.text_area('希望するデザイン',key='autoprod_design',max_chars=2000,placeholder='赤いお祭り風。ロゴは金色。提灯と花火を周囲に。')
        palette=st.selectbox('背景の色合い',['指示に合わせる','赤・朱色・金','青・紺・金','黒・金','ピンク・紫'],key='autoprod_palette')
        bg=_image_source('background',prefix+'_bg')
        reference=st.file_uploader('背景の参考画像（AI生成時・任意）',type=['png','jpg','jpeg','webp'],key=prefix+'_reference') if bg['mode']=='AIで新しく作る' else None
        logo=_image_source('logo',prefix+'_logo')
        st.caption('標準ロゴは登録済みのBASICを使用します。背景の希望とロゴの選択・色は別々に指定できます。')
        logo_tint=st.selectbox('ロゴの色',['元の色','背景に合わせる',*image_studio.PALETTES],key=prefix+'_logo_tint')
        current=digest(dict(event=event,parts=parts,aliases=aliases,transitions=show_transitions,design=design,palette=palette,
            bg={**bg,'data':bytes_hash(bg['data'])},logo={**logo,'data':bytes_hash(logo['data'])},tint=logo_tint,
            reference=bytes_hash(reference.getvalue()) if reference else ''))
        can_preview=bool(parts and confirmed and (design.strip() or bg['mode']!='AIで新しく作る'))
        if st.button('完成フライヤーセットのプレビューを作る',key='btn_autoprod_preview',disabled=not can_preview):
            try:
                draft,rows=production.compile_plan(event,parts,aliases,show_transitions)
                with st.spinner('素材を用意して、フライヤーセットを作っています…'):
                    bg_data=bg['data']
                    if bg['mode']=='アセットから選ぶ':
                        if not bg['asset_id']:raise ValueError('背景素材を選択してください。')
                        bg_data=asset_service.read_image_asset(bg['asset_id'])
                    elif bg['mode']=='画像をアップロード' and not bg_data:raise ValueError('背景画像を選択してください。')
                    elif bg['mode']=='AIで新しく作る':
                        bg_hash=digest(dict(design=design,palette=palette,reference=bytes_hash(reference.getvalue()) if reference else ''))
                        if state.get('bg_hash')==bg_hash:bg_data=state['bg_data']
                        else:
                            bg_data=image_studio.generate_background(design,palette,api_key,access_code,code,reference.getvalue() if reference else None)
                            state.update(bg_hash=bg_hash,bg_data=bg_data)
                    logo_data=logo['data']
                    if logo['mode']=='標準ロゴを使う':
                        logo_data=production.read_default_logo()
                    elif logo['mode']=='アセットから選ぶ':
                        if not logo['asset_id']:raise ValueError('ロゴ素材を選択してください。')
                        logo_data=asset_service.read_image_asset(logo['asset_id'])
                    elif logo['mode']=='画像をアップロード' and not logo_data:raise ValueError('ロゴ画像を選択してください。')
                    if not logo_data:
                        from services import font_service
                        logo_data=image_studio.png(production.title_logo(draft.title,font_service.ensure_font_path('keifont.ttf')))
                    if logo_tint!='元の色':
                        color=image_studio.PALETTES.get(logo_tint)
                        if logo_tint=='背景に合わせる':color=image_studio.PALETTES['ゴールド'] if '赤' in palette or '金' in palette else image_studio.PALETTES['シルバー']
                        logo_data=image_studio.recolor(logo_data,color)
                    package=production.render_package(draft,rows,bg_data,logo_data)
                state.update(package=package,preview_hash=current);st.session_state[STATE]=state
            except ValueError as exc:st.error(str(exc))
        st.caption('AI背景を選んだ場合は画像生成の利用料が発生します。同じ背景条件のプレビュー作り直しは、作成済みの背景を再利用します。')
        package=state.get('package')
        if not package:return
        st.subheader('③ 完成プレビュー')
        stale=state.get('preview_hash')!=current
        if stale:st.warning('内容が変わっています。プレビューを作り直してから保存してください。')
        for failure in package.get('failures',[]):
            if failure.get('name'):st.warning('アー写を確認：'+failure['name'])
        grid_tab,tt_tab,text_tab=st.tabs(['アー写グリッド版','タイムテーブル版','概要テキスト'])
        for tab,variant in ((grid_tab,'grid'),(tt_tab,'tt')):
            with tab:st.image(package['images'][variant],width='stretch')
        with text_tab:st.text(package['text'])
        archive=io.BytesIO()
        with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
            for variant,data in package['images'].items():z.writestr(variant+'.png',data)
            z.writestr('event.txt',package['text'])
        st.download_button('完成セットをダウンロード',archive.getvalue(),file_name='flyer-set.zip',mime='application/zip',key='dl_autoprod_set',disabled=stale)
        unsaved=session_manager.has_unsaved_changes()
        if unsaved:st.warning('編集中のプロジェクトに未保存の変更があります。上部で保存してから新規制作を保存してください。')
        st.caption('次のボタンで素材をアセットに保存し、新しいプロジェクトを作成します。既存イベントは変更しません。')
        if state.get('save_uncertain'):st.error('前回の保存結果を一覧で確認してください。重複防止のため、この画面から再作成しません。')
        st.button('新規プロジェクトとして保存して編集画面を開く',key='btn_autoprod_create',on_click=_create,
                  args=(current,),disabled=stale or not confirmed or unsaved or bool(state.get('save_uncertain')))
