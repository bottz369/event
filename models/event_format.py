"""Optional multi-part event data, stored in the existing settings JSON.

Normal timetable_rows remain untouched. Disabling this format restores the
normal editor; its data and the separate multi-part draft are both retained.
"""
from copy import deepcopy
from datetime import datetime, timedelta

KEY = "event_format"
COLORS = ("#ff5364", "#ffac20", "#ffe328", "#47c8c0", "#a99bff", "#ff8cce")


def new_part(index, open_time="10:00", start_time="10:30", rows=None):
    return dict(name=f"{index + 1}部", open_time=open_time, start_time=start_time,
                color=COLORS[index % len(COLORS)], rows=deepcopy(rows or []),
                goods_offset=10, post_start="", post_prepare=10,
                post_duration=0, transition_label="転換", hide_transitions=False, note="")


def options(settings):
    value = (settings or {}).get(KEY)
    return deepcopy(value) if isinstance(value, dict) else {}


def active_parts(config):
    return config.get("parts", [])[:int(config.get("count", 2))]


def draft_rows(part):
    from models.timetable import TimetableRowDraft
    rows = []
    for raw in part.get("rows", []):
        row = TimetableRowDraft.from_dict(raw)
        # The legacy converter treats numeric zero as an absent value.
        if raw.get("DURATION") == 0:
            row.duration = 0
        if raw.get("GOODS_DURATION") == 0:
            row.goods_duration = 0
        rows.append(row)
    return rows


def summary_inputs(config, artists, notes, free_texts, open_time, start_time):
    artists, notes, free_texts = list(artists), list(notes), deepcopy(free_texts)
    if config.get("enabled"):
        parts = active_parts(config)
        artists = list(dict.fromkeys(r.get("ARTIST", "") for p in parts
            for r in p.get("rows", []) if r.get("ARTIST") and not r.get("IS_HIDDEN")))
        if parts:
            open_time, start_time = parts[0]["open_time"], parts[0]["start_time"]
        free_texts.append(dict(title="各部の時間", content="\n".join(
            f"{p['name']} OPEN {p['open_time']} / START {p['start_time']}" for p in parts)))
    if config.get("free_viewing"):
        notes.append("観覧無料" + (f"（{config['free_text']}）" if config.get("free_text") else ""))
    return dict(artists=artists, ticket_notes=notes, free_texts=free_texts,
                open_time=open_time, start_time=start_time)


def validate(config):
    if not config.get("enabled"):
        return []
    errors = []
    if not active_parts(config):
        return ["部の設定がありません。"]
    for part in active_parts(config):
        name = part.get("name") or "部"
        for field in ("open_time", "start_time"):
            try:
                datetime.strptime(part.get(field, ""), "%H:%M")
            except (ValueError, TypeError):
                errors.append(f"{name}: OPEN / START は HH:MM で入力してください。")
        if part.get("post_start"):
            try:
                datetime.strptime(part["post_start"], "%H:%M")
            except (ValueError, TypeError):
                errors.append(f"{name}: 終演後特典会の開始は HH:MM で入力してください。")
        for row in part.get("rows", []):
            if not str(row.get("ARTIST", "")).strip():
                errors.append(f"{name}: 出演者名が空の行があります。")
            for field in ("GOODS_START_MANUAL", "ADD_GOODS_START"):
                if row.get(field):
                    try:
                        datetime.strptime(row[field], "%H:%M")
                    except (ValueError, TypeError):
                        errors.append(f"{name}: 物販開始は HH:MM で入力してください。")
            if row.get("IS_POST_GOODS") and not part.get("post_duration"):
                errors.append(f"{name}: 終演後特典会の長さを設定してください。")
    return errors


def schedule(part):
    """Calculate each part independently; hidden rows still consume time."""
    current = datetime.strptime(part["start_time"], "%H:%M")
    result = []
    for raw in part.get("rows", []):
        row = deepcopy(raw)
        duration = max(0, int(row.get("DURATION") or 0))
        change = max(0, int(row.get("ADJUSTMENT") or 0))
        end = current + timedelta(minutes=duration)
        row["start"], row["end"] = current.strftime("%H:%M"), end.strftime("%H:%M")
        row["change_end"] = (end + timedelta(minutes=change)).strftime("%H:%M")
        result.append(row)
        current = end + timedelta(minutes=change)
    post = part.get("post_start") or (current + timedelta(
        minutes=int(part.get("post_prepare") or 0))).strftime("%H:%M")
    for row in result:
        start = post if row.get("IS_POST_GOODS") else (row.get("GOODS_START_MANUAL") or
            (datetime.strptime(row["end"], "%H:%M") + timedelta(
                minutes=int(part.get("goods_offset") or 0))).strftime("%H:%M"))
        duration = (part.get("post_duration") if row.get("IS_POST_GOODS")
                    else row.get("GOODS_DURATION", 60)) or 0
        end = (datetime.strptime(start, "%H:%M") + timedelta(minutes=int(duration))).strftime("%H:%M")
        row["goods"] = f"{start}–{end}" if duration else ""
        if row.get("ADD_GOODS_START"):
            extra = datetime.strptime(row["ADD_GOODS_START"], "%H:%M")
            extra_end = extra + timedelta(minutes=int(row.get("ADD_GOODS_DURATION") or 0))
            row["goods"] += f" / {extra:%H:%M}–{extra_end:%H:%M}"
    return result, post
