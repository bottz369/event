"""Existing-project updates: no real writes, generated uploads, LINE or paid API calls."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock
import json

import pytest
from models.project import ProjectDraft
from models.timetable import TimetableRowDraft
from models.event_format import KEY,new_part


def sample():
    from tests.test_auto_production import event,part
    from services.production_service import compile_plan
    return compile_plan(event(),[part()])


def test_updated_facts_and_overview_order_keep_appearance_and_masks():
    from services.production_update import merge_plan
    incoming,rows=sample()
    existing=deepcopy(incoming);existing.id=49;existing.title='Old title'
    existing.settings.update(tt_font='saved-font.ttf',custom='keep')
    existing.grid_settings['layout_mode']='両端揃え (拡大縮小)'
    existing.flyer_settings={'logo_scale':1.5,'bg_id':10,'logo_id':20,'_project_preview':{'old':True}}
    previous=deepcopy(rows);previous[0].is_comingsoon=True;previous[1].is_grid_hidden=True
    snapshot=deepcopy(existing)
    draft,updated=merge_plan(existing,previous,incoming,rows)
    assert draft.id==49 and draft.title==incoming.title
    assert draft.settings['tt_font']=='saved-font.ttf' and draft.settings['custom']=='keep'
    assert draft.grid_settings['layout_mode']=='両端揃え (拡大縮小)'
    assert draft.flyer_settings=={'logo_scale':1.5,'bg_id':10,'logo_id':20}
    assert updated[0].is_comingsoon and updated[1].is_grid_hidden
    assert updated[0].goods_start_time==rows[0].goods_start_time
    assert existing==snapshot and not rows[0].is_comingsoon


def test_multipart_masks_match_source_part_not_another_part():
    from services.production_update import merge_plan
    from services.production_service import compile_plan
    from tests.test_auto_production import event,part
    existing,previous=compile_plan(event(),[part('1部'),part('2部')])
    existing.id=1;existing.settings[KEY]['parts'][1]['rows'][0]['COMINGSOON']=True
    incoming,rows=compile_plan(event(),[part('1部'),part('2部')])
    updated,_=merge_plan(existing,previous,incoming,rows)
    assert not updated.settings[KEY]['parts'][0]['rows'][0]['COMINGSOON']
    assert updated.settings[KEY]['parts'][1]['rows'][0]['COMINGSOON']


def test_reducing_parts_cannot_reveal_existing_concealed_name():
    from services.production_update import merge_plan
    incoming,rows=sample();old=deepcopy(incoming);old.id=1
    part=new_part(0,rows=[TimetableRowDraft(artist_name='A',is_comingsoon=True).to_legacy_dict()])
    old.settings[KEY].update(enabled=True,count=2,parts=[part,new_part(1)])
    updated,rows=merge_plan(old,[],incoming,rows)
    assert not updated.settings[KEY]['enabled'] and rows[0].is_comingsoon


def test_existing_update_is_one_transaction_with_prepared_image_pair(monkeypatch):
    import database
    from services import production_update as update,project_previews
    from repositories import project_repo,timetable_repo
    draft,rows=sample();draft.id=49
    project=SimpleNamespace(flyer_json='{}')
    db=Mock();db.query.return_value.filter.return_value.with_for_update.return_value.first.return_value=project
    monkeypatch.setattr(database,'SessionLocal',lambda:db)
    monkeypatch.setattr(project_previews,'prepare',lambda images:{'pair':'prepared'})
    monkeypatch.setattr(update,'fingerprint',lambda *_:'baseline')
    monkeypatch.setattr(timetable_repo,'load_rows',Mock(return_value=[]))
    apply=Mock();save=Mock(return_value=True)
    monkeypatch.setattr(project_repo,'apply_draft',apply)
    monkeypatch.setattr(timetable_repo,'save_rows',save)
    assert update.persist_update(draft,rows,{'grid':b'a','tt':b'b'},'baseline')==49
    apply.assert_called_once_with(project,draft,rows=rows)
    save.assert_called_once_with(db,49,rows,commit=False)
    db.commit.assert_called_once();db.rollback.assert_not_called()
    assert json.loads(project.flyer_json)['_project_preview']=={'pair':'prepared'}


@pytest.mark.parametrize('failure',['conflict','rows','commit'])
def test_failed_update_never_leaves_a_partial_commit(monkeypatch,failure):
    import database
    from services import production_update as update,project_previews
    from repositories import project_repo,timetable_repo
    draft,rows=sample();draft.id=49
    project=SimpleNamespace(flyer_json='{}')
    db=Mock();db.query.return_value.filter.return_value.with_for_update.return_value.first.return_value=project
    monkeypatch.setattr(database,'SessionLocal',lambda:db)
    monkeypatch.setattr(project_previews,'prepare',lambda images:{})
    monkeypatch.setattr(update,'fingerprint',lambda *_:'changed' if failure=='conflict' else 'baseline')
    monkeypatch.setattr(timetable_repo,'load_rows',Mock(return_value=[]))
    apply=Mock();save=Mock(return_value=True)
    if failure=='rows':save.side_effect=ValueError('row failure')
    if failure=='commit':db.commit.side_effect=RuntimeError('unknown outcome')
    monkeypatch.setattr(project_repo,'apply_draft',apply);monkeypatch.setattr(timetable_repo,'save_rows',save)
    with pytest.raises(Exception):update.persist_update(draft,rows,{'grid':b'a','tt':b'b'},'baseline')
    db.rollback.assert_called_once()
    if failure=='conflict':apply.assert_not_called();save.assert_not_called()
    if failure!='commit':db.commit.assert_not_called()


def test_output_upload_failure_happens_before_db_transaction(monkeypatch):
    import database
    from services import production_update as update,project_previews
    draft,rows=sample();draft.id=49
    session=Mock();monkeypatch.setattr(database,'SessionLocal',session)
    monkeypatch.setattr(project_previews,'prepare',Mock(side_effect=project_previews.OutputStorageError('storage failed')))
    with pytest.raises(project_previews.OutputStorageError):update.persist_update(draft,rows,{},'baseline')
    session.assert_not_called()


def test_row_repository_can_participate_in_callers_transaction():
    from repositories import timetable_repo
    db=Mock()
    assert timetable_repo.save_rows(db,1,[TimetableRowDraft(artist_name='A')],commit=False)
    db.flush.assert_called_once();db.commit.assert_not_called()
    db.add_all.side_effect=ValueError('failed')
    with pytest.raises(ValueError):timetable_repo.save_rows(db,1,[],commit=False)
    db.rollback.assert_not_called() # Outer transaction owns rollback.


def test_row_changes_participate_in_fingerprint(monkeypatch):
    from services import production_update as update,project_previews
    monkeypatch.setattr(project_previews,'revision',lambda _:'same-settings')
    rows=[TimetableRowDraft(artist_name='A')]
    before=update.fingerprint(object(),rows)
    rows[0].duration=25
    assert update.fingerprint(object(),rows)!=before


def test_updated_package_renders_both_originals_with_saved_recipe(monkeypatch):
    from pathlib import Path
    from PIL import Image
    import io
    import logic_grid,logic_timetable
    from constants import FONT_DIR
    from services import production_service,production_templates,production_update,font_service,artist_service
    from tests.test_production_templates import recipe
    font=str(Path(FONT_DIR)/'keifont.ttf')
    if not Path(font).exists():pytest.skip('font unavailable')
    monkeypatch.setattr(font_service,'ensure_font_path',lambda _:font)
    monkeypatch.setattr(artist_service,'resolve_artists_in_order',lambda names,**_:names)
    monkeypatch.setattr(logic_grid,'generate_grid_image',lambda *a,**_:Image.new('RGBA',(1000,600),'gray'))
    monkeypatch.setattr(logic_timetable,'generate_timetable_image',lambda *a,**_:Image.new('RGBA',(2400,800),'gray'))
    incoming,rows=sample();existing=deepcopy(incoming);existing.id=49;existing.flyer_settings=recipe()
    previous=deepcopy(rows);previous[0].is_comingsoon=True
    updated,rows=production_update.merge_plan(existing,previous,incoming,rows)
    output=io.BytesIO();Image.new('RGB',(1080,1350),'navy').save(output,'PNG')
    package=production_service.render_package(updated,rows,output.getvalue(),template=production_templates.capture(existing))
    assert package['draft'].id==49 and package['rows'][0].is_comingsoon
    assert set(package['images'])=={'grid','tt'}
    assert all(Image.open(io.BytesIO(blob)).size==(1080,1350) for blob in package['images'].values())
    assert package['draft'].flyer_settings['date_font']==existing.flyer_settings['date_font']


def test_read_target_restores_display_settings_without_writes(monkeypatch):
    import database
    from services import production_update as update
    from repositories import project_repo,timetable_repo
    draft,rows=sample();draft.id=49;draft.grid_settings.update(order=['B','A'],grid_hidden=['B'])
    db=Mock();project=object()
    monkeypatch.setattr(database,'SessionLocal',lambda:db)
    monkeypatch.setattr(project_repo,'get_project',lambda *_:project)
    monkeypatch.setattr(project_repo,'to_draft',lambda _:draft)
    monkeypatch.setattr(timetable_repo,'load_rows',lambda *_:rows)
    monkeypatch.setattr(update,'fingerprint',lambda *_:'version')
    target=update.load_target(49)
    assert target['revision']=='version'
    assert target['rows'][1].is_grid_hidden
    assert target['rows'][0].grid_no==2 and target['rows'][1].grid_no==1
    db.commit.assert_not_called();db.close.assert_called_once()


def test_missing_or_changed_target_never_falls_back_to_new_project(monkeypatch):
    import database
    from services import production_update as update
    from repositories import project_repo
    db=Mock();monkeypatch.setattr(database,'SessionLocal',lambda:db)
    monkeypatch.setattr(project_repo,'get_project',lambda *_:None)
    with pytest.raises(ValueError,match='見つかりません'):update.load_target(49)
    db.commit.assert_not_called()
    monkeypatch.setattr(update,'load_target',lambda _:{'revision':'new'})
    with pytest.raises(update.ProjectChanged):update.ensure_current(49,'old')
