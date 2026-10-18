"""Read the Excel-exported multipart timetable format, without DB or network writes."""
from copy import deepcopy
import io
import re
import unicodedata

from models.event_format import new_part, schedule
from models.timetable import TimetableRowDraft

TIME = r"\d{1,2}:\d{2}"
RANGE = re.compile(rf"(?P<start>{TIME})\s*[-–－〜~]\s*(?P<end>{TIME})")
ARTIST = re.compile(rf"^\s*(?P<start>{TIME})\s*[-–－〜~]\s*(?P<end>{TIME})\s+"
                    r"\d+\s*[】\]]\s*\(\s*\d+\s*人\s*\)\s*(?P<name>.+?)\s*"
                    r"\(\s*(?P<minutes>\d+)\s*\)(?P<goods>.*)$")
HEADER = re.compile(r"^\s*(\d+)\s*部(?:\s|$)")


def _minute(text):
    hour, minute = map(int, text.split(":"))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("PDFに正しくない時刻があります。")
    return hour * 60 + minute


def _clock(text):
    value = _minute(text)
    return f"{value // 60:02d}:{value % 60:02d}"


def _duration(start, end):
    value = _minute(end) - _minute(start)
    if value < 0:
        raise ValueError("日付をまたぐ時間帯には未対応です。時間を確認してください。")
    return value


def parse_layout(text):
    """Column-aware parser for the supplied format; dressing-room times never enter rows."""
    lines = [unicodedata.normalize("NFKC", line) for line in text.splitlines()]
    markers = [line.index("並行") for line in lines if ARTIST.match(line) and "並行" in line]
    if not markers:
        # Post-show-only lineups use the same right-hand goods column.
        markers = [line.index("終演後特典会") for line in lines
                   if ARTIST.match(line) and "終演後特典会" in line]
    if not markers:
        raise ValueError("対応形式の出演者・物販欄を読み取れませんでした。画像だけのPDFや別形式の表には未対応です。")
    goods_x = min(markers)
    dressing_headers = [line.index("控室") for line in lines if "控室" in line]
    # Split the space between the goods label and the centered 控室 label.
    dressing_x = (goods_x + min(dressing_headers)) // 2 if dressing_headers else None
    parts, warnings = [], []
    part = None
    pending_number = None
    pending_notes = []
    source_rows = []
    last_row = None
    header_note = False
    for line in lines:
        header = HEADER.match(line)
        if header:
            pending_number = int(header[1])
            part = None
            header_note = False
            pending_notes = []
            if "公開リハ" in line:
                pending_notes.append(line[goods_x:].strip())
        if pending_number is not None and "START" in line:
            before, after = line.split("START", 1)
            openings = re.findall(TIME, before)
            starting = re.search(TIME, after)
            if not openings or not starting:
                raise ValueError(f"{pending_number}部のOPEN / STARTを読み取れませんでした。")
            if pending_number != len(parts) + 1:
                raise ValueError("部の番号が連続していません。複数ページで同じ部が続く形式には未対応です。")
            part = new_part(len(parts), _clock(openings[-1]), _clock(starting[0]))
            part.update(post_prepare=0, goods_offset=0, transition_label="転換")
            part["note"] = "\n".join(pending_notes)
            parts.append(part)
            source_rows = []
            part["_source"] = source_rows
            pending_number = None
            header_note = True
            last_row = None
        if part is None:
            continue
        row_match = ARTIST.match(line)
        if row_match:
            header_note = False
            start, end = _clock(row_match["start"]), _clock(row_match["end"])
            duration = _duration(start, end)
            if duration != int(row_match["minutes"]):
                raise ValueError(f"{part['name']}: 出演時間と分数が一致しません（{row_match['name'].strip()}）。")
            goods = row_match["goods"].split("控室", 1)[0]
            location = re.search(r"並行\s*([^\s※]+)", goods)
            row = TimetableRowDraft(artist_name=row_match["name"].strip(), duration=duration,
                goods_duration=0, place=location[1] if location else "",
                is_post_goods="終演後特典会" in goods).to_legacy_dict()
            if not location and not row["IS_POST_GOODS"]:
                raise ValueError(f"{part['name']}: 物販形式を読み取れません（{row['ARTIST']}）。")
            part["rows"].append(row)
            source_rows.append((start, end))
            last_row = row
            if "※" in goods:
                warnings.append(f"{part['name']} / {row['ARTIST']}: {goods[goods.index('※'):].strip()}（物販時刻と場所はそのまま取り込みます）")
            continue
        ranges = list(RANGE.finditer(line))
        if ranges and ranges[0].start() < goods_x // 2 and re.search(r"\d+\s*[】\]]", line[ranges[0].end():]):
            raise ValueError(f"{part['name']}: 読み取れない出演者行があります。人数・分数を含む表の形式を確認してください。")
        # Only the right-hand goods column before 控室 may supply goods times.
        if last_row is not None and not last_row["IS_POST_GOODS"]:
            right_limit = dressing_x
            goods_times = [m for m in ranges if goods_x - 2 <= m.start()
                           and (right_limit is None or m.start() < right_limit)]
            for timing in goods_times:
                if not last_row["GOODS_START_MANUAL"]:
                    last_row["GOODS_START_MANUAL"] = _clock(timing["start"])
                    last_row["GOODS_DURATION"] = _duration(timing["start"], timing["end"])
                elif not last_row["ADD_GOODS_START"]:
                    last_row["ADD_GOODS_START"] = _clock(timing["start"])
                    last_row["ADD_GOODS_DURATION"] = _duration(timing["start"], timing["end"])
                    last_row["ADD_GOODS_PLACE"] = last_row["PLACE"]
                else:
                    raise ValueError("3枠以上の物販には未対応です。取り込み結果を確認してください。")
        stage = ranges[0] if ranges and ranges[0].start() < goods_x // 2 else None
        if stage:
            label = line[stage.end():].strip()
            if label.startswith("終演後特典会"):
                part["post_start"] = _clock(stage["start"])
                part["post_duration"] = _duration(stage["start"], stage["end"])
                last_row = None
            elif label.startswith("特典会準備"):
                part["post_prepare"] = _duration(stage["start"], stage["end"])
                last_row = None
            elif "VIP" in label and "入れ替え" in label:
                part["transition_label"] = "VIP入れ替え"
            elif not part["rows"] and "VIP" in label:
                part["note"] = (part["note"] + "\n" + f"{_clock(stage['start'])}–{_clock(stage['end'])} {label.split('(')[0].strip()}").strip()
        elif header_note and "公開リハ" in line:
            note = line[line.index("公開リハ"):].strip() if not re.search(TIME, line[goods_x:]) else line[goods_x:].strip()
            if note and note not in part["note"]:
                part["note"] = (part["note"] + "\n" + note).strip()
    if pending_number is not None:
        raise ValueError(f"{pending_number}部のOPEN / STARTを読み取れませんでした。")
    if not 2 <= len(parts) <= 6:
        raise ValueError("現在は今回の形式の2〜6部構成PDFに対応しています。")
    if sum(len(part["rows"]) for part in parts) > 500:
        raise ValueError("出演者は500行以内にしてください。")
    for part in parts:
        source = part.pop("_source")
        if not source:
            raise ValueError(f"{part['name']}: 出演者を読み取れませんでした。")
        if source[0][0] != part["start_time"]:
            raise ValueError(f"{part['name']}: STARTと最初の出演開始時刻が一致しません。")
        for index, row in enumerate(part["rows"]):
            if index + 1 < len(source):
                row["ADJUSTMENT"] = _duration(source[index][1], source[index + 1][0])
            if row["IS_POST_GOODS"] and not part["post_duration"]:
                raise ValueError(f"{part['name']}: 終演後特典会の時間を読み取れませんでした。")
            if not row["IS_POST_GOODS"] and not row["GOODS_START_MANUAL"]:
                raise ValueError(f"{part['name']}: {row['ARTIST']}の物販時刻を読み取れませんでした。")
        # Mechanical parity check: the app must reproduce every source stage time.
        calculated, _ = schedule(part)
        if [(row["start"], row["end"]) for row in calculated] != source:
            raise ValueError(f"{part['name']}: アプリの再計算とPDFの時刻が一致しません。")
    return dict(parts=parts, warnings=list(dict.fromkeys(warnings)))


def read_pdf(data):
    if not data or len(data) > 10 * 1024 * 1024:
        raise ValueError("PDFは10MB以下のファイルを選択してください。")
    from pypdf import PdfReader
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise ValueError("パスワード付きPDFには未対応です。")
        if len(reader.pages) > 10:
            raise ValueError("PDFは10ページ以内にしてください。")
        text = "\n".join(page.extract_text(extraction_mode="layout") or "" for page in reader.pages)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("PDFを開けませんでした。別のPDFを選択してください。") from exc
    return parse_layout(text)


def match_artists(result, registered_names):
    """Only unique whitespace/case-normalized matches; never guess by substrings."""
    def key(name):
        return "".join(unicodedata.normalize("NFKC", name).split()).casefold()
    by_key = {}
    for name in registered_names:
        by_key.setdefault(key(name), set()).add(name)
    result = deepcopy(result)
    unmatched = []
    for part in result["parts"]:
        for row in part["rows"]:
            matches = by_key.get(key(row["ARTIST"]), set())
            if len(matches) == 1:
                row["ARTIST"] = next(iter(matches))
            else:
                unmatched.append(row["ARTIST"])
    result["unmatched"] = list(dict.fromkeys(unmatched))
    return result


def select_parts(result, indices):
    """Select source indices in PDF order, without changing the parsed preview."""
    selected = set(indices)
    if not selected or any(not isinstance(i, int) or i < 0 or i >= len(result["parts"]) for i in selected):
        raise ValueError("読み込む部を1つ以上選択してください。")
    if len(selected) > 6:
        raise ValueError("読み込む部は6部以内で選択してください。")
    return [deepcopy(part) for i, part in enumerate(result["parts"]) if i in selected]


def normal_rows_from_part(part):
    """Adapt one selected part to the normal editor, preserving explicit goods times."""
    from models.timetable import POST_GOODS_ARTIST_NAME
    from models.event_format import draft_rows
    rows = draft_rows(part)
    _, post_start = schedule(part)
    for row in rows:
        if row.is_post_goods:
            row.goods_start_time = post_start
            row.goods_duration = int(part.get("post_duration") or 0)
    if any(row.is_post_goods for row in rows):
        rows.append(TimetableRowDraft(artist_name=POST_GOODS_ARTIST_NAME, duration=0,
            goods_start_time=post_start, goods_duration=int(part.get("post_duration") or 0), place=""))
    return rows
