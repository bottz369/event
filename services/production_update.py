"""Reviewed updates to existing productions, with appearance retention and conflict checks."""
from collections import defaultdict
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json

from models.event_format import KEY, active_parts, draft_rows
from models.timetable import seed_grid_no_from_order, seed_grid_hidden_from_settings, build_grid_order_from_rows


class ProjectChanged(ValueError):
    """The selected saved version changed; nothing has been overwritten."""


def fingerprint(project, rows):
    from services.project_previews import revision
    content = dict(project=revision(project), rows=[asdict(row) for row in rows])
    return hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def load_target(project_id):
    from database import SessionLocal
    from repositories import project_repo, timetable_repo
    db = SessionLocal()
    try:
        project = project_repo.get_project(db, project_id)
        if project is None:
            raise ValueError('更新先のプロジェクトが見つかりません。選び直してください。')
        rows = timetable_repo.load_rows(db, project_id)
        token = fingerprint(project, rows)
        draft = project_repo.to_draft(project)
        seed_grid_no_from_order(rows, draft.grid_settings.get('order', []))
        seed_grid_hidden_from_settings(rows, draft.grid_settings)
        return dict(draft=draft, rows=rows, revision=token)
    finally:
        db.close()


def ensure_current(project_id, expected_revision):
    if load_target(project_id)['revision'] != expected_revision:
        raise ProjectChanged('更新先がアプリなどで変更されています。上書きせず停止しました。「中止」して、プロジェクト更新から選び直してください。')


def _carry_display(rows, previous):
    from services.production_intake import normalized
    by_name = defaultdict(list)
    for row in previous:
        if not row.is_special_row:
            by_name[normalized(row.artist_name)].append(row)
    for row in rows:
        matches = by_name.get(normalized(row.artist_name), [])
        if not matches or row.is_special_row:
            continue
        # A repeated name must never accidentally reveal a concealed performer.
        row.is_comingsoon = any(old.is_comingsoon for old in matches)
        if len(matches) == 1:
            row.is_hidden = matches[0].is_hidden
            row.is_grid_hidden = matches[0].is_grid_hidden


def merge_plan(existing, previous_rows, incoming, rows):
    """New overview/timing is authoritative; saved appearance and masks are retained."""
    from models.event_format import options
    merged = deepcopy(existing)
    rows = deepcopy(rows)
    for field in ('title', 'subtitle', 'event_date', 'venue_name', 'venue_url', 'open_time',
                  'start_time', 'goods_start_offset', 'tickets', 'ticket_notes', 'free_texts'):
        setattr(merged, field, deepcopy(getattr(incoming, field)))
    merged.settings.update({KEY: deepcopy(incoming.settings[KEY]),
                            'production_order': deepcopy(incoming.settings.get('production_order', {}))})
    old_config = options(existing.settings)
    config = merged.settings[KEY]
    if config.get('enabled'):
        old_parts = active_parts(old_config) if old_config.get('enabled') else []
        for part in active_parts(config):
            matches = [old for old in old_parts if old.get('name') == part.get('name')]
            old_rows = draft_rows(matches[0]) if len(matches) == 1 else previous_rows
            updated = draft_rows(part)
            _carry_display(updated, old_rows)
            part['rows'] = [row.to_legacy_dict() for row in updated]
        if config['parts']:
            from services.timetable_pdf_service import normal_rows_from_part
            rows = normal_rows_from_part(config['parts'][0])
    else:
        # When reducing a multi-part event, retain concealment from every previous part.
        old_rows = ([row for part in active_parts(old_config) for row in draft_rows(part)]
                    if old_config.get('enabled') else previous_rows)
        _carry_display(rows, old_rows)
    merged.grid_settings['order'] = build_grid_order_from_rows(rows)
    merged.flyer_settings.pop('_project_preview', None)
    return merged, rows


def persist_update(draft, rows, images, expected_revision):
    """Publish updated settings, rows and both originals in one transaction."""
    from database import SessionLocal, TimetableProject
    from repositories import project_repo, timetable_repo
    from services.project_previews import prepare, KEY as PREVIEW_KEY
    if draft.id is None or not expected_revision:
        raise ValueError('更新先と確認済みの版が必要です。')
    # Upload immutable originals before opening a DB transaction. Upload failure cannot overwrite.
    payload = prepare(images)
    db = SessionLocal()
    try:
        project = db.query(TimetableProject).filter(
            TimetableProject.id == draft.id).with_for_update().first()
        if project is None or fingerprint(project, timetable_repo.load_rows(db, draft.id)) != expected_revision:
            raise ProjectChanged('更新先が変更されたため保存を止めました。「中止」して、プロジェクト更新から選び直してください。')
        project_repo.apply_draft(project, draft, rows=rows)
        if not timetable_repo.save_rows(db, draft.id, rows, commit=False):
            raise ValueError('タイムテーブルを更新できませんでした。')
        flyer = json.loads(project.flyer_json or '{}')
        flyer[PREVIEW_KEY] = payload
        project.flyer_json = json.dumps(flyer, ensure_ascii=False)
        db.commit()
        return draft.id
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
