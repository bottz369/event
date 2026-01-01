import os
import tempfile  # ★追加: システムの一時フォルダを使うために必要

# ==========================================
# ディレクトリ設定 (ここを修正)
# ==========================================

# アプリのルートディレクトリを動的に取得
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 素材(Assets)フォルダ
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
os.makedirs(ASSETS_DIR, exist_ok=True)

# ★修正: フォントフォルダをシステムの一時領域に固定
# これにより、どの画面からでも確実にアクセスでき、権限エラーも回避します
FONT_DIR = os.path.join(tempfile.gettempdir(), "app_fonts")
os.makedirs(FONT_DIR, exist_ok=True)


# ==========================================
# 選択肢リスト (ユーザー様の設定を維持)
# ==========================================

def get_time_options_1min():
    """00:00 から 23:59 までの1分刻みのリストを生成"""
    times = []
    for h in range(24):
        for m in range(60):
            times.append(f"{h:02d}:{m:02d}")
    return times

# 時間リスト
TIME_OPTIONS = get_time_options_1min()

# 出演時間 (0分〜240分)
DURATION_OPTIONS = list(range(0, 241))

# 転換時間 (0分〜60分)
ADJUSTMENT_OPTIONS = list(range(0, 61))

# 物販時間 (5分〜300分、5分刻み)
GOODS_DURATION_OPTIONS = list(range(5, 301, 5))

# 場所リスト (A〜Z)
PLACE_OPTIONS = [chr(i) for i in range(65, 91)]


# ==========================================
# デフォルト設定値
# ==========================================

def get_default_row_settings():
    """タイムテーブル行の初期設定値を返す"""
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
