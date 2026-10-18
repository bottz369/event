"""Image studio: deterministic recoloring and explicit, bounded image API calls.

No Streamlit or DB writes. Returned PNG bytes are drafts until explicitly saved.
"""
import base64
import binascii
import hmac
import io
import warnings

import numpy as np
from PIL import Image, ImageColor, UnidentifiedImageError
import requests

MAX_BYTES = 20 * 1024 * 1024
MAX_PIXELS = 8_000_000
MODEL = 'gpt-image-2'
PALETTES = {'ゴールド': '#e4a637', 'アイボリー': '#e9ddbd', 'シルバー': '#b9c8db',
            'ブルー': '#2686dc', 'レッド': '#d23428'}


def open_image(data):
    if not data or len(data) > MAX_BYTES:
        raise ValueError('画像は20MB以下で選択してください。')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            image = Image.open(io.BytesIO(data))
            if image.format not in ('PNG', 'JPEG', 'WEBP'):
                raise ValueError('PNG・JPEG・WebPの画像を選択してください。')
            if image.width * image.height > MAX_PIXELS:
                raise ValueError('画像は800万画素以下で選択してください。')
            image.load()
            return image.convert('RGBA')
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombWarning,
            Image.DecompressionBombError) as exc:
        raise ValueError('画像を開けませんでした。別の画像を選択してください。') from exc


def png(image):
    buf = io.BytesIO()
    image.save(buf, format='PNG')
    data = buf.getvalue()
    if len(data) > MAX_BYTES:
        raise ValueError('処理後の画像が20MBを超えました。小さい画像でお試しください。')
    return data


def recolor(data, color, strength=100, brightness=100):
    """Map original luminance to a tint ramp, preserving size and every alpha byte."""
    image = open_image(data)
    try:
        base = np.array(ImageColor.getrgb(color), dtype=float)
    except (ValueError, TypeError) as exc:
        raise ValueError('正しい色を選択してください。') from exc
    source = np.array(image)
    rgb = source[:, :, :3].astype('float32')
    luminance = np.clip((rgb @ np.array([.2126, .7152, .0722], dtype='float32')) * max(50, min(150, brightness)) / 100, 0, 255)
    stops = [0, 45, 95, 145, 195, 230, 255]
    colors = np.array([base * .08, base * .32, base * .64, base,
                       base * .45 + 255 * .55, base * .12 + 255 * .88, [255, 253, 245]])
    weight = max(0, min(100, strength)) / 100
    output = source.copy()
    for channel in range(3):
        tint = np.interp(luminance, stops, colors[:, channel])
        output[:, :, channel] = np.clip(rgb[:, :, channel] * (1 - weight) + tint * weight, 0, 255).round().astype('uint8')
    return png(Image.fromarray(output))


def background_prompt(description, palette, reference=False):
    if not description.strip() or len(description) > 2000:
        raise ValueError('作りたい背景を1〜2000文字で入力してください。')
    return ('Create ONE portrait 4:5 background-only asset for a Japanese concert flyer. '
            'Keep the central 80% dark and quiet for existing logo, white event details, artist photos, '
            'timetable and ticket text. Put decorative detail mainly around edges and upper corners. '
            'Full bleed. NO lettering, logos, people, artist photos, prices or watermark. '
            + ('The supplied image is a visual reference. Preserve its composition and ornament positions; '
               'change only the requested visual treatment. ' if reference else '')
            + 'Requested palette: ' + palette + '. Requested design: ' + description.strip())


def generate_background(description, palette, api_key, access_code, supplied_code, reference=None):
    """One request per explicit action, no retries (avoid duplicate paid generations)."""
    if not api_key or not access_code:
        raise ValueError('背景のAI生成は管理者の接続設定後に使えます。')
    if not hmac.compare_digest(str(access_code).encode(), str(supplied_code).encode()):
        raise ValueError('利用コードを確認してください。')
    prompt = background_prompt(description, palette, reference is not None)
    payload = dict(model=MODEL, prompt=prompt, size='1024x1280', quality='medium', output_format='png', n=1)
    headers = {'Authorization': 'Bearer ' + api_key}
    args = dict(headers=headers, timeout=(15, 180), allow_redirects=False)
    endpoint = 'https://api.openai.com/v1/images/'
    if reference is not None:
        reference = png(open_image(reference))
        args.update(data=payload, files={'image': ('reference.png', reference, 'image/png')})
        endpoint += 'edits'
    else:
        args['json'] = payload
        endpoint += 'generations'
    try:
        response = requests.post(endpoint, **args)
    except requests.Timeout as exc:
        raise ValueError('生成の応答が時間内に届きませんでした。処理済みの可能性があるため、自動再試行はしません。利用状況を確認してください。') from exc
    except requests.RequestException as exc:
        raise ValueError('画像生成サービスに接続できませんでした。時間をおいてお試しください。') from exc
    if response.status_code != 200:
        messages = {401: '画像生成の接続設定を確認してください。',403: '画像生成モデルの利用権限を確認してください。',
                    429: '画像生成の利用枠または残高を確認してください。'}
        raise ValueError(messages.get(response.status_code, '背景を生成できませんでした。指示を変えるか、時間をおいてお試しください。'))
    try:
        encoded = response.json()['data'][0]['b64_json']
        if len(encoded) > MAX_BYTES * 4 // 3 + 8:
            raise ValueError('画像サイズの上限を超えました。')
        data = base64.b64decode(encoded, validate=True)
        return png(open_image(data))
    except (KeyError, IndexError, TypeError, binascii.Error, ValueError) as exc:
        raise ValueError('生成画像を受け取れませんでした。利用状況を確認してください。') from exc
