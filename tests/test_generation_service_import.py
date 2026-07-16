"""generation_service が streamlit / session_manager / project_service 非依存であることの機械確認。

Bot 実環境(streamlit が import 不能)を再現するため builtins.__import__ を差し替えて
'streamlit' / 'streamlit.*' の import を ImportError にし、その状態で
services.generation_service を fresh import する。

検証(§11.7 段階A1):
  (a) import が成功する(streamlit 不在でも ImportError を投げない)
  (b) import 後に 'streamlit' / 'services.session_manager' / 'services.project_service' が
      sys.modules に載っていない(generation_service がこれらを引かない証明)

streamlit を封じると database は env 変数フォールバックに落ちるため、read-only secrets の
SUPABASE_* を env に流し込む(import のみ・書き込み無し)。.venv での実行を想定。
"""
from __future__ import annotations

import builtins
import importlib
import sys
from pathlib import Path

import pytest

try:
    import tomllib as _toml
except ModuleNotFoundError:  # 3.9/3.10
    import tomli as _toml

# fresh import させたい / 非ロードを主張したいモジュール群
_PURGE = (
    "services.generation_service",
    "database",
    "services.project_service",
    "services.session_manager",
    "services.legacy_adapter",
)


def _readonly_supabase() -> dict:
    p = Path(__file__).resolve().parent.parent / ".streamlit" / "secrets.readonly.toml"
    if not p.exists():
        pytest.skip(f"read-only secrets 未配置: {p}")
    sec = _toml.loads(p.read_text()).get("supabase")
    if not sec or "DB_URL" not in sec:
        pytest.skip("read-only secrets に [supabase] が無い")
    return sec


def _purge() -> None:
    for m in list(sys.modules):
        if m in _PURGE or m == "streamlit" or m.startswith("streamlit."):
            sys.modules.pop(m, None)


def test_generation_service_is_streamlit_free(monkeypatch):
    sec = _readonly_supabase()
    monkeypatch.setenv("SUPABASE_DB_URL", sec["DB_URL"])
    monkeypatch.setenv("SUPABASE_URL", sec["URL"])
    monkeypatch.setenv("SUPABASE_KEY", sec["KEY"])

    real_import = builtins.__import__

    def _blocked_import(name, *args, **kwargs):
        if name == "streamlit" or name.startswith("streamlit."):
            raise ImportError("streamlit is unavailable (simulated Bot env)")
        return real_import(name, *args, **kwargs)

    try:
        _purge()  # 直前に purge → import で再追加されたら「引いた」証拠になる
        monkeypatch.setattr(builtins, "__import__", _blocked_import)

        gs = importlib.import_module("services.generation_service")  # (a) 例外を投げない

        assert callable(gs.build_summary_text_for_project)
        assert callable(gs.render_grid_png_for_project)
        # (b) streamlit を引く連鎖を一切持たない
        assert "streamlit" not in sys.modules
        assert "services.session_manager" not in sys.modules
        assert "services.project_service" not in sys.modules
    finally:
        _purge()
