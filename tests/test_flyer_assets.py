"""Explicit upload actions only; all storage/DB writes are mocked."""
import io
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image


def image_bytes(fmt='PNG'):
    data = io.BytesIO()
    Image.new('RGBA' if fmt == 'PNG' else 'RGB', (40, 60), (30, 40, 50, 80) if fmt == 'PNG' else (30, 40, 50)).save(data, format=fmt)
    return data.getvalue()


@pytest.mark.parametrize('kind', ['background', 'logo'])
def test_upload_saves_verified_image_and_commits_asset(monkeypatch, kind):
    import database
    from services import asset_service
    data = image_bytes()
    storage = Mock(return_value='saved')
    db = Mock()
    create = Mock(return_value=SimpleNamespace(id=901, name='祭り', image_filename='stored.png'))
    monkeypatch.setattr(database, 'upload_image_to_supabase', storage)
    monkeypatch.setattr(asset_service, 'SessionLocal', lambda: db)
    monkeypatch.setattr(asset_service.asset_repo, 'add_image_asset', create)
    result = asset_service.upload_image_asset(data, 'original.jpg', kind, ' 祭り ')
    assert result.id == 901
    args = create.call_args.args
    assert args[:3] == (db, '祭り', kind)
    assert args[3].startswith('asset_') and args[3].endswith('.png')
    assert storage.call_args_list[0].args[0].getvalue() == data  # transparency preserved
    db.commit.assert_called_once()
    db.close.assert_called_once()


@pytest.mark.parametrize('data,kind', [(b'bad', 'logo'), (b'', 'background'), (b'x'*(20*1024*1024+1), 'background'), (image_bytes(), 'font')])
def test_invalid_upload_never_touches_storage_or_database(monkeypatch, data, kind):
    import database
    from services import asset_service
    storage, session = Mock(), Mock()
    monkeypatch.setattr(database, 'upload_image_to_supabase', storage)
    monkeypatch.setattr(asset_service, 'SessionLocal', session)
    with pytest.raises(ValueError):
        asset_service.upload_image_asset(data, 'image.png', kind)
    storage.assert_not_called()
    session.assert_not_called()


def test_failed_storage_does_not_register_asset(monkeypatch):
    import database
    from services import asset_service
    monkeypatch.setattr(database, 'upload_image_to_supabase', lambda *a: None)
    session = Mock()
    monkeypatch.setattr(asset_service, 'SessionLocal', session)
    with pytest.raises(ValueError, match='保存できません'):
        asset_service.upload_image_asset(image_bytes(), 'bg.png', 'background')
    session.assert_not_called()


def test_db_failure_rolls_back_and_reports_failure(monkeypatch):
    import database
    from services import asset_service
    monkeypatch.setattr(database, 'upload_image_to_supabase', lambda *a: 'ok')
    db = Mock()
    db.commit.side_effect = RuntimeError('unavailable')
    monkeypatch.setattr(asset_service, 'SessionLocal', lambda: db)
    monkeypatch.setattr(asset_service.asset_repo, 'add_image_asset', lambda *a: SimpleNamespace(id=1,name='bg',image_filename='x.png'))
    with pytest.raises(ValueError, match='登録に失敗'):
        asset_service.upload_image_asset(image_bytes(), 'bg.png', 'background')
    db.rollback.assert_called_once()
    db.close.assert_called_once()


@pytest.mark.parametrize('kind,key_name,label', [('background','flyer_bg_id','背景画像'),('logo','flyer_logo_id','ロゴ画像')])
def test_flyer_upload_is_explicit_selects_asset_and_does_not_repeat(app_test,monkeypatch,kind,key_name,label):
    from tests.conftest import select_tab
    from views.workspace import TAB_FLYER, TAB_TT
    from views import flyer
    from services import asset_service
    from models.asset import AssetView
    uploaded = AssetView(id=9001, name='新しい画像', image_filename='new.png')
    available = []
    upload = Mock(side_effect=lambda *a: available.append(uploaded) or uploaded)
    monkeypatch.setattr(asset_service, 'upload_image_asset', upload)
    monkeypatch.setattr(asset_service, 'list_assets_by_type', lambda t: available if t == kind else [])
    original_uploader = flyer.st.file_uploader
    def fake_uploader(*args, **kwargs):
        if str(kwargs.get('key','')).startswith('asset_upload_'):
            flyer.st.session_state[kwargs['key']] = SimpleNamespace(name='new.png',getvalue=lambda: image_bytes())
            return flyer.st.session_state[kwargs['key']]
        return original_uploader(*args, **kwargs)
    monkeypatch.setattr(flyer.st, 'file_uploader', fake_uploader)
    at = app_test.run()
    project = next(x for x in at.selectbox(key='ws_project_selector_label').options
                   if x not in ('(選択してください)','➕ 新規プロジェクト作成'))
    at.selectbox(key='ws_project_selector_label').select(project).run()
    before = at.session_state['draft_project']
    select_tab(at,TAB_FLYER)
    upload.assert_not_called()
    next(b for b in at.button if b.label == label+'をアセットに保存して選択').click().run()
    assert not at.exception
    upload.assert_called_once()
    assert at.session_state[key_name] == uploaded.id
    assert at.button(key=f'btn_{key_name}_9001').disabled
    at.run()
    select_tab(at,TAB_TT)
    select_tab(at,TAB_FLYER)
    assert not at.exception
    assert at.session_state[key_name] == uploaded.id
    upload.assert_called_once()
    assert at.session_state['draft_project'].title == before.title
