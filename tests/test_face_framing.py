"""Image safety geometry + cached checks + real registration/preview/TT boundaries."""
import io
from dataclasses import replace
from unittest.mock import Mock

import numpy as np
import pytest
from PIL import Image

from services import face_framing as ff


def info(boxes=None, size=(800, 900)):
    return dict(version=1, width=size[0], height=size[1],
        status='detected' if boxes else 'no_faces', boxes=boxes or [])


@pytest.fixture
def detector(monkeypatch):
    calls=Mock(return_value=info([[.1,.02,.25,.23],[.75,.7,.9,.95]]))
    monkeypatch.setattr(ff,'detect',calls)
    return calls


@pytest.mark.parametrize('crop,target', [((1.,0,0),(800,450)), ((2.,150,-100),(800,450)),
    ((1.,0,0),(1740,159)), ((.5,0,0),(800,450))])
def test_all_faces_fit_not_just_the_average_face(crop,target):
    data=info([[.01,.01,.2,.22],[.8,.78,.99,.99]])
    result=ff.corrected(data,crop,target=target)
    assert ff.visible(data,result,target=target)
    assert result[0] <= crop[0]


def test_safe_manual_framing_is_exactly_preserved():
    data=info([[.4,.4,.6,.6]], (800,450))
    assert ff.corrected(data,(1.2,30,-10)) == (1.2,30,-10)


def test_move_before_shrinking_for_single_face():
    data=info([[.4,.15,.6,.25]])
    result=ff.corrected(data,(1.,0,0))
    assert result[0] > .99 and result[2] > 0 and ff.visible(data,result)


def test_no_faces_shows_full_original_with_black_borders():
    data=info()
    crop=ff.corrected(data,(1.,0,0))
    assert ff.visible(data,crop)
    from logic_grid import apply_manual_crop
    output=apply_manual_crop(Image.new('RGB',(800,900),'white'),*crop)
    assert output.getpixel((0,0))[:3]==(0,0,0)
    assert output.getpixel((400,225))[:3]==(255,255,255)


def test_tiny_scale_handles_extreme_panoramas_without_cutting():
    data=info([[0,0,1,1]], (100000,100))
    crop=ff.corrected(data,(1.,0,0),target=(800,450))
    assert crop[0] < .1 and ff.visible(data,crop,target=(800,450))


def test_persisted_bounds_reused_across_process_and_layout_changes(monkeypatch,detector):
    disk={};read=Mock(side_effect=lambda key:disk.get(key));write=Mock(side_effect=lambda key,value:disk.update({key:value}))
    monkeypatch.setattr(ff,'_read',read);monkeypatch.setattr(ff,'_write',write)
    image=Image.new('RGB',(800,900))
    ff.protect(image,'a.png');ff.protect(image,'a.png',(.9,20,0),target=(1740,159))
    detector.assert_called_once();write.assert_called_once()
    ff.CACHE.clear();ff.protect(image,'a.png')
    detector.assert_called_once()
    ff.protect(image,'replacement.png');assert detector.call_count==2


def test_corrupt_bounds_are_replaced_and_detector_failure_does_not_write(monkeypatch):
    monkeypatch.setattr(ff,'_read',lambda _:info([[float('nan'),0,1,1]]))
    detect=Mock(side_effect=RuntimeError('unavailable'));write=Mock()
    monkeypatch.setattr(ff,'detect',detect);monkeypatch.setattr(ff,'_write',write)
    assert ff.protect(Image.new('RGB',(800,450)),'bad.png',(.7,10,0))==(.7,10,0)
    write.assert_not_called()


def test_registered_crop_and_management_preview_use_identical_bounds(monkeypatch,detector):
    from views import artists
    from logic_grid import apply_manual_crop
    image=Image.new('RGB',(800,900),'white');data=io.BytesIO();image.save(data,format='PNG')
    crop=ff.registration(data,'new.png');assert ff.visible(detector.return_value,crop)
    monkeypatch.setattr(artists,'get_image_url',lambda _: 'fixture')
    monkeypatch.setattr(artists,'load_image_from_url',lambda _:image)
    artists.get_processed_thumbnail.clear()
    preview=artists.get_processed_thumbnail('new.png',*crop)
    expected=apply_manual_crop(image,*crop).resize((400,225),Image.LANCZOS)
    assert np.array_equal(np.array(preview),np.array(expected))
    detector.assert_called_once()


def test_timetable_guards_before_irreversible_strip_crop(monkeypatch,detector):
    import logic_timetable as tt
    image=Image.new('RGB',(800,900),'white');data=io.BytesIO();image.save(data,format='PNG')
    monkeypatch.setattr(tt.requests,'get',lambda *a,**kw:Mock(status_code=200,content=data.getvalue()))
    result=tt._load_and_fit_tt('https://example.com/photo.png',1740,159,'new.png')
    assert result.size==(1740,159)
    assert result.getpixel((0,0))[:3]==(0,0,0)
    assert ff.visible(detector.return_value,ff.protect(image,'new.png',target=(1740,159)),image.size,(1740,159))
    tt._load_and_fit_tt('https://example.com/photo.png',1000,120,'new.png')
    detector.assert_called_once()


def test_grid_passes_protected_crop_to_existing_generator(monkeypatch,detector):
    from logic_grid import generate_grid_image
    import logic_grid as grid
    from models.artist import ArtistView
    artist=ArtistView(4,'Test','photo.png',False,1.,0,0)
    image=Image.new('RGB',(800,900),'white')
    monkeypatch.setattr(grid,'_fetch_grid_images_parallel',lambda *a,**kw:{4:image})
    original=grid.apply_manual_crop;seen=[]
    def capture(im,scale,x,y,*args):
        seen.append((scale,x,y));return original(im,scale,x,y,*args)
    monkeypatch.setattr(grid,'apply_manual_crop',capture)
    result=generate_grid_image([artist], None)
    assert result is not None and seen and ff.visible(detector.return_value,seen[0])


@pytest.mark.parametrize('kind',['create','restore','replace','rename'])
def test_registration_and_replacement_saved_atomically_without_touching_name_only(monkeypatch,detector,kind):
    from services import artist_service as svc
    from repositories import artist_repo as repo
    from models.artist import ArtistView
    image=Image.new('RGB',(800,900),'white');data=io.BytesIO();image.save(data,format='PNG')
    original=ArtistView(4,'Test','old.png',kind=='restore',2.,100,80)
    updated=replace(original,image_filename='new.png',is_deleted=False)
    db=Mock();monkeypatch.setattr(svc,'SessionLocal',lambda:db)
    monkeypatch.setattr(svc,'_upload_image',lambda _: 'new.png' if kind!='rename' else None)
    monkeypatch.setattr(repo,'get_artist_by_name',lambda *a:None if kind=='create' else original)
    monkeypatch.setattr(repo,'create_artist',lambda *a:updated)
    monkeypatch.setattr(repo,'restore_artist',lambda *a:updated)
    monkeypatch.setattr(repo,'update_artist',lambda *a:updated)
    crop_save=Mock(side_effect=lambda db,id,s,x,y:replace(updated,crop_scale=s,crop_x=x,crop_y=y))
    monkeypatch.setattr(repo,'update_artist_crop',crop_save)
    if kind in ('create','restore'):
        result,status=svc.create_artist('Test',data)
        assert status==('created' if kind=='create' else 'restored')
    else:
        result=svc.update_artist(4,'Test',None if kind=='rename' else data)
    db.commit.assert_called_once()
    if kind=='rename':
        crop_save.assert_not_called();detector.assert_not_called()
    else:
        crop_save.assert_called_once()
        assert ff.visible(detector.return_value,(result.crop_scale,result.crop_x,result.crop_y))
        assert result.crop_scale!=original.crop_scale


def test_concurrent_first_use_detects_once(monkeypatch,detector):
    from concurrent.futures import ThreadPoolExecutor
    image=Image.new('RGB',(800,900))
    with ThreadPoolExecutor(max_workers=8) as pool:
        results=list(pool.map(lambda _:ff.protect(image,'same.png'),range(16)))
    detector.assert_called_once()
    assert all(ff.visible(detector.return_value,result,image.size) for result in results)


def test_cached_no_face_result_does_not_repeat_detection(monkeypatch):
    call=Mock(return_value=info())
    monkeypatch.setattr(ff,'detect',call)
    image=Image.new('RGB',(800,900))
    ff.protect(image,'nofaces.png');ff.protect(image,'nofaces.png',target=(1500,120))
    call.assert_called_once()


def test_existing_name_registration_keeps_existing_photo_and_crop(monkeypatch):
    from services import artist_service as svc
    from repositories import artist_repo as repo
    from models.artist import ArtistView
    db=Mock();monkeypatch.setattr(svc,'SessionLocal',lambda:db)
    monkeypatch.setattr(svc,'_upload_image',lambda _:'new.png')
    old=ArtistView(4,'Test','old.png',False,.8,20,10)
    monkeypatch.setattr(repo,'get_artist_by_name',lambda *a:old)
    frame=Mock();monkeypatch.setattr(svc,'_frame_uploaded',frame)
    result,status=svc.create_artist('Test',io.BytesIO(b'new'))
    assert status=='exists' and result==old
    frame.assert_not_called();db.commit.assert_not_called()
