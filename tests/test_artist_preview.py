"""Artist preview uses the exact tile crop used by the generated grid."""
import numpy as np
from PIL import Image
import pytest


@pytest.mark.parametrize('scale,x,y',[(1.,0,0),(1.3,100,-60),(.6,-200,112)])
def test_thumbnail_is_downscaled_generator_crop(monkeypatch,scale,x,y):
    from views import artists
    from logic_grid import apply_manual_crop,TILE_WIDTH,TILE_HEIGHT
    raw=np.indices((700,1000)).sum(axis=0)%256
    image=Image.fromarray(np.stack([raw,raw//2,255-raw],axis=2).astype('uint8'))
    monkeypatch.setattr(artists,'get_image_url',lambda _:'fixture')
    monkeypatch.setattr(artists,'load_image_from_url',lambda _:image)
    artists.get_processed_thumbnail.clear()
    actual=artists.get_processed_thumbnail('fixture.png',scale,x,y)
    expected=apply_manual_crop(image,scale,x,y,TILE_WIDTH,TILE_HEIGHT).resize((400,225),Image.LANCZOS)
    assert np.array_equal(np.array(actual),np.array(expected))


def test_manual_removed_and_preview_tracks_sliders(app_test,monkeypatch):
    from views import artists
    from models.artist import ArtistView
    from types import SimpleNamespace
    monkeypatch.setattr(artists.artist_service,'list_artists',lambda:[SimpleNamespace(id=99,name='Test',image_filename='test.png',crop_scale=1.,crop_x=0,crop_y=0)])
    thumb=[]
    def preview(filename,scale,x,y):
        thumb.append((scale,x,y));return Image.new('RGB',(400,225))
    monkeypatch.setattr(artists,'get_processed_thumbnail',preview)
    at=app_test.run()
    assert '使い方マニュアル' not in at.radio(key='sb_menu').options
    at.radio(key='sb_menu').set_value('アーティスト管理').run()
    selector=next(s for s in at.selectbox if s.label=='編集するアーティストを選択・検索してください')
    selector.select('Test').run()
    at.slider(key='sx_99').set_value(100).run()
    at.slider(key='sy_99').set_value(-50).run()
    assert not at.exception
    assert thumb[-1]==(1.,100,-50)
    assert '左（−）' in at.slider(key='sx_99').label and '上（−）' in at.slider(key='sy_99').label
