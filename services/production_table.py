"""Strict single-sheet timetable extraction from named Excel-export columns.

No guessing: multi-part/multi-sheet or unrecognized layouts retain the AI route.
Only explicitly mapped columns are read; dressing rooms and trailing dates are ignored.
"""
import re
import unicodedata


def _key(value):return re.sub(r'\s+','',unicodedata.normalize('NFKC',str(value))).casefold()


def _clock(value):
    text=unicodedata.normalize('NFKC',value).strip()
    match=re.fullmatch(r'([01]?\d|2[0-3]):([0-5]\d)(?::00)?',text)
    return f'{int(match[1]):02d}:{match[2]}' if match else ''


def single_table(text):
    lines=str(text).splitlines()
    if sum(line.startswith('シート: ') for line in lines)!=1:return None
    # Explicit part markers mean we cannot safely treat this as a single session.
    if any(re.search(r'(?:第\s*)?[1-6１-６]\s*部',line) for line in lines):return None
    aliases=dict(artist={'グループ名','アーティスト','アーティスト名','出演者'},
                 start={'start','出演開始'},end={'end','出演終了'},
                 goods_start={'物販開始'},goods_end={'物販終了'},place={'物販場所'})
    header=None;rows=[]
    for line in lines:
        cells=line.split('\t')
        keys=[_key(c) for c in cells]
        found={name:[i for i,key in enumerate(keys) if key in labels] for name,labels in aliases.items()}
        if all(len(found[k])==1 for k in aliases):
            if header is not None:return None
            allowed=set().union(*aliases.values())|{'持ち時間','物販時間','控室','人数','日付',''}
            if any(key not in allowed for key in keys):return None
            header={k:v[0] for k,v in found.items()};continue
        if header is None:continue
        values={k:cells[i].strip() if i<len(cells) else '' for k,i in header.items()}
        if not any(values.values()):continue
        if any('終演後' in c for c in cells):return None
        mapped=set(header.values())
        if any(_clock(c) for i,c in enumerate(cells) if i not in mapped):return None
        name=values['artist']
        start,end=_clock(values['start']),_clock(values['end'])
        if not name or not start or not end:return None
        if name in ('調整','転換','休憩'):
            if any(values[k] for k in ('goods_start','goods_end','place')):return None
            continue
        gs,ge=values['goods_start'],values['goods_end']
        if bool(gs)!=bool(ge) or (gs and not(_clock(gs) and _clock(ge))):return None
        rows.append(dict(artist=name,start=start,end=end,goods_start=_clock(gs),goods_end=_clock(ge),
            place=values['place'],post_goods=False,add_start='',add_end='',add_place='',evidence=line))
    if header is None or not rows:return None
    return dict(name='1部',open_time='',start_time='',post_start='',post_end='',note='',transition_label='転換',rows=rows)
