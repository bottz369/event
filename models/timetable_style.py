"""Optional timetable typography/layout settings; absent values preserve legacy output."""
DEFAULTS = dict(column_width=100, column_gap=120, custom_widths=False,
                time_width=20, goods_width=30, artist_font=100, time_font=100, goods_font=100)
LIMITS = dict(column_width=(60,140), column_gap=(0,480), time_width=(10,35),
              goods_width=(15,45), artist_font=(50,180), time_font=(50,180), goods_font=(50,180))


def normalize_style(value=None):
    source = value if isinstance(value, dict) else {}
    result = dict(DEFAULTS)
    for key, (low, high) in LIMITS.items():
        try:
            result[key] = max(low, min(high, int(source.get(key, DEFAULTS[key]))))
        except (TypeError, ValueError, OverflowError):
            pass
    result['custom_widths'] = source.get('custom_widths') is True
    return result
