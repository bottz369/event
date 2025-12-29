import os

# --- 定数定義 ---
FONT_DIR = "fonts"
os.makedirs(FONT_DIR, exist_ok=True)

def get_time_options_1min():
    times = []
    for h in range(24):
        for m in range(60):
            times.append(f"{h:02d}:{m:02d}")
    return times

TIME_OPTIONS = get_time_options_1min()
DURATION_OPTIONS = list(range(0, 241))
ADJUSTMENT_OPTIONS = list(range(0, 61))
GOODS_DURATION_OPTIONS = list(range(5, 301, 5))
PLACE_OPTIONS = [chr(i) for i in range(65, 91)]

def get_default_row_settings():
    return {
        "ADJUSTMENT": 0,
        "GOODS_START_MANUAL": "",
        "GOODS_DURATION": 60,
        "PLACE": "A",
        "ADD_GOODS_START": "",
        "ADD_GOODS_DURATION": None,
        "ADD_GOODS_PLACE": "",
        "IS_POST_GOODS": False
    }
