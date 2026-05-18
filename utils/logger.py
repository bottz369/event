"""
共通ロガー

`except: pass` を撲滅し、エラーの可視化を行うためのロガー。

使い方:
    from utils.logger import get_logger
    logger = get_logger(__name__)

    try:
        ...
    except Exception as e:
        logger.warning(f"何か失敗: {e}", exc_info=True)
"""
import logging
import os
import sys


def get_logger(name: str = "event_app") -> logging.Logger:
    """
    名前付きロガーを取得する。
    同じ名前で複数回呼んでも、ハンドラが重複登録されないように制御している。
    """
    logger = logging.getLogger(name)

    # 既に設定済みならそのまま返す
    if logger.handlers:
        return logger

    # 環境変数でログレベルを切り替え可能(デフォルト: INFO)
    level_name = os.environ.get("EVENT_APP_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logger.setLevel(level)

    # 標準エラーに出力
    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(level)

    fmt = "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s"
    formatter = logging.Formatter(fmt, datefmt="%Y-%m-%d %H:%M:%S")
    handler.setFormatter(formatter)

    logger.addHandler(handler)

    # 親ロガーへの伝播を止める(Streamlitのロガーへの二重出力防止)
    logger.propagate = False

    return logger
