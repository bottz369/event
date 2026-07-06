"""AppTest スモークテスト用の共通フィクスチャ。

安全設計(本番データ保護):
- 本番 `.streamlit/secrets.toml` は一切参照させない。テスト用 read-only secrets
  (`.streamlit/secrets.readonly.toml`)の値を Streamlit の secrets シングルトンへ
  直接注入し、app が import 時に読む st.secrets を read-only 接続へ確定させる。
- テスト先頭で `SELECT current_user` を実行し、接続ユーザーが event_app_readonly で
  なければ pytest.exit で**全テストを即中断**(誤って書き込み可能ユーザーで走らせない安全弁)。
- テストは SELECT のみ(プロジェクト選択・タブ描画)。INSERT/UPDATE/DELETE は行わない
  (read-only ユーザーで物理的にも不可)。

重要: このモジュール/テストは `database` や `app` を import 時にロードしない。
先にロードすると engine が本番 secrets.toml で生成されてしまうため、
secrets 注入(_inject_readonly_secrets)より後に AppTest 経由でのみロードする。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

try:
    import tomllib as _toml  # Python 3.11+
except ModuleNotFoundError:  # 3.9/3.10
    import tomli as _toml

REPO_ROOT = Path(__file__).resolve().parent.parent
READONLY_SECRETS_PATH = REPO_ROOT / ".streamlit" / "secrets.readonly.toml"
APP_PATH = REPO_ROOT / "app.py"
EXPECTED_USER = "event_app_readonly"


def _load_readonly_supabase() -> dict | None:
    if not READONLY_SECRETS_PATH.exists():
        return None
    with open(READONLY_SECRETS_PATH, "rb") as f:
        data = _toml.load(f)
    return data.get("supabase")


@pytest.fixture(scope="session")
def readonly_creds() -> dict:
    """read-only secrets の [supabase] セクション。未配置ならスキップ。"""
    creds = _load_readonly_supabase()
    if not creds or "DB_URL" not in creds:
        pytest.skip(
            "read-only テスト secrets 未配置: "
            f"{READONLY_SECRETS_PATH}(.example を参照して配置してください)"
        )
    return creds


@pytest.fixture(scope="session", autouse=True)
def _inject_readonly_secrets(readonly_creds):
    """st.secrets を read-only 値へ確定的に差し替える(本番 secrets.toml を参照させない)。

    database.py は import 時に st.secrets["supabase"][...] を読むため、AppTest 実行より
    前に(=最初の at.run() 前に)このシングルトン注入を済ませておく必要がある。
    """
    import streamlit.runtime.secrets as st_secrets

    st_secrets.secrets_singleton._secrets = {"supabase": dict(readonly_creds)}
    yield


def _make_engine(db_url: str):
    from sqlalchemy import create_engine

    return create_engine(db_url, connect_args={"sslmode": "require"})


@pytest.fixture(scope="session", autouse=True)
def _enforce_readonly_user(readonly_creds, _inject_readonly_secrets):
    """安全弁: 接続ユーザーが event_app_readonly でなければ全テストを即中断。"""
    from sqlalchemy import text

    try:
        engine = _make_engine(readonly_creds["DB_URL"])
        with engine.connect() as conn:
            user = conn.execute(text("SELECT current_user")).scalar()
    except Exception as e:  # 接続不可なら中断(本番へ誤接続するより安全に倒す)
        pytest.exit(f"read-only DB へ接続できません: {e}", returncode=3)
    finally:
        try:
            engine.dispose()
        except Exception:
            pass

    if user != EXPECTED_USER:
        pytest.exit(
            f"接続ユーザーが '{user}' です。'{EXPECTED_USER}' 以外では安全のため"
            " 全テストを中断します(書き込み可能ユーザーでの実行を防止)。",
            returncode=3,
        )
    yield


def _extract_row_counts_str(raw) -> str | None:
    """grid_order_json(生文字列)から row_counts_str を取り出す。

    dict 形式({"order":..., "row_counts_str": "5,5,5,6,6", ...})のみ対象。
    裸 list 形式は row_counts を持たないため None。空/壊れ JSON も None。
    """
    if not raw:
        return None
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return None
    if isinstance(data, dict):
        rc = data.get("row_counts_str")
        if isinstance(rc, str) and rc.strip():
            return rc
    return None


@pytest.fixture(scope="session")
def two_projects_different_row_counts(readonly_creds):
    """row_counts_str が異なる既存プロジェクトを 2 件返す。

    返り値: ((id, label, row_counts_str), (id, label, row_counts_str))
    label は workspace の selectbox 表示と同形式 f"{event_date or '----'} {title}"。
    2 件見つからなければ skip(read-only ではテストデータを作れないため)。
    """
    from sqlalchemy import text

    engine = _make_engine(readonly_creds["DB_URL"])
    by_rc: dict[str, tuple] = {}
    try:
        with engine.connect() as conn:
            res = conn.execute(
                text(
                    "SELECT id, event_date, title, grid_order_json "
                    "FROM projects_v4 WHERE grid_order_json IS NOT NULL"
                )
            )
            for row in res:
                rc = _extract_row_counts_str(row.grid_order_json)
                if rc is None:
                    continue
                label = f"{row.event_date or '----'} {row.title}"
                by_rc.setdefault(rc, (row.id, label, rc))  # rc ごとに1件
    finally:
        engine.dispose()

    distinct = list(by_rc.values())
    if len(distinct) < 2:
        pytest.skip(
            "row_counts_str が異なる既存プロジェクトが 2 件見つかりません "
            f"(見つかった distinct 値: {len(distinct)} 件)。テストデータを用意してください。"
        )
    return distinct[0], distinct[1]


@pytest.fixture
def app_test(_inject_readonly_secrets):
    """未実行の AppTest を返す(secrets 注入後に生成)。"""
    from streamlit.testing.v1 import AppTest

    return AppTest.from_file(str(APP_PATH), default_timeout=90)
