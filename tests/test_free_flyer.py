import base64
from copy import deepcopy
import io
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image
from services import free_flyer as ff

P=ff.PREFIX+'a'*64+'.png'
Q=ff.PREFIX+'b'*64+'.png'


@pytest.fixture(autouse=True)
def no_thumbnail_writes(monkeypatch):
    monkeypatch.setattr(ff,'_store_thumbnail',Mock())


def png(color='red'):
    out=io.BytesIO();Image.new('RGB',(240,320),color).save(out,'PNG');return out.getvalue()


def document():
    d=ff.new_document(P,'Tour');d.update(fields=[dict(id='f1',label='日付',value='11/29(日)'),dict(id='f2',label='会場',value='Venue')],selected=['f1'],reviewed=True)
    return d


def test_edits_send_current_original_and_named_refs_once(monkeypatch):
    request=Mock(return_value=Mock(status_code=200,json=lambda:dict(data=[dict(b64_json=base64.b64encode(png()).decode())])))
    monkeypatch.setattr(ff.requests,'post',request)
    result=ff.edit(png('blue'),png(),'雰囲気を変える','key',references=[png('green')],reference_names=['ロゴ'])
    assert Image.open(io.BytesIO(result)).size==(240,320)
    request.assert_called_once()
    args=request.call_args.kwargs
    assert len(args['files'])==3 and args['data']['model']=='gpt-image-2' and args['data']['n']==1
    assert 'input_fidelity' not in args['data'] and args['allow_redirects'] is False
    assert 'immutable original' in args['data']['prompt'] and 'ロゴ' in args['data']['prompt']


def test_timeout_never_retried(monkeypatch):
    request=Mock(side_effect=ff.requests.Timeout());monkeypatch.setattr(ff.requests,'post',request)
    with pytest.raises(ValueError,match='自動再試行'):ff.edit(png(),png(),'変更','key')
    request.assert_called_once()


@pytest.mark.parametrize('payload',[dict(data=[]),dict(data=[dict(b64_json='not base64')])])
def test_invalid_image_response_is_not_a_project(monkeypatch,payload):
    monkeypatch.setattr(ff.requests,'post',Mock(return_value=Mock(status_code=200,json=lambda:payload)))
    with pytest.raises(ValueError):ff.edit(png(),png(),'変更','key')


def test_only_confirmed_fields_can_change():
    d=document()
    assert ff.replacements(d,{'f1':'12/5(土)'})[0]['before']=='11/29(日)'
    for requested in ({'f2':'Other'},{'f99':'Fake'},{'f1':''}):
        with pytest.raises(ValueError):ff.replacements(d,requested)
    d['reviewed']=False
    with pytest.raises(ValueError):ff.replacements(d,{'f1':'Other'})


def test_revision_keeps_original_and_prior_text():
    d=document();new=ff.revision(d,Q,'日付を変更',{'f1':'12/5(土)'})
    assert new['original']==P and new['current']==Q and not new['reviewed']
    assert new['history'][0]['fields'][0]['value']=='11/29(日)'
    assert d['current']==P and d['fields'][0]['value']=='11/29(日)'


def test_vision_only_returns_proposal_with_verbatim_values(monkeypatch):
    result=dict(title='Tour',fields=document()['fields'],fixed_note='ロゴと装飾は画像の一部')
    response=Mock(status_code=200,json=lambda:dict(choices=[dict(finish_reason='stop',message=dict(content=json.dumps(result)))]))
    call=Mock(return_value=response);monkeypatch.setattr(ff.requests,'post',call)
    assert ff.analyze(png(),'key')==result
    assert 'data:image/png;base64,' in call.call_args.kwargs['json']['messages'][1]['content'][0]['image_url']['url']
    result['fields'][0]['id']='../../file'
    with pytest.raises(ValueError):ff.analyze(png(),'key')


def test_natural_change_rejects_unapproved_field(monkeypatch):
    response=Mock(status_code=200,json=lambda:dict(choices=[dict(finish_reason='stop',message=dict(content=json.dumps(dict(changes={'f2':'Other'},question=''))))]))
    monkeypatch.setattr(ff.requests,'post',Mock(return_value=response))
    with pytest.raises(ValueError,match='編集可能'):ff.interpret_changes(document(),'会場変更','key')


@pytest.mark.parametrize('path',['https://evil.test/a.png','../a.png','free_flyer/images/bad.png'])
def test_blob_paths_are_not_arbitrary_network_or_storage_paths(path):
    d=document();d['current']=path
    with pytest.raises(ValueError):ff.validate(d)


def test_save_is_atomic_and_conflict_never_overwrites(monkeypatch):
    import database
    from repositories import project_repo,asset_repo
    from services import project_previews
    d=document();project=SimpleNamespace(id=55,flyer_json=json.dumps({ff.KEY:d}),title='Tour')
    db=Mock();db.bind.dialect.name='sqlite'
    db.query.return_value.filter.return_value.with_for_update.return_value.first.return_value=project
    db.query.return_value.filter.return_value.first.return_value=True
    monkeypatch.setattr(database,'SessionLocal',lambda:db)
    monkeypatch.setattr(ff,'get_image',lambda _:png())
    monkeypatch.setattr(project_previews,'prepare',lambda _:dict(images={},originals={}))
    changed=deepcopy(d);changed['title']='New'
    assert ff.save(changed,55,ff.fingerprint(d))==55
    db.commit.assert_called_once()
    assert json.loads(project.flyer_json)[ff.KEY]['original']==P
    db.commit.reset_mock()
    with pytest.raises(ValueError,match='別の操作'):ff.save(changed,55,'stale')
    db.commit.assert_not_called();db.rollback.assert_called_once()


def test_new_save_deduplicates_same_draft_key(monkeypatch):
    import database
    from services import project_previews
    d=document();project=SimpleNamespace(id=55,flyer_json=json.dumps({ff.KEY:d}))
    db=Mock();db.bind.dialect.name='sqlite';db.query.return_value.filter.return_value.all.return_value=[project]
    monkeypatch.setattr(database,'SessionLocal',lambda:db)
    monkeypatch.setattr(ff,'get_image',lambda _:png());monkeypatch.setattr(project_previews,'prepare',lambda _: {})
    assert ff.save(d)==55
    db.commit.assert_not_called()


def test_new_project_and_shared_assets_share_one_commit(monkeypatch):
    import database
    from repositories import project_repo,asset_repo
    from services import project_previews
    d=document();db=Mock();db.bind.dialect.name='sqlite'
    db.query.return_value.filter.return_value.all.return_value=[]
    db.query.return_value.filter.return_value.first.return_value=None
    monkeypatch.setattr(database,'SessionLocal',lambda:db)
    monkeypatch.setattr(ff,'get_image',lambda _:png());monkeypatch.setattr(project_previews,'prepare',lambda _: {})
    project=SimpleNamespace(id=55,flyer_json='{}',title='')
    stage=Mock(return_value=project);assets=Mock()
    monkeypatch.setattr(project_repo,'stage_new_draft',stage);monkeypatch.setattr(asset_repo,'add_image_asset',assets)
    assert ff.save(d)==55
    assert stage.call_args.args[1].flyer_settings[ff.KEY]['original']==P
    db.commit.assert_called_once();assert assets.call_count==2


def test_persistent_draft_owner_binding_and_expiry(monkeypatch):
    from services import free_flyer_store as store
    owner='a'*64;bucket=Mock();state=dict(owner=owner,phase='edit')
    monkeypatch.setattr(store,'_bucket',lambda:bucket)
    store.save(owner,state)
    raw=bucket.upload.call_args.kwargs['file'];bucket.download.return_value=raw
    assert store.load(owner)==state
    monkeypatch.setattr(store.time,'time',lambda:10**12)
    assert store.load(owner) is None
    bucket.remove.assert_not_called()
    with pytest.raises(ValueError):store.save('../other',state)


def test_history_archives_instead_of_losing_original(monkeypatch):
    d=document();d['history']=[dict(image=P,prompt='old',at='now',fields=[]) for _ in range(20)]
    archive=Mock(return_value='archive');monkeypatch.setattr(ff,'put_archive',archive)
    result=ff.revision(d,Q,'new')
    archive.assert_called_once();assert result['archives']==['archive'] and len(result['history'])==1 and result['original']==P


def test_analysis_cannot_replace_original_owner_or_project_paths(monkeypatch):
    result=dict(title='Tour',fields=document()['fields'],fixed_note='art',original=Q,owner='forged')
    response=Mock(status_code=200,json=lambda:dict(choices=[dict(finish_reason='stop',message=dict(content=json.dumps(result)))]))
    monkeypatch.setattr(ff.requests,'post',Mock(return_value=response))
    with pytest.raises(ValueError):ff.analyze(png(),'key')


def test_phone_photo_orientation_is_applied_once():
    output=io.BytesIO();im=Image.new('RGB',(320,240),'red')
    exif=Image.Exif();exif[274]=6;im.save(output,'JPEG',exif=exif)
    normalized=ff.image_bytes(output.getvalue())
    assert Image.open(io.BytesIO(normalized)).size==(240,320)
    assert Image.open(io.BytesIO(ff.image_bytes(normalized))).size==(240,320)
