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
    monkeypatch.setattr(project_repo,'get_project',lambda db,pid:row if pid==49 else None)
    saved=previews.save(49,{'grid':Image.new('RGB',(1080,1350),'navy')})
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
