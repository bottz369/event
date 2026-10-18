"""Multi-part rendering shared by the web app and LINE/API (read only)."""
import io
import json
from datetime import datetime, timedelta

from PIL import Image, ImageDraw, ImageFont

from models.event_format import active_parts, options, schedule, validate, draft_rows


def _font(path, size):
    return ImageFont.truetype(path, size)


def _text(canvas, text, box, path, size=42, fill="white", center=False):
    x, y, w, h = box
    draw = ImageDraw.Draw(canvas)
    font = _font(path, size)
    while size > 12 and draw.textbbox((0, 0), str(text), font=font)[2] > w:
        size -= 1
        font = _font(path, size)
    draw.text((x + (w / 2 if center else 0), y + h / 2), str(text),
              font=font, fill=fill, anchor="mm" if center else "lm")


def free_banner(image, text, font_path):
    """Append a dedicated band; never cover existing tickets or artwork."""
    width = image.width
    height = max(120, round(width * .15))
    out = Image.new("RGBA", (width, image.height + height), "#151922")
    out.paste(image.convert("RGBA"), (0, 0))
    _text(out, "観覧無料", (20, image.height + 4, width - 40, height * .58),
          font_path, round(width * .06), "#ffe328", True)
    _text(out, text or "", (20, image.height + height * .57, width - 40, height * .37),
          font_path, round(width * .028), "white", True)
    return out


def _part_grid(part, width, font_path, failures):
    from services import artist_service
    from logic_grid import generate_grid_image
    rows = draft_rows(part)
    rows = [r for r in rows if not r.is_grid_hidden and not r.is_special_row]
    rows.sort(key=lambda r: r.grid_no if r.grid_no is not None else float("inf"))
    artists = artist_service.resolve_artists_in_order([r.artist_name for r in rows], failures=failures)
    image = None
    if artists:
        counts = [min(5, len(artists) - i) for i in range(0, len(artists), 5)]
        image = generate_grid_image(artists, "", font_path=font_path, row_counts=counts,
                                    alignment="left", failures=failures)
    if image:
        image = image.convert("RGBA")
        target_width = round((width - 40) * min(5, len(artists)) / 5)
        image = image.resize((target_width, max(1, round(image.height * target_width / image.width))))
    height = 160 + (image.height if image else 100)
    out = Image.new("RGBA", (width, height))
    ImageDraw.Draw(out).rectangle((0, 0, width, 72), fill=part["color"])
    _text(out, part["name"], (20, 0, width - 40, 72), font_path, 50, "#10131b", True)
    _text(out, f"OPEN {part['open_time']}  /  START {part['start_time']}",
          (20, 78, width - 40, 64), font_path, 38, part["color"], True)
    if image:
        out.alpha_composite(image, (20, 150))
    else:
        _text(out, "出演者未設定", (20, 150, width - 40, 90), font_path)
    return out


def timetable_rows(part):
    """Adapt independent part timing to the regular photo-row renderer."""
    rows, post = schedule(part)
    result = []
    for row in rows:
        if row.get("IS_HIDDEN"):
            continue
        places = str(row.get("PLACE") or "")
        if row.get("ADD_GOODS_START"):
            places += " / " + str(row.get("ADD_GOODS_PLACE") or "")
        result.append((f"{row['start']} - {row['end']}", row["ARTIST"],
                       row["goods"].replace("–", " - "), places))
        if int(row.get("ADJUSTMENT") or 0):
            result.append((f"{row['end']} - {row['change_end']}",
                           part.get("transition_label") or "転換", "", ""))
    if part.get("post_duration"):
        end = datetime.strptime(post, "%H:%M") + timedelta(minutes=int(part["post_duration"]))
        result.append((f"{post} - {end:%H:%M}", "終演後物販", "", ""))
    return result


def compose_flyer(project, source, variant, failures=None):
    """Use exactly the regular flyer compositor and persisted editor settings."""
    from services import font_service, asset_service
    from database import get_image_url
    from models.flyer_keys import FLYER_KEY_REGISTRY
    from utils.flyer_generator import create_flyer_image_shadow
    from utils.flyer_helpers import format_event_date
    cfg = options(project.settings)
    saved = project.flyer_settings or {}
    styles = {e.short_key: saved.get(e.short_key, e.default)
              for e in FLYER_KEY_REGISTRY if e.persist}
    for key in list(styles):
        if key.endswith("_font") and styles[key]:
            styles[key] = font_service.ensure_font_path(styles[key]) or styles[key]
    styles.update(event_multipart=True, event_free_viewing=cfg.get("free_viewing", False),
                  event_free_text=cfg.get("free_text", ""),
                  event_free_notices=cfg.get("free_notices", ""),
                  content_scale_w=styles[f"{variant}_scale_w"],
                  content_scale_h=styles[f"{variant}_scale_h"],
                  content_pos_y=styles[f"{variant}_pos_y"])
    def asset_url(field):
        asset = asset_service.get_asset_view(styles[field]) if styles.get(field) else None
        return get_image_url(asset.image_filename) if asset else None
    fallback = font_service.ensure_font_path(styles["fallback_font"])
    return create_flyer_image_shadow(
        bg_source=asset_url("bg_id"), logo_source=asset_url("logo_id"), main_source=source,
        styles=styles, date_text=format_event_date(project.event_date, styles["date_format"]),
        venue_text=project.venue_name, subtitle_text=project.subtitle,
        open_time="", start_time="", ticket_info_list=[t.to_dict() for t in project.tickets],
        common_notes_list=project.ticket_notes, system_fallback_filename=fallback,
        failures=failures)


def render(project, variant="tt", finished=False, failures=None):
    from services import font_service
    from logic_timetable import generate_timetable_image
    config = options(project.settings)
    if variant not in ("tt", "grid"):
        raise ValueError("variant must be tt or grid")
    if not config.get("enabled"):
        raise ValueError("複数部の設定が有効ではありません。")
    errors = validate(config)
    if errors:
        raise ValueError("\n".join(errors))
    path = font_service.ensure_font_path(project.settings.get("tt_font") or "keifont.ttf")
    if not path:
        raise ValueError("日本語フォントを取得できませんでした。")
    width, gap = 2400, 28
    panels = []
    for part in active_parts(config):
        if variant == "grid":
            panels.append(_part_grid(part, width - gap * 2, path, failures))
            continue
        data = timetable_rows(part)
        columns = int(project.settings.get("tt_columns") or 2)
        cols = 2 if len(data) >= 24 else columns
        rows_per_col = max(1, (len(data) + cols - 1) // cols)
        source_width = 2800 if cols == 1 else 3600
        if data:
            image = generate_timetable_image(data, font_path=path, columns=cols, failures=failures,
                                              canvas_height=rows_per_col * 148)
        else:
            # The regular empty-table fallback is opaque black. Do not composite it
            # into an empty part: it can overlap independently positioned tickets.
            image = Image.new("RGBA", (source_width, 148))
        body_height = max(1, round(image.height * (width - gap * 2) / source_width))
        note_height = max(80, len(part["note"].splitlines()) * 42 + 16) if part.get("note") else 0
        panel = Image.new("RGBA", (width - gap * 2, 160 + body_height + note_height))
        ImageDraw.Draw(panel).rectangle((0, 0, panel.width, 70), fill=part["color"])
        ImageDraw.Draw(panel).rectangle((0, 72, panel.width - 1, 152), fill=(0, 0, 0, 160))
        _text(panel, part["name"], (20, 0, panel.width - 40, 70), path, 50, "#10131b", True)
        _text(panel, f"OPEN {part['open_time']} / START {part['start_time']}",
              (20, 78, panel.width - 40, 64), path, 42, part["color"], True)
        panel.alpha_composite(image.resize((panel.width, body_height), Image.Resampling.LANCZOS), (0, 160))
        if part.get("note"):
            _text(panel, part["note"], (20, 160 + body_height, panel.width - 40, note_height), path, 34)
        panels.append(panel)
    out = Image.new("RGBA", (width, sum(p.height for p in panels) + gap * (len(panels) + 1)))
    y = gap
    for panel in panels:
        out.alpha_composite(panel, (gap, y))
        y += panel.height + gap
    return compose_flyer(project, out, variant, failures)[0] if finished else out


def png(image):
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def project_from_db(project_id):
    from database import SessionLocal
    from repositories import project_repo
    db = SessionLocal()
    try:
        project = project_repo.get_project(db, project_id)
        if project is None:
            return None
        try:
            config = options(json.loads(project.settings_json or "{}"))
        except (ValueError, TypeError):
            config = {}
        if not (config.get("enabled") or config.get("free_viewing")):
            return None
        return project_repo.to_draft(project)
    finally:
        db.close()
