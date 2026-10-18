"""Source-order and ticket normalization for AI intake, without storage or API calls."""
from copy import deepcopy
from difflib import SequenceMatcher
import re
import unicodedata


def key(value):
    return re.sub(r'\s+','',unicodedata.normalize('NFKC',str(value))).casefold()


def bare_note(value):
    """Remove whole, balanced outer pairs only; retain parentheses inside a condition."""
    text=str(value or '').strip()
    pairs={'(':')','（':'）'}
    while len(text)>=2 and text[0] in pairs and text[-1]==pairs[text[0]]:
        stack=[];whole=True
        for i,char in enumerate(text):
            if char in pairs:stack.append(pairs[char])
            elif char in pairs.values():
                if not stack or stack.pop()!=char:whole=False;break
                if not stack and i<len(text)-1:whole=False;break
        if not whole or stack:break
        text=text[1:-1].strip()
    return text


def ticket_note_text(value):
    note=bare_note(value)
    return f'({note})' if note else ''


def common_drink(value):
    text=unicodedata.normalize('NFKC',bare_note(value))
    text=re.sub(r'^[\s※*＊・]+','',text)
    if re.search(r'のみ|不要|含む|込み|対象|除く|除き|免除|VIP|チケット|撮影',text,re.I):return False
    return bool(re.match(r'^(?:各|別途)?(?:入場時)?(?:[12]?\s*ドリンク(?:代|別|必要|\s*[¥￥0-9])|[12]?\s*D(?:代|別|必要|\s*[¥￥0-9]|$))',text,re.I))


def separate_drink(value):
    text=str(value or '').strip();common=[]
    while True:
        tail=re.search(r'[（(]([^()（）]*)[）)]\s*$',text)
        if not tail or not common_drink(tail[1]):break
        common.insert(0,bare_note(tail[1]));text=text[:tail.start()].rstrip()
    split=re.split(r'(\s*(?:\r?\n|[/／、,;；])\s*)',text)
    pieces=[split[0]];depth=0
    for char in split[0]:
        if char in '(（':depth+=1
        elif char in ')）':depth=max(0,depth-1)
    for index in range(1,len(split),2):
        separator,chunk=split[index],split[index+1]
        if depth:pieces[-1]+=separator+chunk
        else:pieces.extend([separator,chunk])
        for char in chunk:
            if char in '(（':depth+=1
            elif char in ')）':depth=max(0,depth-1)
    kept=[]
    for index in range(0,len(pieces),2):
        part=pieces[index].strip()
        if not part:continue
        if common_drink(part):common.append(bare_note(part))
        else:
            if kept:kept.append(pieces[index-1])
            kept.append(part)
    return ''.join(kept).strip(),common


def overview_artists(text):
    """Read a labelled, newline-separated lineup verbatim, without trusting model order."""
    active=False;names=[]
    for raw in str(text or '').splitlines():
        line=raw.strip()
        if not active:
            heading=re.sub(r'^[■●◆◇]\s*','',line).strip('【】[]：: ')
            if re.fullmatch(r'出演者|出演アーティスト|出演グループ|出演|LINE\s*UP',heading,re.I):active=True
            continue
        if re.match(r'^[■◆◇【\[]|^※|^(?:チケット|注意事項|入場に関して|料金|会場|時間)[：:]?',line):break
        if not line:continue
        if re.match(r'https?://',line):break
        name=re.sub(r'^(?:[・●○▪]\s*|\d+[.)．]\s*)','',line).strip()
        if name:names.append(name)
    return list(dict.fromkeys(names))


def normalize_event(event,overview=None):
    result=deepcopy(event)
    original=overview_artists(overview) if overview is not None else []
    if original:result['artists']=original
    common=[line.strip() for line in str(result.get('ticket_common_note') or '').splitlines() if line.strip()]
    tickets=[]
    for entry in result.get('tickets',[]):
        ticket=deepcopy(entry)
        note,notes=separate_drink(bare_note(ticket.get('note')))
        price,price_notes=separate_drink(ticket.get('price'))
        ticket.update(note=bare_note(note),price=price)
        common.extend(notes+price_notes);tickets.append(ticket)
    clean=[];seen=set()
    for line in common:
        line=bare_note(line)
        if common_drink(line):line='※'+re.sub(r'^[\s※*＊・]+','',line)
        identity=key(re.sub(r'^[\s※*＊・]+','',line))
        if identity and identity not in seen:clean.append(line);seen.add(identity)
    result.update(tickets=tickets,ticket_common_note='\n'.join(clean))
    return result


def roster_aliases(overview,roster,aliases=None):
    """Resolve order against this event's roster, never rename registered artists.

    Unique cosmetic matches are automatic. Typo recovery requires a strong,
    reciprocal unique match; ambiguous names are returned for explicit review.
    """
    aliases=aliases or {}
    targets=list(dict.fromkeys(aliases.get(n,n) for n in roster))
    result={};used=set();ambiguous=[]
    cosmetic=lambda s:re.sub(r'[☆★]+$','',key(s))
    for name in overview:
        value=aliases.get(name,name)
        if value in targets:result[name]=value;used.add(value);continue
        candidates=[n for n in targets if key(n)==key(value)]
        if not candidates:candidates=[n for n in targets if cosmetic(n)==cosmetic(value)]
        if len(candidates)==1:result[name]=candidates[0];used.add(candidates[0])
        elif len(candidates)>1:ambiguous.append(name)
    remaining=[n for n in targets if n not in used]
    pending=[n for n in overview if n not in result and n not in ambiguous]
    proposals={}
    for name in pending:
        value=aliases.get(name,name)
        ranked=sorted(((SequenceMatcher(None,key(value),key(n)).ratio(),n) for n in remaining),reverse=True)
        if not ranked or ranked[0][0]<.88:continue
        if len(ranked)>1 and ranked[0][0]-ranked[1][0]<.12:ambiguous.append(name);continue
        proposals[name]=ranked[0]
    for name,(score,target) in proposals.items():
        competitors=[(s,n) for n,(s,t) in proposals.items() if t==target]
        if len(competitors)==1:
            result[name]=target
        else:ambiguous.extend(n for _,n in competitors)
    return result,list(dict.fromkeys(ambiguous))


def grid_order(overview,roster,aliases=None):
    aliases=aliases or {}
    mapped,ambiguous=roster_aliases(overview,roster,aliases)
    if ambiguous:raise ValueError('概要の掲載順に使う名前を一意に照合できません。登録名を確認してください：'+'、'.join(ambiguous))
    targets=list(dict.fromkeys(aliases.get(n,n) for n in roster))
    ordered=list(dict.fromkeys(mapped[n] for n in overview if n in mapped))
    unlisted=[n for n in targets if n not in ordered]
    return ordered+unlisted,dict(source='公演概要の出演者順' if overview else 'タイムテーブル出演順',
        matched=[dict(original=n,artist=mapped[n]) for n in overview if n in mapped and n!=mapped[n]],
        unlisted=unlisted if overview else [],order=ordered+unlisted)


def normalize_parts(parts,event,overview=''):
    """Fill single-session blanks only; never spread global times across sessions."""
    result=deepcopy(parts)
    if len(result)!=1:return result
    text=unicodedata.normalize('NFKC',str(overview or ''))
    for field,label in (('open_time',r'OPEN|開場'),('start_time',r'START|開演')):
        if str(result[0].get(field) or '').strip():continue
        value=str(event.get(field) or '').strip()
        if not re.fullmatch(r'(?:[01]?\d|2[0-3]):[0-5]\d',value):
            matches=re.findall(r'(?:'+label+r')[ \t:：▶▷►>→]*([0-2]?\d:[0-5]\d)(?!\d)',text,re.I)
            valid={f'{int(v.split(":")[0]):02d}:{v.split(":")[1]}' for v in matches if int(v.split(':')[0])<24}
            value=next(iter(valid)) if len(valid)==1 else ''
        if value:result[0][field]=f'{int(value.split(":")[0]):02d}:{value.split(":")[1]}'
    return result
