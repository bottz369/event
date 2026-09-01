# -*- coding: utf-8 -*-
"""§42 豆腐化 診断: 空の FONT_DIR で ensure_font_available が何をしているかを1ステップずつ可視化。

read-only DB。書き込みはローカル一時 FS(FONT_DIR)への materialize のみ。
"""
from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

try:
    import tomllib as _toml
except ModuleNotFoundError:
    import tomli as _toml

P = REPO_ROOT / ".streamlit" / "secrets.readonly.toml"
creds = _toml.load(open(P, "rb"))["supabase"]
import streamlit.runtime.secrets as st_secrets
st_secrets.secrets_singleton._secrets = {"supabase": dict(creds)}

from sqlalchemy import create_engine, text
_e = create_engine(creds["DB_URL"], connect_args={"sslmode": "require"})
with _e.connect() as c:
    u = c.execute(text("SELECT current_user")).scalar()
_e.dispose()
assert u == "event_app_readonly", "read-only ユーザー以外では実行しない: %r" % u
print("[safety] current_user =", u)

from constants import FONT_DIR, BASE_DIR              # noqa: E402
from database import SessionLocal, get_image_url      # noqa: E402
from repositories import font_repo                    # noqa: E402
import logic_grid                                     # noqa: E402

TARGET = "keifont.ttf"

print()
print("=" * 70)
print("[0] ディレクトリ基準")
print("=" * 70)
print("  constants.FONT_DIR      =", FONT_DIR)
print("  constants.BASE_DIR      =", BASE_DIR)
print("  logic_grid.FONT_DIR     =", logic_grid.FONT_DIR)
print("  logic_grid.BASE_DIR     =", logic_grid.BASE_DIR)
print("  FONT_DIR 一致           =", FONT_DIR == logic_grid.FONT_DIR)
print("  os.getcwd()             =", os.getcwd())
print("  FONT_DIR の中身         =", sorted(os.listdir(FONT_DIR)) if os.path.isdir(FONT_DIR) else "(無し)")

print()
print("=" * 70)
print("[1] resolve_font_path の候補パス (materialize 前)")
print("=" * 70)
cands = [
    TARGET,
    os.path.join(FONT_DIR, TARGET),
    os.path.join("assets", "fonts", TARGET),
    os.path.join(BASE_DIR, "assets", "fonts", TARGET),
    os.path.join("fonts", TARGET),
    os.path.join(os.getcwd(), TARGET),
]
for i, c in enumerate(cands, 1):
    print("  %d) exists=%-5s %s" % (i, os.path.exists(c), c))
print("  resolve_font_path(%r) -> %r" % (TARGET, logic_grid.resolve_font_path(TARGET)))

print()
print("=" * 70)
print("[2] DB 実体を辿る (read-only)")
print("=" * 70)
db = SessionLocal()
try:
    asset = font_repo.get_font_asset(db, TARGET)
    print("  Asset(image_filename==%r) -> %s" % (TARGET, "HIT" if asset else "MISS"))
    url = None
    if asset:
        print("    asset.id            =", getattr(asset, "id", None))
        print("    asset.image_filename=", repr(asset.image_filename))
        print("    asset.asset_type    =", repr(getattr(asset, "asset_type", None)))
        print("    asset.is_deleted    =", getattr(asset, "is_deleted", None))
        try:
            url = get_image_url(asset.image_filename)
            print("    get_image_url()     =", repr(url))
        except Exception as e:
            print("    get_image_url() EXC  =", repr(e))
            traceback.print_exc()

    af = font_repo.get_font_asset_file(db, TARGET)
    print("  AssetFile(filename==%r) -> %s" % (TARGET, "HIT" if af else "MISS"))
    if af:
        data = af.file_data
        print("    file_data           =", ("%d bytes" % len(data)) if data else repr(data))
finally:
    db.close()

print()
print("=" * 70)
print("[3] URL 経路の HTTP 取得を実際に試す")
print("=" * 70)
if url:
    import requests
    try:
        r = requests.get(url, timeout=10)
        print("  requests.get -> status=%s  len=%s  content-type=%s"
              % (r.status_code, len(r.content), r.headers.get("content-type")))
        print("  先頭16バイト =", r.content[:16])
    except Exception as e:
        print("  requests.get EXC =", repr(e))
        traceback.print_exc()
else:
    print("  (URL が無いためスキップ)")

print()
print("=" * 70)
print("[4] ensure_font_available を実行 (例外を握らせず素で観察)")
print("=" * 70)
from services import font_service  # noqa: E402
try:
    status = font_service.ensure_font_available(TARGET)
    print("  ensure_font_available(%r) -> %r" % (TARGET, status))
except Exception as e:
    print("  EXC =", repr(e))
    traceback.print_exc()
print("  FONT_DIR の中身 (実行後) =", sorted(os.listdir(FONT_DIR)) if os.path.isdir(FONT_DIR) else "(無し)")
fp = os.path.join(FONT_DIR, TARGET)
print("  %s exists=%s size=%s" % (fp, os.path.exists(fp), os.path.getsize(fp) if os.path.exists(fp) else "-"))

print()
print("=" * 70)
print("[5] materialize 後の resolve_font_path")
print("=" * 70)
print("  resolve_font_path(%r)                 -> %r" % (TARGET, logic_grid.resolve_font_path(TARGET)))
print("  resolve_font_path(FONT_DIR/keifont)   -> %r"
      % logic_grid.resolve_font_path(os.path.join(FONT_DIR, TARGET)))
