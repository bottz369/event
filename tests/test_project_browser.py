"""Project identity, cross-process refresh, preview persistence and read-only browse."""
import base64
import io
import json
from types import SimpleNamespace
from unittest.mock import Mock

from PIL import Image, ImageChops
from services import project_previews as previews, project_service as projects


def test_same_labels_are_distinct_and_preserve_ids(monkeypatch):
    db=Mock();monkeypatch.setattr(projects,'SessionLocal',lambda:db)
    monkeypatch.setattr(projects.project_repo,'list_projects',lambda db:[
        SimpleNamespace(id=i,title='Same',subtitle='Same',event_date='2026-11-21') for i in (48,49)])
    result=projects.list_projects_for_selector.__wrapped__()
    assert result==[(48,'2026-11-21 Same - Same [#48]'),(49,'2026-11-21 Same - Same [#49]')]
    assert len(dict((label,pid) for pid,label in result))==2
    db.commit.assert_not_called()


def test_snapshot_is_small_watermarked_and_never_mutates_export():
    source=Image.new('RGBA',(1080,1350),'navy');before=source.copy()
    saved=previews.snapshot({'grid':source,'tt':source})
    decoded=previews.decode({previews.KEY:saved})
    assert set(decoded)=={'grid','tt'}
    image=Image.open(io.BytesIO(decoded['grid']))
    assert image.size==(240,300) and len(decoded['grid'])<40000
    assert ImageChops.difference(source,before).getbbox() is None
    # Watermark produces white lettering in the middle of a solid navy source.
    assert max(image.convert('L').crop((0,150,240,180)).getdata())>150
    assert previews.decode('{}')=={} and previews.decode('bad json')=={}
    assert previews.decode({previews.KEY:dict(images={'grid':'invalid'})})=={}


def test_thumbnail_save_merges_only_metadata_and_closes_session(monkeypatch):
    import database
    from repositories import project_repo
    row=SimpleNamespace(flyer_json=json.dumps({'logo_scale':1.17,'_other':{'a':1}}))
    db=Mock();monkeypatch.setattr(database,'SessionLocal',lambda:db)
    monkeypatch.setattr(database,'upload_image_to_supabase',lambda data,name:name)
    monkeypatch.setattr(project_repo,'get_project',lambda db,pid:row if pid==49 else None)
    saved=previews.save(49,{k:Image.new('RGB',(1080,1350),'navy') for k in ('grid','tt')})
    data=json.loads(row.flyer_json)
    assert data['logo_scale']==1.17 and data['_other']=={'a':1}
    assert data[previews.KEY]==saved
    db.commit.assert_called_once();db.close.assert_called_once()


def test_browse_never_generates_or_writes_and_refresh_fetches_external_insert(monkeypatch):
    from views.project_browser import refresh
    db=Mock();monkeypatch.setattr(projects,'SessionLocal',lambda:db)
    rows=[SimpleNamespace(id=48,title='Same',subtitle='',event_date='2026-11-21',venue_name='Venue',flyer_json='{}')]
    monkeypatch.setattr(projects.project_repo,'list_projects',lambda db:list(rows))
    refresh()
    assert len(projects.list_project_cards())==1
    rows.append(SimpleNamespace(**{**vars(rows[0]),'id':49}))
    refresh()
    assert [p['id'] for p in projects.list_project_cards()]==[49,48]
    db.commit.assert_not_called();db.add.assert_not_called()
    refresh()


def test_gallery_renders_watermark_and_opens_by_id(app_test,monkeypatch):
    from views import project_browser
    from services import session_manager
    pictures=previews.decode({previews.KEY:previews.snapshot({'grid':Image.new('RGB',(1080,1350),'navy')})})
    monkeypatch.setattr(projects,'list_project_cards',lambda:[dict(id=i,title='Same',subtitle='Same',event_date='2026-11-21',venue='Venue',images=pictures) for i in (48,49)])
    opened=Mock();monkeypatch.setattr(project_browser,'open_project',opened)
    at=app_test.run()
    assert not at.exception
    at.button(key='btn_browser_open_49').click().run()
    opened.assert_called_once_with(49)
    assert not at.exception
    assert any('一覧' in x.label for x in at.expander)
    assert 'プロジェクト管理' not in at.sidebar.radio(key='sb_menu').options


def test_originals_keep_exact_png_bytes_and_download_without_generation(monkeypatch):
    import database
    images={}
    for kind in ('grid','tt'):
        out=io.BytesIO();Image.new('RGBA',(1080,1350),'navy').save(out,'PNG');images[kind]=out.getvalue()
    stored={}
    monkeypatch.setattr(database,'upload_image_to_supabase',lambda data,name:stored.setdefault(name,data.getvalue()) and name)
    payload=previews.prepare(images)
    for kind,path in payload['originals'].items():
        assert stored[path]==images[kind]
        assert Image.open(io.BytesIO(stored[path])).size==(1080,1350)
    monkeypatch.setattr(database,'get_image_url',lambda path:'https://example.test/'+path)
    links=previews.downloads({previews.KEY:payload},49)
    assert all(links[k].endswith('?download=flyer_49_'+k+'.png') for k in ('grid','tt'))
    assert previews.downloads({previews.KEY:{'originals':{'grid':'https://evil.test/a'}}},49)=={}


def test_original_upload_failure_never_publishes_partial_pair(monkeypatch):
    import database,pytest
    db=Mock();monkeypatch.setattr(database,'SessionLocal',lambda:db)
    upload=Mock(side_effect=['stored',None]);monkeypatch.setattr(database,'upload_image_to_supabase',upload)
    with pytest.raises(ValueError,match='保管'):
        previews.save(49,{k:Image.new('RGB',(1080,1350),'navy') for k in ('grid','tt')})
    db.commit.assert_not_called()


def test_backfill_refuses_changed_settings_before_commit(monkeypatch):
    import database,pytest
    db=Mock();monkeypatch.setattr(database,'SessionLocal',lambda:db)
    monkeypatch.setattr(previews,'prepare',lambda images:{'images':{},'originals':{}})
    monkeypatch.setattr(previews,'revision',lambda project:'new revision')
    with pytest.raises(ValueError,match='変更'):
        previews.save(49,{},expected_revision='old revision')
    db.commit.assert_not_called();db.rollback.assert_called_once();db.close.assert_called_once()


def test_old_editor_does_not_restore_obsolete_download_links():
    from database import TimetableProject
    from models import ProjectDraft
    from repositories.project_repo import apply_draft
    row=TimetableProject(id=49,flyer_json=json.dumps({previews.KEY:{'originals':{'grid':'new.png'}}}))
    draft=ProjectDraft(id=49,title='Updated',flyer_settings={previews.KEY:{'originals':{'grid':'old.png'}},'logo_scale':1.17})
    apply_draft(row,draft)
    assert json.loads(row.flyer_json)[previews.KEY]['originals']['grid']=='new.png'
    assert json.loads(row.flyer_json)['logo_scale']==1.17


def browser_cards(count):
    pictures=previews.decode({previews.KEY:previews.snapshot({k:Image.new('RGB',(1080,1350),'navy') for k in ('grid','tt')})})
    return [dict(id=9000+i,title='公演',subtitle=f'サブ{i}',event_date='2026-11-21',venue='会場',images=pictures) for i in range(count)]


def test_compact_list_has_ten_items_both_previews_and_bottom_pagination(app_test,monkeypatch):
    records=browser_cards(11)
    monkeypatch.setattr(projects,'list_project_cards',Mock(return_value=records))
    at=app_test.run();assert not at.exception
    assert len([b for b in at.button if b.key and b.key.startswith('btn_browser_open_')])==10
    assert not any(r.key=='browser_variant' for r in at.radio)
    assert not any(n.label=='ページ' for n in at.number_input)
    assert any(m.value=='公演 - サブ0' for m in at.markdown)
    assert len(at.get('image'))==20
    assert at.button(key='btn_browser_prev').disabled
    at.button(key='btn_browser_next').click().run();assert not at.exception
    assert at.button(key='btn_browser_open_9010')
    assert at.button(key='btn_browser_next').disabled
    at.text_input(key='browser_search').set_value('サブ0').run();assert not at.exception
    assert at.button(key='btn_browser_open_9000')
    assert at.button(key='btn_browser_prev').disabled


def test_delete_requires_explicit_confirmation_and_cancel_never_deletes(app_test,monkeypatch):
    records=browser_cards(2)
    monkeypatch.setattr(projects,'list_project_cards',Mock(side_effect=lambda:list(records)))
    delete=Mock(return_value=True);monkeypatch.setattr(projects,'delete_project_by_id',delete)
    at=app_test.run()
    at.button(key='btn_browser_delete_9000').click().run();assert not at.exception
    delete.assert_not_called()
    assert at.button(key='btn_browser_delete_confirm').disabled
    at.button(key='btn_browser_delete_cancel').click().run();delete.assert_not_called()
    at.button(key='btn_browser_delete_9001').click().run()
    at.checkbox(key='browser_delete_confirmed').check().run()
    at.button(key='btn_browser_delete_confirm').click().run();assert not at.exception
    delete.assert_called_once_with(9001)
    assert 'browser_delete_target' not in at.session_state
