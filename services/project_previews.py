"""Small watermarked snapshots in existing project JSON; no rendering on browse."""
import base64
import io
import json
from datetime import datetime, timezone

from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError

KEY = '_project_preview'


class OutputStorageError(ValueError):
    """Original uploads failed before any project transaction began."""


def thumbnail(source):
    if isinstance(source, bytes):
        source = Image.open(io.BytesIO(source))
    image = source.convert('RGB')
    image.thumbnail((240, 300), Image.Resampling.LANCZOS)
    overlay = Image.new('RGBA', image.size)
    draw = ImageDraw.Draw(overlay)
    font = ImageFont.load_default(size=max(18, image.width // 8))
    text = 'preview'
    box = draw.textbbox((0, 0), text, font=font)
    x = (image.width - (box[2] - box[0])) // 2
    y = image.height // 2
    draw.rectangle((0, y - 5, image.width, y + box[3] + 5), fill=(0, 0, 0, 110))
    draw.text((x, y), text, font=font, fill=(255, 255, 255, 210))
    image = Image.alpha_composite(image.convert('RGBA'), overlay).convert('RGB')
    out = io.BytesIO()
    image.save(out, 'JPEG', quality=65, optimize=True)
    return base64.b64encode(out.getvalue()).decode('ascii')


def snapshot(images):
    result = {}
    for kind in ('grid', 'tt'):
        if images.get(kind) is not None:
            try:
                result[kind] = thumbnail(images[kind])
            except (OSError, ValueError, UnidentifiedImageError):
                continue
    return dict(version=1, generated_at=datetime.now(timezone.utc).isoformat(), images=result) if result else None


def decode(value):
    try:
        data = json.loads(value) if isinstance(value, str) else value
        data = (data or {}).get(KEY, {})
        images = data.get('images', {})
        result = {}
        for kind in ('grid', 'tt'):
            raw = images.get(kind)
            if isinstance(raw, str) and len(raw) <= 120000:
                blob = base64.b64decode(raw, validate=True)
                with Image.open(io.BytesIO(blob)) as image:
                    if image.format == 'JPEG' and image.width <= 240 and image.height <= 300:
                        image.verify()
                        result[kind] = blob
        return result
    except (ValueError, TypeError, AttributeError, OSError):
        return {}


def prepare(images):
    """Upload immutable original PNGs only on explicit generation/save, never browse."""
    import hashlib
    from database import upload_image_to_supabase
    if set(images) != {'grid', 'tt'} or any(images[k] is None for k in ('grid', 'tt')):
        raise ValueError('フライヤーセット2種が揃っていません。')
    originals = {}
    for kind in ('grid', 'tt'):
        source = images[kind]
        if isinstance(source, bytes):
            with Image.open(io.BytesIO(source)) as image:
                if image.format != 'PNG': raise ValueError('原寸画像はPNGで保存してください。')
                image.verify()
            blob = source
        else:
            out = io.BytesIO(); source.save(out, 'PNG'); blob = out.getvalue()
        filename = f"project_outputs/{hashlib.sha256(blob).hexdigest()}/{kind}.png"
        if not upload_image_to_supabase(io.BytesIO(blob), filename):
            raise OutputStorageError('ダウンロード用画像の保管に失敗しました。再度保存してください。')
        originals[kind] = filename
    payload = snapshot(images)
    payload['originals'] = originals
    return payload


def downloads(value, project_id):
    """Return small public download links, without fetching original image bytes."""
    import re
    from urllib.parse import urlencode
    from database import get_image_url
    try:
        data = json.loads(value) if isinstance(value, str) else value
        files = data.get(KEY, {}).get('originals', {})
        return {kind: get_image_url(path) + '?' + urlencode({'download': f'flyer_{project_id}_{kind}.png'})
                for kind, path in files.items() if kind in ('grid', 'tt') and isinstance(path, str)
                and re.fullmatch(r'project_outputs/[a-f0-9]{64}/' + kind + r'\.png', path)}
    except (ValueError, TypeError, AttributeError):
        return {}


def revision(project):
    """Fingerprint saved settings without generated metadata for safe one-time backfill."""
    import hashlib
    data = {c.name: getattr(project, c.name) for c in project.__table__.columns}
    flyer = json.loads(data.get('flyer_json') or '{}')
    flyer.pop(KEY, None)
    data['flyer_json'] = flyer
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()


def save(project_id, images, expected_revision=None):
    """Atomically publish thumbnails + both stored originals after saved-project rendering."""
    from database import SessionLocal
    from repositories import project_repo
    payload = prepare(images)
    db = SessionLocal()
    try:
        if expected_revision is not None:
            from database import TimetableProject
            project = db.query(TimetableProject).filter_by(id=project_id).with_for_update().first()
            if project is None or revision(project) != expected_revision:
                raise ValueError('生成後にプロジェクトが変更されたため保存を止めました。')
        else:
            project = project_repo.get_project(db, project_id)
        if project is None:
            return False
        data = json.loads(project.flyer_json or '{}')
        data[KEY] = payload
        project.flyer_json = json.dumps(data, ensure_ascii=False)
        db.commit()
        return payload
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
