"""Bounded layout refinement using the real renderer's glyph geometry, no paid calls."""
from copy import deepcopy
import math

HEADERS=('logo','subtitle','date','venue','time')
FOOTERS=('ticket_name','free_viewing','free_note','free_notice','ticket_note')


def union(items):
    if not items:return None
    return dict(left=min(b['left'] for b in items),right=max(b['right'] for b in items),
                top=min(b['top'] for b in items),bottom=max(b['bottom'] for b in items))


def overlap(a,b,gap=0):
    return a['left']<b['right']+gap and b['left']<a['right']+gap and a['top']<b['bottom']+gap and b['top']<a['bottom']+gap


def issues(meta):
    boxes=meta.get('bounds',{})
    errors=[]
    flat=[(key,b) for key,values in boxes.items() for b in values]
    for key,b in flat:
        if b.get('font_size',12)<12:errors.append(key+'：文字が小さすぎます')
        if b['left']<0 or b['top']<0 or b['right']>1080 or b['bottom']>1350:errors.append(key+'：画像外')
    for i,(key,a) in enumerate(flat):
        for other,b in flat[i+1:]:
            if overlap(a,b):errors.append(key+'／'+other+'：重なり')
    return list(dict.fromkeys(errors))


def fit(args,zone=None,row_count=0,columns=2,grid_rows=0):
    """Keep fonts/colors, fit header/footer first, then aspect-fit the changing content."""
    from utils.flyer_generator import create_flyer_image_shadow
    styles=deepcopy(args['styles']);original=deepcopy(styles);args={**args,'styles':styles}
    def render():return create_flyer_image_shadow(**args)
    image,meta=render()
    if not meta.get('bounds'):raise ValueError('配置の検査情報を取得できませんでした。')
    def group(key):return union(meta['bounds'].get(key,[]))
    def move(key,y):
        nonlocal image,meta
        box=group(key)
        if box:
            styles[key+'_pos_y']=round(styles.get(key+'_pos_y',0)+box['top']-y)
            image,meta=render()
    def shrink(key):
        size=styles.get(key+'_size',40)
        minimum=max(12,round(original.get(key+'_size',size)*.65))
        if size<=minimum:return False
        styles[key+'_size']=max(minimum,round(size*.9));return True
    # Resolve horizontal overflow and changed subtitle/venue widths before stacking.
    for _ in range(10):
        changed=False
        for key in HEADERS:
            b=group(key)
            if not b:continue
            if key=='logo':
                if b['left']<20 or b['right']>1060 or b['top']<20:
                    styles['logo_scale']=max(.1,styles.get('logo_scale',1)*.9)
                    styles['logo_pos_x']=0.;styles['logo_pos_y']=0.;changed=True
            elif b['left']<20 or b['right']>1060:
                if b['right']-b['left']>1040:changed=shrink(key) or changed
                else:
                    shift=max(0,20-b['left'])-max(0,b['right']-1060)
                    styles[key+'_pos_x']=round(styles.get(key+'_pos_x',0)+shift);changed=True
        if not changed:break
        image,meta=render()
    # Preserve side-by-side header relationships; stack vertically when needed.
    for _ in range(12):
        changed=False
        for i,key in enumerate(HEADERS):
            a=group(key)
            if not a:continue
            for other in HEADERS[i+1:]:
                b=group(other)
                if not b or not overlap(a,b,8):continue
                if abs((a['left']+a['right']-b['left']-b['right'])/2)>200 and abs(a['top']-b['top'])<80:
                    changed=shrink(other) or shrink(key) or changed
                else:
                    move(other,a['bottom']+12);changed=True
                break
            if changed:break
        if not changed:break
        image,meta=render()
    header_bottom=max((group(k)['bottom'] for k in HEADERS if group(k)),default=100)
    # Remove renderer padding from line spacing, keeping actual glyph gaps positive.
    for key,gap_key in (('ticket_name','ticket_gap'),('ticket_note','note_gap')):
        boxes=meta['bounds'].get(key,[])
        if boxes:
            styles[gap_key]=round(min(b['bottom']-b['top']-b.get('advance',b['bottom']-b['top']) for b in boxes)+8)
    image,meta=render()
    all_footer=[b for k in FOOTERS for b in meta['bounds'].get(k,[])]
    buzz=group('buzz')
    bottom_limit=1320
    original_top=min((b['top'] for b in all_footer),default=bottom_limit)
    # Font family/color stay fixed; only sizes may decrease within a bounded range.
    for _ in range(6):
        total=sum((group(k)['bottom']-group(k)['top']+10) for k in FOOTERS if group(k))
        if total<=bottom_limit-header_bottom-260:break
        if not any(shrink(k) for k in FOOTERS if group(k)):break
        image,meta=render()
    total=sum((group(k)['bottom']-group(k)['top']+10) for k in FOOTERS if group(k))
    y=min(original_top,bottom_limit-total)
    for key in FOOTERS:
        if group(key):move(key,y);y=group(key)['bottom']+10
    # Long footer lines must stay inside the image, including explicit x offsets.
    for key in FOOTERS:
        for _ in range(6):
            b=group(key)
            if not b or (b['left']>=20 and b['right']<=1060):break
            styles[key+'_pos_x']=0
            if not shrink(key):break
            image,meta=render()
    # A corner wordmark only constrains text that actually reaches that corner.
    for key in FOOTERS:
        for _ in range(8):
            b=group(key)
            if not b or not buzz or not overlap(b,buzz,8):break
            if not shrink(key):
                styles[key+'_pos_x']=round(styles.get(key+'_pos_x',0)+buzz['left']-b['right']-12)
            image,meta=render()
    footer_top=min((b['top'] for k in FOOTERS for b in meta['bounds'].get(k,[])),default=1320)
    zone=zone or {}
    top=max(header_bottom+20,min(zone.get('top',header_bottom+20),footer_top-260))
    available=footer_top-20-top
    if available<160:raise ValueError('見出しと料金情報が1枚の表示領域を超えています。完成扱いにせず停止しました。')
    source=args['main_source']
    required=max(math.ceil(row_count/columns)*24 if row_count else 0,grid_rows*65)
    if available<required:
        # Borrow unused footer space before sacrificing text legibility.
        last=max((b['bottom'] for k in FOOTERS for b in meta['bounds'].get(k,[])),default=bottom_limit)
        step=source.height*1080/source.width/100
        delta=min(required-available+step+2,max(0,bottom_limit-last))
        targets={k:group(k)['top']+delta for k in FOOTERS if group(k)}
        for key,y in targets.items():move(key,y)
        footer_top=min((b['top'] for k in FOOTERS for b in meta['bounds'].get(k,[])),default=1320)
        available=footer_top-20-top
    width=min(1020,max(300,zone.get('width',1020)))
    pct=min(width/1080*100,available*source.width/(1080*source.height)*100)
    # Saved sliders use whole percentages and must reproduce the same geometry.
    pct=min(150,math.floor(pct))
    if pct<10:raise ValueError('1枚では文字の読みやすさを保てません。制作対象の分割が必要です。')
    height=source.height*1080/source.width*pct/100
    if row_count and height/max(1,math.ceil(row_count/columns))<24:
        raise ValueError('出演行が多く、1枚では時刻を読める大きさを保てません。完成扱いにせず停止しました。')
    if grid_rows and height/grid_rows<65:raise ValueError('アー写の名前が小さくなりすぎるため完成扱いにせず停止しました。')
    styles.update(content_scale_w=pct,content_scale_h=pct,content_pos_y=round(675-(top+height/2)))
    image,meta=render()
    errors=issues(meta)
    if errors:raise ValueError('配置の自動検査を通過しませんでした：'+'、'.join(errors[:4]))
    changes={k:v for k,v in styles.items() if original.get(k)!=v and not k.startswith('event_')}
    return image,meta,styles,dict(ok=True,changes=changes,checks=['画像外へのはみ出しなし','文字・画像の重なりなし','収まりを実測して確認'])
