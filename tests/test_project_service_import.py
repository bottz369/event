"""project_service の read 経路が streamlit / session_manager 非依存であることの機械確認。

Bot 実環境(streamlit が import 不能・starlette 版数衝突)を再現するため、
builtins.__import__ を差し替えて 'streamlit' / 'streamlit.*' の import を ImportError に
見せかけ、その状態で services.project_service を fresh import する。

検証(§11.7 段階0):
  (a) import が成功する(streamlit 不在でも ImportError を投げない)
  (b) project_service.st is None(optional 化が効いている)
  (c) read 2 関数 list_project_summaries / get_project_flyer_view が callable
  (d) import 直後に services.session_manager が sys.modules に無い
      (= read 経路が session_manager を引かない証明。write 系の遅延 import 化が効いている)

streamlit を封じると database は env 変数フォールバックに落ちるため、read-only secrets の
SUPABASE_* を env に流し込む(SELECT すら発行しない・import のみ。書き込み無し)。
fastapi は不要だが database import のため .venv での実行を想定。
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

_AFFECTED = ("services.project_service", "database")


def _readonly_supabase() -> dict:
    p = Path(__file__).resolve().parent.parent / ".streamlit" / "secrets.readonly.toml"
    if not p.exists():
        pytest.skip(f"read-only secrets 未配置: {p}")
    sec = _toml.loads(p.read_text()).get("supabase")
    if not sec or "DB_URL" not in sec:
        pytest.skip("read-only secrets に [supabase] が無い")
    return sec


def _purge(mods) -> None:
    for m in list(sys.modules):
        if m in mods or m == "streamlit" or m.startswith("streamlit."):
            sys.modules.pop(m, None)
    sys.modules.pop("services.session_manager", None)


def test_project_service_read_path_is_streamlit_free(monkeypatch):
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
        _purge(_AFFECTED)  # fresh import させて try/except を再評価させる
        monkeypatch.setattr(builtins, "__import__", _blocked_import)

        ps = importlib.import_module("services.project_service")  # (a) 例外を投げない

        assert ps.st is None  # (b) optional 化が効いている
        assert callable(ps.list_project_summaries)  # (c)
        assert callable(ps.get_project_flyer_view)  # (c)
        # (d) read 経路は session_manager を引かない(write 系の遅延 import 化の証明)
        assert "services.session_manager" not in sys.modules
    finally:
        # monkeypatch が __import__/env を戻した後、汚染したモジュールを purge して
        # 後続テストが streamlit 本物で再 import できるようにする。
        _purge(_AFFECTED)


def test_noop_cache_data_has_clear(monkeypatch):
    """st 不在時の no-op デコレータが .clear() を生やし、関数として動くこと。"""
    real_import = builtins.__import__

    def _blocked_import(name, *args, **kwargs):
        if name == "streamlit" or name.startswith("streamlit."):
            raise ImportError("streamlit is unavailable (simulated Bot env)")
        return real_import(name, *args, **kwargs)

    sec = _readonly_supabase()
    monkeypatch.setenv("SUPABASE_DB_URL", sec["DB_URL"])
    monkeypatch.setenv("SUPABASE_URL", sec["URL"])
    monkeypatch.setenv("SUPABASE_KEY", sec["KEY"])

    try:
        _purge(_AFFECTED)
        monkeypatch.setattr(builtins, "__import__", _blocked_import)
        ps = importlib.import_module("services.project_service")

        # list_projects_for_selector は @_cache_data 適用済み。no-op でも .clear() が呼べる。
        assert hasattr(ps.list_projects_for_selector, "clear")
        assert ps.list_projects_for_selector.clear() is None  # 無害(例外を投げない)
    finally:
        _purge(_AFFECTED)
