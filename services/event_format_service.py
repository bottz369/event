"""Multi-part rendering shared by the web app and LINE/API (read only)."""
import io
import json
from datetime import datetime, timedelta

from PIL import Image, ImageDraw, ImageFont, ImageOps

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


def _wrap(text, font_path, size, width):
    font = _font(font_path, size)
    lines = []
    for paragraph in str(text or "").splitlines():
        current = ""
        for char in paragraph:
            if current and font.getlength(current + char) > width:
                lines.append(current)
                current = ""
            current += char
        if current:
            lines.append(current)
    return lines


def _part_tt(part, width, font_path, split=False):
    if split:
        return _part_tt_wide(part, width, font_path)
    rows, post = schedule(part)
    live = [r for r in rows if not r.get("IS_HIDDEN")]
    items = []
    for r in live:
        items.append((f"{r['start']}–{r['end']}", r["ARTIST"], False))
        if int(r.get("ADJUSTMENT") or 0):
            items.append((f"{r['end']}–{r['change_end']}", part.get("transition_label", "転換"), True))
    items.append(("", "特典会", True))
    for r in live:
        if r["goods"]:
            place = str(r.get("PLACE") or "")
            if r.get("ADD_GOODS_PLACE"):
                place += " / " + r["ADD_GOODS_PLACE"]
            items.append((r["goods"], r["ARTIST"] + (f"  ({place})" if place else ""), False))
    if part.get("post_duration"):
        end = datetime.strptime(post, "%H:%M") + timedelta(minutes=int(part["post_duration"]))
        items.append((f"{post}–{end:%H:%M}", "終演後特典会", True))
    height = 170 + len(items) * 76 + (80 if part.get("note") else 0)
    out = Image.new("RGBA", (width, height), "#151922")
    draw = ImageDraw.Draw(out)
    draw.rectangle((0, 0, width, 72), fill=part["color"])
    _text(out, part["name"], (20, 0, width - 40, 72), font_path, 50, "#10131b", True)
    _text(out, f"OPEN {part['open_time']}  /  START {part['start_time']}",
          (20, 80, width - 40, 64), font_path, 35, part["color"], True)
    y = 160
    for timing, name, special in items:
        if special:
            draw.rectangle((10, y, width - 10, y + 70), fill="#292f3b")
        _text(out, timing, (24, y, width - 48, 26), font_path, 25, "#c8cfda")
        _text(out, name, (24, y + 26, width - 48, 46), font_path, 38,
              part["color"] if special else "white")
        y += 76
    if part.get("note"):
        _text(out, part["note"], (24, y, width - 48, 65), font_path, 28)
    return out


def _part_tt_wide(part, width, font_path):
    """Uneven lineups use stacked parts with LIVE / goods side by side."""
    rows, post = schedule(part)
    rows = [r for r in rows if not r.get("IS_HIDDEN")]
    live, goods = [], []
    for r in rows:
        live.append((f"{r['start']}–{r['end']}", r["ARTIST"], False))
        if int(r.get("ADJUSTMENT") or 0):
            live.append((f"{r['end']}–{r['change_end']}", part.get("transition_label", "転換"), True))
        if r["goods"]:
            place = str(r.get("PLACE") or "")
            if r.get("ADD_GOODS_PLACE"):
                place += " / " + r["ADD_GOODS_PLACE"]
            goods.append((r["goods"], r["ARTIST"] + (f"  ({place})" if place else ""), False))
    if part.get("post_duration"):
        end = datetime.strptime(post, "%H:%M") + timedelta(minutes=int(part["post_duration"]))
        goods.append((f"{post}–{end:%H:%M}", "終演後特典会", True))
    height = 210 + max(len(live), len(goods), 1) * 74 + (75 if part.get("note") else 0)
    out = Image.new("RGBA", (width, height), "#151922")
    draw = ImageDraw.Draw(out)
    draw.rectangle((0, 0, width, 72), fill=part["color"])
    _text(out, part["name"], (20, 0, width - 40, 72), font_path, 50, "#10131b", True)
    _text(out, f"OPEN {part['open_time']}  /  START {part['start_time']}",
          (20, 78, width - 40, 62), font_path, 42, part["color"], True)
    half = (width - 60) // 2
    for col, (label, items) in enumerate((("LIVE", live), ("特典会", goods))):
        x = 20 + col * (half + 20)
        _text(out, label, (x, 142, half, 60), font_path, 42, part["color"])
        for i, (timing, name, special) in enumerate(items):
            y = 210 + i * 74
            if special:
                draw.rectangle((x, y, x + half, y + 70), fill="#292f3b")
            _text(out, timing, (x + 10, y, half - 20, 26), font_path, 26, "#c8cfda")
            _text(out, name, (x + 10, y + 26, half - 20, 44), font_path, 40,
                  part["color"] if special else "white")
    if part.get("note"):
        _text(out, part["note"], (24, height - 75, width - 48, 65), font_path, 30)
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
    out = Image.new("RGBA", (width, height), "#151922")
    ImageDraw.Draw(out).rectangle((0, 0, width, 72), fill=part["color"])
    _text(out, part["name"], (20, 0, width - 40, 72), font_path, 50, "#10131b", True)
    _text(out, f"OPEN {part['open_time']}  /  START {part['start_time']}",
          (20, 78, width - 40, 64), font_path, 38, part["color"], True)
    if image:
        out.alpha_composite(image, (20, 150))
    else:
        _text(out, "出演者未設定", (20, 150, width - 40, 90), font_path)
    return out


def render(project, variant="tt", finished=False, failures=None):
    """Return one combined image, using project.settings without DB writes."""
    from services import font_service, asset_service
    from database import get_image_url
    from utils.flyer_generator import load_image
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
    parts = active_parts(config)
    width, gap = 2400, 28
    counts = [len(p.get("rows", [])) for p in parts]
    uneven = bool(counts and max(counts) > max(6, 2 * min(counts)))
    columns = min(3, len(parts)) if variant == "tt" and not uneven else 1
    panel_width = (width - gap * (columns + 1)) // columns
    panels = [(_part_tt(p, panel_width, path, split=uneven) if variant == "tt" else
               _part_grid(p, panel_width, path, failures)) for p in parts]
    band_heights = [max(p.height for p in panels[i:i + columns])
                    for i in range(0, len(panels), columns)]
    body_height = sum(band_heights) + gap * (len(band_heights) + 1)
    header = 500 if finished else 0
    footer_lines = []
    if finished:
        for t in project.tickets:
            footer_lines.append(f"{t.name}  {t.price}" + (f"  ({t.note})" if t.note else ""))
        footer_lines.extend(project.ticket_notes)
        footer_lines = [line for text in footer_lines for line in _wrap(text, path, 55, width - 120)]
    footer_height = 40 + 75 * len(footer_lines) if footer_lines else 0
    out = Image.new("RGBA", (width, header + body_height + footer_height), "#0c1019")
    flyer = project.flyer_settings or {}
    if finished and flyer.get("bg_id"):
        asset = asset_service.get_asset_view(flyer["bg_id"])
        bg = load_image(get_image_url(asset.image_filename)) if asset else None
        if bg:
            out = ImageOps.fit(bg.convert("RGBA"), out.size)
            out.alpha_composite(Image.new("RGBA", out.size, (0, 0, 0, 95)))
    if finished:
        logo = None
        if flyer.get("logo_id"):
            asset = asset_service.get_asset_view(flyer["logo_id"])
            logo = load_image(get_image_url(asset.image_filename)) if asset else None
        if logo:
            logo = ImageOps.contain(logo.convert("RGBA"), (1600, 260))
            out.alpha_composite(logo, ((width - logo.width) // 2, 20))
            _text(out, project.title, (50, 285, width - 100, 65), path, 65, center=True)
        else:
            _text(out, project.title, (60, 40, width - 120, 170), path, 100, center=True)
            _text(out, project.subtitle, (60, 215, width - 120, 85), path, 65, center=True)
        date_text = str(project.event_date or "").replace("-", ".")
        _text(out, date_text, (40, 355, width - 80, 60), path, 65, "#ffe328", True)
        _text(out, project.venue_name, (40, 420, width - 80, 60), path, 55, center=True)
    y = header + gap
    for i in range(0, len(panels), columns):
        for j, panel in enumerate(panels[i:i + columns]):
            out.alpha_composite(panel, (gap + j * (panel_width + gap), y))
        y += band_heights[i // columns] + gap
    for line in footer_lines:
        _text(out, line, (50, y, width - 100, 75), path, 55, center=True)
        y += 75
    if config.get("free_viewing") and finished:
        out = free_banner(out, config.get("free_text", ""), path)
    return out


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
