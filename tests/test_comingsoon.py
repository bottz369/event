"""Masking, storage round trips and public rendering; all writes are mocked."""
import json
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from PIL import Image, ImageDraw
from models.timetable import TimetableRowDraft, draft_rows_to_df, df_to_draft_rows


def test_checkbox_roundtrip_preserves_identity_and_defaults():
    rows = [TimetableRowDraft(artist_name='Secret', is_comingsoon=True), TimetableRowDraft(artist_name='Visible')]
    df = draft_rows_to_df(rows)
    assert df['COMINGSOON'].tolist() == [True, False]
    restored = df_to_draft_rows(df)
    assert restored[0].artist_name == 'Secret' and restored[0].is_comingsoon
    assert not TimetableRowDraft.from_dict({'ARTIST':'Old'}).is_comingsoon
    assert not TimetableRowDraft.from_dict({'COMINGSOON':'false'}).is_comingsoon


def test_timetable_mask_preserves_times_goods_and_unmasking():
    from services.timetable_service import build_tt_gen_list_from_rows
    rows = [TimetableRowDraft(artist_name='Secret', place='B'), TimetableRowDraft(artist_name='Visible')]
    before = build_tt_gen_list_from_rows(rows, '10:00', '10:30')
    rows[0].is_comingsoon = True
    masked = build_tt_gen_list_from_rows(rows, '10:00', '10:30')
    assert masked[0][1] == 'comingsoon' and masked[1] == before[1]
    assert masked[0][0] == before[0][0] and masked[0][2:] == before[0][2:]
    rows[0].is_comingsoon = False
    assert build_tt_gen_list_from_rows(rows, '10:00', '10:30') == before


def test_grid_masks_without_fetching_hidden_artist(monkeypatch):
    from services import comingsoon, artist_service
    visible = SimpleNamespace(name='Visible')
    resolver = Mock(return_value=[visible])
    monkeypatch.setattr(artist_service, 'resolve_artists_in_order', resolver)
    artists = comingsoon.resolve_public_artists(['Secret','Visible'], [TimetableRowDraft(artist_name='Secret',is_comingsoon=True)])
    resolver.assert_called_once_with(['Visible'], failures=None)
    assert artists[0].name == 'comingsoon' and artists[0].image_filename is None
    assert artists[1] is visible


def test_multipart_mask_is_per_part():
    from services.event_format_service import timetable_rows
    from models.event_format import new_part
    first = new_part(0,rows=[TimetableRowDraft(artist_name='Secret',is_comingsoon=True).to_legacy_dict()])
    second = new_part(1,rows=[TimetableRowDraft(artist_name='Secret').to_legacy_dict()])
    assert timetable_rows(first)[0][1] == 'comingsoon'
    assert timetable_rows(second)[0][1] == 'Secret'


def test_black_public_images_do_not_query_artist(monkeypatch, tmp_path):
    import logic_grid, logic_timetable
    from services.comingsoon import resolve_public_artists
    from models.artist import ArtistView
    font = logic_grid.resolve_font_path('keifont.ttf')
    if not font: pytest.skip('font unavailable')
    image = logic_grid.generate_grid_image([ArtistView(0,'comingsoon',None,False,1.,0,0,True)],'',font_path=font,row_counts=[1])
    assert image is not None
    # The photo area contains only a black field and the white label, no missing-photo guide.
    assert image.convert('RGB').getpixel((30,30)) == (0,0,0)
    db = Mock(); db.query.side_effect = AssertionError('concealed artist must not be fetched')
    canvas = Image.new('RGBA',(1200,150),'red')
    logic_timetable.draw_one_row(ImageDraw.Draw(canvas),canvas,0,0,['10:30 - 10:50','comingsoon','11:00 - 12:00','B'],font,db,1200,150,2)
    assert canvas.getpixel((2,2)) == (0,0,0,255)
    db.query.assert_not_called()
    image.save(tmp_path/'grid.png')


def test_repository_flags_restore_only_matching_rows(monkeypatch):
    from repositories import timetable_repo
    rows = [TimetableRowDraft(artist_name='Secret'),TimetableRowDraft(artist_name='Different')]
    db=Mock(); db.query.return_value.filter.return_value.order_by.return_value.all.return_value=rows
    db.query.return_value.filter.return_value.first.return_value=SimpleNamespace(settings_json=json.dumps({'comingsoon_rows':[{'index':0,'artist':'Secret'},{'index':1,'artist':'Old'}]}))
    monkeypatch.setattr(timetable_repo,'_row_to_draft',lambda row:row)
    restored=timetable_repo.load_rows(db,123)
    assert [r.is_comingsoon for r in restored] == [True,False]
    db.commit.assert_not_called()


@pytest.mark.parametrize('enabled',[True,False])
def test_line_edit_changes_only_metadata_not_registration_or_timing(monkeypatch,enabled):
    from services import comingsoon
    import database
    from repositories import timetable_repo
    project=SimpleNamespace(settings_json=json.dumps({'other':'keep'}))
    db=Mock(); db.query.return_value.filter.return_value.with_for_update.return_value.first.return_value=project
    monkeypatch.setattr(database,'SessionLocal',lambda:db)
    monkeypatch.setattr(timetable_repo,'load_rows',lambda *_:[TimetableRowDraft(artist_name='Secret',is_comingsoon=True)])
    comingsoon.set_project_slot(123,dict(part=None,index=0,artist='Secret'),enabled)
    settings=json.loads(project.settings_json)
    assert settings['other']=='keep'
    assert bool(settings['comingsoon_rows']) is enabled
    db.commit.assert_called_once(); db.delete.assert_not_called();db.add.assert_not_called()


def test_line_rejects_changed_slot_without_commit(monkeypatch):
    from services import comingsoon
    import database
    from repositories import timetable_repo
    project=SimpleNamespace(settings_json='{}')
    db=Mock(); db.query.return_value.filter.return_value.with_for_update.return_value.first.return_value=project
    monkeypatch.setattr(database,'SessionLocal',lambda:db)
    monkeypatch.setattr(timetable_repo,'load_rows',lambda *_:[TimetableRowDraft(artist_name='Changed')])
    with pytest.raises(ValueError,match='出演順'):
        comingsoon.set_project_slot(123,dict(part=None,index=0,artist='Secret'),True)
    assert project.settings_json=='{}';db.commit.assert_not_called(); db.rollback.assert_called_once()


def test_line_multipart_persistence_keeps_other_part(monkeypatch):
    from services import comingsoon
    import database
    from models.event_format import new_part, KEY
    parts=[new_part(i,rows=[TimetableRowDraft(artist_name='Secret').to_legacy_dict()]) for i in range(2)]
    project=SimpleNamespace(settings_json=json.dumps({KEY:dict(enabled=True,count=2,parts=parts)}))
    db=Mock();db.query.return_value.filter.return_value.with_for_update.return_value.first.return_value=project
    monkeypatch.setattr(database,'SessionLocal',lambda:db)
    comingsoon.set_project_slot(123,dict(part=1,index=0,artist='Secret'),True)
    actual=json.loads(project.settings_json)[KEY]['parts']
    assert actual[0]==parts[0]
    assert actual[1]['rows'][0]['COMINGSOON'] is True


def test_normal_editor_checkbox_reaches_draft(app_test, two_projects_different_row_counts):
    from tests.test_tt_editor_repro import _open_project_tt, SELECTOR_KEY, _sget
    (_, label, _), _ = two_projects_different_row_counts
    at=app_test.run()
    assert label in at.selectbox(key=SELECTOR_KEY).options
    _open_project_tt(at,label)
    rows=_sget(at,'draft_rows')
    index=next(i for i,r in enumerate(rows) if not r.is_special_row)
    name=rows[index].artist_name
    for enabled in (True,False):
        editor_key=f"tt_editor_{_sget(at,'tt_editor_key')}"
        at.session_state[editor_key]={'edited_rows':{index:{'COMINGSOON':enabled}},'added_rows':[],'deleted_rows':[]}
        at.run()
        assert not at.exception
        row=_sget(at,'draft_rows')[index]
        assert row.artist_name==name and row.is_comingsoon is enabled


def test_multipart_editor_checkbox_reaches_saved_part(monkeypatch):
    from views import event_format
    from services import session_manager
    from models.project import ProjectDraft
    from models.event_format import KEY,new_part
    draft=ProjectDraft(id=999,settings={KEY:dict(enabled=True,count=2,parts=[new_part(0,rows=[TimetableRowDraft(artist_name='Secret').to_legacy_dict()]),new_part(1)])})
    state=dict(draft_project=draft,ws_active_project_id=999,editor0=dict(edited_rows={0:{'COMINGSOON':True}},added_rows=[],deleted_rows=[]))
    monkeypatch.setattr(session_manager.st,'session_state',state)
    event_format._rows_changed('editor0',0)
    assert draft.settings[KEY]['parts'][0]['rows'][0]['COMINGSOON'] is True
    assert draft.settings[KEY]['parts'][0]['rows'][0]['ARTIST']=='Secret'


def test_web_save_writes_matching_metadata_then_reload(monkeypatch):
    from repositories import project_repo,timetable_repo
    from models.project import ProjectDraft
    draft=ProjectDraft(id=123,settings={'other':'keep'})
    project=SimpleNamespace(id=123,flyer_json='{}',subtitle='',data_json='[]')
    rows=[TimetableRowDraft(artist_name='Secret',is_comingsoon=True)]
    project_repo.apply_draft(project,draft,rows)
    assert json.loads(project.settings_json)['comingsoon_rows']==[dict(index=0,artist='Secret')]
    assert project.data_json=='[]'
    db=Mock();db.query.return_value.filter.return_value.order_by.return_value.all.return_value=rows
    db.query.return_value.filter.return_value.first.return_value=project
    monkeypatch.setattr(timetable_repo,'_row_to_draft',lambda _:TimetableRowDraft(artist_name='Secret'))
    assert timetable_repo.load_rows(db,123)[0].is_comingsoon
