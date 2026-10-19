"""Shared crop math and optimistic artist-management save for LINE adjustments."""
import math
import re


def snapshot(artist):
    return (artist.name, artist.image_filename, artist.is_deleted,
            artist.crop_scale, artist.crop_x, artist.crop_y)


def adjust(image, current, instruction):
    """Use the exact grid coordinate space. Never invent or redraw image pixels."""
    from logic_grid import TILE_WIDTH, TILE_HEIGHT
    scale, x, y = current
    text = instruction.strip()
    if re.search(r'リセット|元に戻', text):
        return 1.0, 0, 0
    if re.search(r'全体|見切れ|顔.*(?:切れ|収ま|入)|切れない', text):
        ratio = image.width / image.height
        if ratio > TILE_WIDTH / TILE_HEIGHT:
            base_w, base_h = int(TILE_HEIGHT * ratio), TILE_HEIGHT
        else:
            base_w, base_h = TILE_WIDTH, int(TILE_WIDTH / ratio)
        fit = min(TILE_WIDTH / base_w, TILE_HEIGHT / base_h)
        if fit < .1:
            raise ValueError('極端に縦長・横長の画像です。アプリで元画像を確認してください。')
        return min(1., fit), 0, 0
    zoom = re.search(r'(縮小|拡大)(?:\s*(\d+(?:\.\d+)?)\s*[%％]?)?', text)
    move = re.search(r'(左|右|上|下)(?:\s*(\d+)\s*(?:px|ピクセル)?)?', text)
    if not zoom and not move:
        raise ValueError('「全体を収める」「縮小10%」「右20」「上20」「リセット」で調整できます。')
    if zoom:
        amount = float(zoom[2] or 10)
        if not 0 < amount <= 90:
            raise ValueError('拡大・縮小は1〜90%で指定してください。')
        scale *= 1 + amount / 100 * (1 if zoom[1] == '拡大' else -1)
    if move:
        amount = int(move[2] or 20)
        if amount > 200:
            raise ValueError('移動量は200以下で指定してください。')
        direction = move[1]
        x += amount * (1 if direction == '右' else -1 if direction == '左' else 0)
        y += amount * (1 if direction == '下' else -1 if direction == '上' else 0)
    return max(.1, min(3., scale)), max(-200, min(200, x)), max(-112, min(112, y))


def save(artist_id, expected, crop):
    from database import Artist, SessionLocal
    from repositories import artist_repo
    if not (len(crop) == 3 and all(math.isfinite(v) for v in crop)
            and .1 <= crop[0] <= 3 and -200 <= crop[1] <= 200 and -112 <= crop[2] <= 112):
        raise ValueError('配置値が範囲外です。')
    db = SessionLocal()
    try:
        artist = db.query(Artist).filter(Artist.id == artist_id).with_for_update().first()
        if not artist or snapshot(artist_repo._to_view(artist)) != expected or artist.is_deleted:
            raise ValueError('アー写または配置が別の操作で変更されました。新しく依頼してください。')
        result = artist_repo.update_artist_crop(db, artist_id, *crop)
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
