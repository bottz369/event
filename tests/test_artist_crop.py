from unittest.mock import Mock
from dataclasses import replace
import pytest
from PIL import Image
from models.artist import ArtistView
from services import artist_crop as crop


def artist():
    return ArtistView(5, 'Test', 'photo.png', False, 1., 0, 0)


@pytest.mark.parametrize('size', [(1200, 450), (450, 1200), (800, 450), (501, 777)])
def test_fit_keeps_all_four_corners_in_grid(size):
    from logic_grid import apply_manual_crop
    image = Image.new('RGB', size, 'white')
    scale, x, y = crop.adjust(image, (2., 100, -80), '顔が見切れないように')
    assert x == y == 0
    # Geometry matches generator's integer Cover baseline.
    w, h = size
    base_w, base_h = (int(450*w/h), 450) if w/h > 800/450 else (800, int(800*h/w))
    assert int(base_w*scale) <= 800 and int(base_h*scale) <= 450
    result = apply_manual_crop(image, scale, x, y)
    assert result.size == (800, 450)
    if w/h != 800/450:
        assert result.getpixel((0, 0))[:3] == (0, 0, 0)


def test_relative_adjustments_and_bounds():
    image = Image.new('RGB', (800, 450))
    assert crop.adjust(image, (1., 0, 0), '少し縮小して右へ') == (.9, 20, 0)
    assert crop.adjust(image, (1., 0, 0), '上30') == (1., 0, -30)
    assert crop.adjust(image, (3., 190, 0), '拡大10%右20') == (3., 200, 0)
    assert crop.adjust(image, (2., 10, 10), 'リセット') == (1., 0, 0)
    for instruction in ['好きな感じに', '縮小100%', '下999']:
        with pytest.raises(ValueError):
            crop.adjust(image, (1., 0, 0), instruction)


@pytest.mark.parametrize('changed', [False, True])
def test_save_locks_and_rejects_other_editor_change(monkeypatch, changed):
    import database
    from repositories import artist_repo
    current = artist() if not changed else replace(artist(), crop_y=10)
    db = Mock(); db.query.return_value.filter.return_value.with_for_update.return_value.first.return_value = current
    monkeypatch.setattr(database, 'SessionLocal', lambda: db)
    monkeypatch.setattr(artist_repo, '_to_view', lambda a: a)
    update = Mock(return_value=artist()); monkeypatch.setattr(artist_repo, 'update_artist_crop', update)
    if changed:
        with pytest.raises(ValueError, match='変更'):
            crop.save(5, crop.snapshot(artist()), (.8, 0, 0))
        update.assert_not_called(); db.rollback.assert_called_once(); db.commit.assert_not_called()
    else:
        crop.save(5, crop.snapshot(artist()), (.8, 0, 0))
        update.assert_called_once_with(db, 5, .8, 0, 0); db.commit.assert_called_once()
    db.close.assert_called_once()
