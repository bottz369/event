"""Catalog open performs no font downloads, image fetching, or specimen generation."""
import io
from unittest.mock import Mock
from PIL import Image


def test_catalog_is_lazy_and_pages_only_selected_type(app_test,monkeypatch):
    from views import assets
    from services import asset_thumbnails,font_service
    fetch=Mock(side_effect=AssertionError('catalog must not fetch originals'))
    monkeypatch.setattr(assets.requests,'get',fetch)
    sync=Mock(side_effect=AssertionError('no full font sync on open'))
    monkeypatch.setattr(assets,'sync_fonts_from_storage',sync)
    font=Mock(side_effect=AssertionError('no font download on open'))
    monkeypatch.setattr(font_service,'ensure_font_path',font)
    specimen=Mock(side_effect=AssertionError('no specimen on open'))
    monkeypatch.setattr(assets,'create_font_thumbnail',specimen)
    at=app_test.run()
    at.sidebar.radio(key='sb_menu').set_value('アセット管理').run()
    assert not at.exception
    assert len([b for b in at.button if b.key and b.key.startswith('del_')])<=12
    assert len(at.tabs)==0
    html=[m.value for m in at.markdown if '<img ' in m.value]
    assert 0<len(html)<=12 and all('asset_thumbnails/' in m and 'loading="lazy"' in m for m in html)
    at.radio(key='assets_kind').set_value('background').run();assert not at.exception
    assert len([b for b in at.button if b.key and b.key.startswith('del_')])<=12
    at.button(key='btn_assets_next').click().run();assert not at.exception
    at.text_input(key='assets_search').set_value('not a real asset name').run()
    assert not at.exception and at.button(key='btn_assets_prev').disabled
    at.radio(key='assets_kind').set_value('font').run()
    at.text_input(key='assets_search').set_value('').run()
    assert not at.exception
    font.assert_not_called();specimen.assert_not_called();fetch.assert_not_called();sync.assert_not_called()


def test_thumbnail_is_small_and_preserves_original_alpha(monkeypatch):
    import database
    from services import asset_thumbnails
    source=Image.new('RGBA',(1080,1350),(20,40,60,0));source.putpixel((500,500),(255,0,0,255))
    original=io.BytesIO();source.save(original,'PNG');data=original.getvalue()
    upload=Mock(return_value='stored');monkeypatch.setattr(database,'upload_image_to_supabase',upload)
    result=asset_thumbnails.store(data,'original.png')
    image=Image.open(io.BytesIO(result))
    assert image.width<=320 and image.height<=200
    assert image.mode=='RGBA' and image.getpixel((0,0))[3]==0
    assert upload.call_args.args[1].startswith('asset_thumbnails/')
    assert original.getvalue()==data


def test_failed_thumbnail_never_invalidates_original_upload(monkeypatch):
    from services import asset_thumbnails
    monkeypatch.setattr(asset_thumbnails,'store',Mock(side_effect=ValueError('unavailable')))
    assert asset_thumbnails.try_store(b'image','original.png') is False


def test_large_jpeg_is_draft_decoded_before_allocating_full_rgba(monkeypatch):
    import database
    from services import asset_thumbnails
    original=io.BytesIO();Image.new('RGB',(1280,800),'navy').save(original,'JPEG')
    monkeypatch.setattr(Image,'MAX_IMAGE_PIXELS',700000)
    monkeypatch.setattr(database,'upload_image_to_supabase',lambda data,name:name)
    result=asset_thumbnails.store(original.getvalue(),'large.jpg')
    assert Image.open(io.BytesIO(result)).size==(320,200)
