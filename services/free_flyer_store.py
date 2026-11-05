"""Owner-keyed, bounded image workshop drafts. No raw LINE IDs or credentials."""
import json
import re
import time
from services.intake_draft_store import _bucket

TTL=3*24*3600


def path(owner):
    if not re.fullmatch(r'[a-f0-9]{64}',owner): raise ValueError('利用者の識別情報が不正です。')
    return 'free_flyer/drafts/'+owner+'.json'


def save(owner,state):
    data=json.dumps(dict(at=time.time(),state=state),ensure_ascii=False).encode()
    if len(data)>1024*1024: raise ValueError('下書きが大きすぎます。プロジェクトに保存してください。')
    _bucket().upload(path=path(owner),file=data,file_options={'content-type':'application/json','upsert':'true'})


def load(owner):
    try:
        raw=_bucket().download(path(owner))
        if len(raw)>1024*1024:return None
        data=json.loads(bytes(raw))
        if time.time()-float(data['at'])>TTL:return None
        state=data['state']
        return state if isinstance(state,dict) and state.get('owner')==owner else None
    except Exception:return None
