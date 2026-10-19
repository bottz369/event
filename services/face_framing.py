"""Local face bounds, persisted per immutable photo, reused by every layout.

No recognition, external vision API, project DB writes or new schema. Only cached
normalized rectangles are stored alongside the existing public artist photos.
"""
import hashlib
import io
import json
import logging
import math
import threading
from collections import OrderedDict

from PIL import Image, ImageOps

logger = logging.getLogger(__name__)
VERSION = 1
LOCK = threading.RLock()
CACHE = OrderedDict()
MAX_CACHE = 512


def _path(filename):
    return 'face_checks/v1/' + hashlib.sha256(filename.encode()).hexdigest() + '.json'


def _read(filename):
    import requests
    from database import get_image_url
    try:
        response = requests.get(get_image_url(_path(filename)), timeout=(2, 3), allow_redirects=False)
        if response.status_code == 200 and len(response.content) <= 65536:
            return json.loads(response.content)
    except Exception:
        logger.debug('face bounds cache read unavailable')
    return None


def _write(filename, info):
    from database import supabase, BUCKET_NAME
    try:
        supabase.storage.from_(BUCKET_NAME).upload(path=_path(filename),
            file=json.dumps(info, allow_nan=False).encode(),
            file_options={'content-type': 'application/json', 'upsert': 'true'})
    except Exception:
        # A storage outage must not make registration or manual editing unusable.
        logger.warning('face bounds persistence unavailable; using process cache')


def _valid(info):
    try:
        return (info['version'] == VERSION and info['status'] in ('detected', 'no_faces')
            and 0 < info['width'] <= 100000 and 0 < info['height'] <= 100000
            and len(info['boxes']) <= 200
            and all(len(b) == 4 and all(isinstance(v, (int, float)) and math.isfinite(v) for v in b)
                    and 0 <= b[0] < b[2] <= 1 and 0 <= b[1] < b[3] <= 1 for b in info['boxes']))
    except (KeyError, TypeError, ValueError):
        return False


def detect(image):
    import cv2
    import numpy as np
    sample = image.convert('RGB'); sample.thumbnail((1600, 1600))
    gray = cv2.cvtColor(np.asarray(sample), cv2.COLOR_RGB2GRAY)
    gray = cv2.equalizeHist(gray)
    boxes = []
    # Frontal + both profile directions, bounded input resolution.
    for model, flipped in [('haarcascade_frontalface_default.xml', False),
                           ('haarcascade_profileface.xml', False), ('haarcascade_profileface.xml', True)]:
        classifier = cv2.CascadeClassifier(cv2.data.haarcascades + model)
        if classifier.empty():
            raise ValueError('顔検出モデルを読み込めませんでした。')
        source = cv2.flip(gray, 1) if flipped else gray
        for x, y, w, h in classifier.detectMultiScale(source, scaleFactor=1.1,
                minNeighbors=5, minSize=(16, 16)):
            if flipped:
                x = sample.width-x-w
            # Include forehead/hair and chin rather than just the detected face box.
            boxes.append([max(0., (x-w*.2)/sample.width), max(0., (y-h*.35)/sample.height),
                          min(1., (x+w*1.2)/sample.width), min(1., (y+h*1.2)/sample.height)])
    boxes = boxes[:200]
    return dict(version=VERSION, status='detected' if boxes else 'no_faces',
                width=image.width, height=image.height, boxes=boxes)


def bounds(filename, image=None):
    if not filename:
        return None
    # Single-flight also prevents duplicated work for repeated artists/parallel TT+grid.
    with LOCK:
        if filename in CACHE:
            CACHE.move_to_end(filename)
            return CACHE[filename]
        info = _read(filename)
        if not _valid(info):
            if image is None:
                return None
            try:
                info = detect(image)
                if not _valid(info):
                    raise ValueError('Invalid face bounds')
                _write(filename, info)
            except Exception:
                logger.warning('face detection unavailable; retaining manual framing', exc_info=True)
                CACHE[filename] = None
                if len(CACHE) > MAX_CACHE:
                    CACHE.popitem(last=False)
                return None
        CACHE[filename] = info
        if len(CACHE) > MAX_CACHE:
            CACHE.popitem(last=False)
        return info


def base_size(size, target):
    w, h = size; tw, th = target
    return (int(th*w/h), th) if w/h > tw/th else (tw, int(tw*h/w))


def visible(info, crop, size=None, target=(800, 450)):
    size = size or (info['width'], info['height'])
    bw, bh = base_size(size, target); scale, x, y = crop; tw, th = target
    fw, fh = max(1, int(bw*scale)), max(1, int(bh*scale))
    left, top = int((tw-fw)/2+x), int((th-fh)/2+y)
    boxes = info['boxes'] or [[0., 0., 1., 1.]]
    return all(left+b[0]*fw >= 0 and top+b[1]*fh >= 0
               and left+b[2]*fw <= tw and top+b[3]*fh <= th for b in boxes)


def corrected(info, crop, size=None, target=(800, 450)):
    """Preserve safe manual choices; shift first, then shrink, then contain all."""
    if not info or visible(info, crop, size, target):
        return crop
    size = size or (info['width'], info['height']); tw, th = target
    bw, bh = base_size(size, target)
    boxes = info['boxes'] or [[0., 0., 1., 1.]]
    l, t = min(b[0] for b in boxes), min(b[1] for b in boxes)
    r, b = max(b[2] for b in boxes), max(b[3] for b in boxes)
    scale = min(crop[0], tw/(bw*(r-l)), th/(bh*(b-t)))
    # A tiny inset avoids integer rounding at the edges; don't enlarge the photo.
    scale = max(.1, scale*.999)
    for _ in range(100):
        fw, fh = max(1, int(bw*scale)), max(1, int(bh*scale))
        xmin, xmax = math.ceil(-l*fw-(tw-fw)/2), math.floor(tw-r*fw-(tw-fw)/2)
        ymin, ymax = math.ceil(-t*fh-(th-fh)/2), math.floor(th-b*fh-(th-fh)/2)
        # Same movement range as artist management, proportional for the TT strip.
        mx, my = tw/4, th*112/450
        xmin, xmax = max(xmin, math.ceil(-mx)), min(xmax, math.floor(mx))
        ymin, ymax = max(ymin, math.ceil(-my)), min(ymax, math.floor(my))
        if xmin <= xmax and ymin <= ymax:
            result = scale, max(xmin, min(xmax, crop[1])), max(ymin, min(ymax, crop[2]))
            if visible(info, result, size, target):
                return result
        if scale <= .1:
            break
        scale = max(.1, scale*.95)
    # Very extreme aspect ratios need a smaller rendering-only scale.
    return min(crop[0], tw/bw, th/bh)*.999, 0, 0


def protect(image, filename, crop=(1., 0, 0), target=(800, 450)):
    info = bounds(filename, image)
    return corrected(info, crop, image.size, target)


def fit_timetable(image, filename, target):
    from logic_grid import apply_manual_crop
    crop = protect(image, filename, target=target)
    if crop == (1., 0, 0):
        return ImageOps.fit(image, target, method=Image.Resampling.LANCZOS, centering=(.5, .5))
    return apply_manual_crop(image, *crop, *target)


def registration(file_obj, filename):
    """New/replacement photos start with a fresh crop, not the previous image's zoom."""
    if file_obj is None or not filename:
        return None
    try:
        data = file_obj.getvalue()
        if len(data) > 20*1024*1024:
            return None
        image = Image.open(io.BytesIO(data))
        if image.width*image.height > 40_000_000:
            return None
        image = image.convert('RGB'); image.thumbnail((1600, 1600))
        crop = protect(image, filename)
        return max(.1, crop[0]), int(crop[1]), int(crop[2])
    except Exception:
        logger.warning('registration face check unavailable', exc_info=True)
        return None
