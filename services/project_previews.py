"""Small watermarked snapshots in existing project JSON; no rendering on browse."""
import base64
import io
import json
from datetime import datetime, timezone

from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError

KEY = '_project_preview'


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


def save(project_id, images):
    """Save only the thumbnail key after an explicit saved-project render."""
    from database import SessionLocal
    from repositories import project_repo
    payload = snapshot(images)
    if not payload:
        return False
    db = SessionLocal()
    try:
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
