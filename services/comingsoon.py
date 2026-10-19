"""Public artist masking without changing artist registrations or timetable timing."""
from PIL import Image, ImageDraw, ImageFont
from models.artist import ArtistView


def resolve_public_artists(order, rows, failures=None):
    from services import artist_service
    hidden = {r.artist_name for r in rows if r.is_comingsoon and not r.is_special_row}
    visible = iter(artist_service.resolve_artists_in_order(
        [name for name in order if name not in hidden], failures=failures))
    return [ArtistView(0, 'comingsoon', None, False, 1.0, 0, 0, True)
            if name in hidden else next(visible) for name in order]


def placeholder(width, height, font_path):
    image = Image.new('RGB', (width, height), 'black')
    draw = ImageDraw.Draw(image)
    size = max(12, round(height * .18))
    font = ImageFont.truetype(font_path, size) if font_path else ImageFont.load_default()
    while size > 12 and draw.textbbox((0, 0), 'comingsoon', font=font)[2] > width * .9:
        size -= 1
        font = ImageFont.truetype(font_path, size) if font_path else ImageFont.load_default()
    draw.text((width / 2, height / 2), 'comingsoon', font=font, fill='white', anchor='mm')
    return image


def project_slots(project_id):
    from database import SessionLocal
    from repositories import project_repo, timetable_repo
    from models.event_format import options, active_parts
    db = SessionLocal()
    try:
        project = project_repo.get_project(db, project_id)
        if project is None:
            raise ValueError('プロジェクトが見つかりません。')
        draft = project_repo.to_draft(project)
        config = options(draft.settings)
        if config.get('enabled'):
            from models.event_format import draft_rows
            return [dict(part=p, index=i, artist=row.artist_name,
                         label=f"{part['name']} / {row.artist_name}", enabled=row.is_comingsoon)
                    for p, part in enumerate(active_parts(config))
                    for i, row in enumerate(draft_rows(part)) if not row.is_special_row]
        return [dict(part=None, index=i, artist=row.artist_name,
                     label=row.artist_name, enabled=row.is_comingsoon)
                for i, row in enumerate(timetable_repo.load_rows(db, project_id))
                if not row.is_special_row]
    finally:
        db.close()


def set_project_slot(project_id, slot, enabled):
    """Change only display metadata in one locked transaction; no row replacement."""
    import json
    from database import SessionLocal, TimetableProject
    from repositories import timetable_repo
    from models.event_format import options, active_parts, KEY
    db = SessionLocal()
    try:
        project = db.query(TimetableProject).filter(
            TimetableProject.id == project_id).with_for_update().first()
        if project is None:
            raise ValueError('プロジェクトが見つかりません。')
        settings = json.loads(project.settings_json or '{}')
        config = options(settings)
        if config.get('enabled'):
            part_index = slot['part']
            parts = active_parts(config)
            if not isinstance(part_index, int) or not 0 <= part_index < len(parts):
                raise ValueError('部の構成が変わりました。もう一度選択してください。')
            rows = parts[part_index]['rows']
            index = slot['index']
            if not 0 <= index < len(rows) or rows[index].get('ARTIST') != slot['artist']:
                raise ValueError('出演順が変わりました。もう一度選択してください。')
            rows[index]['COMINGSOON'] = bool(enabled)
            settings[KEY] = config
        else:
            if slot['part'] is not None:
                raise ValueError('部の構成が変わりました。もう一度選択してください。')
            rows = timetable_repo.load_rows(db, project_id)
            index = slot['index']
            if not 0 <= index < len(rows) or rows[index].artist_name != slot['artist'] or rows[index].is_special_row:
                raise ValueError('出演順が変わりました。もう一度選択してください。')
            rows[index].is_comingsoon = bool(enabled)
            settings['comingsoon_rows'] = [dict(index=i, artist=r.artist_name)
                                          for i, r in enumerate(rows) if r.is_comingsoon]
        project.settings_json = json.dumps(settings, ensure_ascii=False)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
