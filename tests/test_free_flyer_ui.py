from copy import deepcopy
import io
from unittest.mock import Mock
from PIL import Image
from streamlit.testing.v1 import AppTest

from services import free_flyer as ff


def setup(monkeypatch):
    from views import free_flyer as view,image_studio
    import database
    out=io.BytesIO();Image.new('RGB',(100,140),'red').save(out,'PNG');data=out.getvalue()
    doc=ff.new_document(ff.PREFIX+'a'*64+'.png','Tour')
    doc.update(fields=[dict(id='f1',label='日付',value='11/29(日)'),dict(id='f2',label='会場',value='Venue')],selected=['f1'],reviewed=True)
    monkeypatch.setattr(ff,'load',lambda _: (deepcopy(doc),'baseline'))
    monkeypatch.setattr(view,'_photo',lambda _:data)
    monkeypatch.setattr(database,'get_image_url',lambda p:'https://example.com/'+p)
    monkeypatch.setattr(image_studio,'_settings',lambda:('key','code'))
    edit=Mock(return_value=data);save=Mock(return_value=55)
    monkeypatch.setattr(ff,'edit',edit);monkeypatch.setattr(ff,'save',save)
    monkeypatch.setattr(ff,'put_image',lambda _:ff.PREFIX+'b'*64+'.png')
    return edit,save


def test_view_rerender_is_read_only_and_changes_require_generation(monkeypatch):
    edit,save=setup(monkeypatch)
    app=AppTest.from_string('from views.free_flyer import render\nrender(55)').run()
    assert not app.exception
    app.text_area(key='ff_editor_55_0_f1').set_value('12/5(土)').run()
    app.checkbox(key='ff_editor_55_0_confirmed').check().run()
    assert app.button(key='ff_editor_55_0_save').disabled
    edit.assert_not_called();save.assert_not_called()
    assert not any(t.label=='会場' for t in app.text_area)


def test_field_change_preview_then_explicit_save(monkeypatch):
    edit,save=setup(monkeypatch)
    from views import project_browser
    from services import session_manager
    monkeypatch.setattr(project_browser,'refresh',lambda:None)
    monkeypatch.setattr(session_manager,'reload_project',Mock(return_value=True))
    app=AppTest.from_string('from views.free_flyer import render\nrender(55)').run()
    app.text_input(key='ff_editor_55_0_code').set_value('code').run()
    app.text_area(key='ff_editor_55_0_f1').set_value('12/5(土)').run()
    app.button(key='ff_editor_55_0_generate').click().run()
    assert not app.exception
    edit.assert_called_once();save.assert_not_called()
    assert edit.call_args.kwargs['locked'][0]['before']=='11/29(日)'
    assert app.text_area(key='ff_editor_55_1_f1').value=='12/5(土)'
    app.checkbox(key='ff_editor_55_1_confirmed').check().run()
    app.button(key='ff_editor_55_1_save').click().run()
    assert not app.exception
    save.assert_called_once()
    assert save.call_args.args[0]['fields'][0]['value']=='12/5(土)'
    assert save.call_args.args[1:]==(55,'baseline')


def test_free_project_generation_returns_only_saved_completed_image(monkeypatch):
    from types import SimpleNamespace
    from services import event_format_service,generation_service
    monkeypatch.setattr(event_format_service,'project_from_db',lambda _:SimpleNamespace(flyer_settings={ff.KEY:{'current':'current'}}))
    fetch=Mock(return_value=b'PNG');monkeypatch.setattr(ff,'get_image',fetch)
    assert generation_service.render_flyer_png_for_project(55,'grid')==b'PNG'
    assert generation_service.render_flyer_png_for_project(55,'tt') is None
    fetch.assert_called_once_with('current')
