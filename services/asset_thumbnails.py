"""Small derivative images; originals are never fetched while rendering the catalog."""
import hashlib
import io
import warnings
from PIL import Image


def filename(original):
    return 'asset_thumbnails/' + hashlib.sha256(original.encode()).hexdigest() + '.webp'


def store(data, original):
    from database import upload_image_to_supabase
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(data)) as source:
            # Decode large JPEGs at reduced resolution instead of allocating full RGBA.
            if source.width * source.height > Image.MAX_IMAGE_PIXELS:
                if source.format != 'JPEG':
                    raise ValueError('この画像は縮小処理には大きすぎます。')
                source.draft('RGB', (320, 200))
                if source.width * source.height > Image.MAX_IMAGE_PIXELS:
                    raise ValueError('この画像は縮小処理には大きすぎます。')
            image = source.convert('RGBA')
            image.thumbnail((320, 200), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    image.save(out, 'WEBP', quality=75, method=4)
    if not upload_image_to_supabase(out, filename(original)):
        raise ValueError('縮小プレビューを保存できませんでした。')
    return out.getvalue()


def ensure(original):
    """Explicit repair/backfill only, never run on catalog open."""
    import requests
    from database import get_image_url
    data = bytearray()
    with requests.get(get_image_url(original), stream=True, timeout=(5, 20)) as response:
        response.raise_for_status()
        for chunk in response.iter_content(65536):
            data.extend(chunk)
            if len(data) > 20*1024*1024:
                raise ValueError('20MB以下の画像を選択してください。')
    return store(bytes(data), original)


def try_store(data, original):
    try:
        store(data, original)
        return True
    except Exception:
        import logging
        logging.getLogger(__name__).warning('Could not prepare small asset preview')
        return False
