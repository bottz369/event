"""Photo-version-specific offsets inside a project's fixed grid cells."""
import math


def normalize_offsets(value):
    result = {}
    if not isinstance(value, dict):
        return result
    for name, entry in list(value.items())[:100]:
        if not isinstance(name, str) or not name or len(name) > 200 or not isinstance(entry, dict):
            continue
        filename = entry.get('image_filename')
        if not isinstance(filename, str) or not filename or len(filename) > 4096 or isinstance(entry.get('y'), bool):
            continue
        try:
            offset = float(entry['y'])
            if math.isfinite(offset):
                result[name] = dict(image_filename=filename, y=max(-112, min(112, round(offset))))
        except (KeyError, TypeError, ValueError, OverflowError):
            pass
    return result
