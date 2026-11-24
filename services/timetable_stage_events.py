"""Optional stage notices anchored before performances, without moving live slots."""
from datetime import datetime, timedelta

KEY = 'tt_stage_events'


def add_stage_events(table, events=None):
    if not events:
        return table
    configured = {}
    for entry in events:
        artist = str(entry.get('before_artist') or '').strip()
        label = str(entry.get('label') or '').strip()
        minutes = entry.get('minutes')
        if not artist or not label or isinstance(minutes, bool) or not isinstance(minutes, int) or not 1 <= minutes <= 60:
            raise ValueError('進行枠の出演者・表示名・時間を確認してください。')
        if artist in configured:
            raise ValueError('同じ出演者の前に進行枠が重複しています。')
        configured[artist] = (label, minutes)
    result = []
    previous_end = None
    for row in table:
        timing, artist = row[0], row[1]
        if not timing or ' - ' not in timing:
            result.append(row)
            continue
        start_text, end_text = timing.split(' - ', 1)
        start = datetime.strptime(start_text, '%H:%M')
        end = datetime.strptime(end_text, '%H:%M')
        if artist in configured:
            label, minutes = configured[artist]
            notice_start = start - timedelta(minutes=minutes)
            if previous_end is not None and notice_start < previous_end:
                raise ValueError(f'{artist}: 進行枠が前の出演時間と重なっています。')
            result.append([f'{notice_start:%H:%M} - {start:%H:%M}', label, '', ''])
        result.append(row)
        previous_end = end
    return result
