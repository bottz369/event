# -*- coding: utf-8 -*-
"""段階② コミット4: grid の DnD 撤去を AST + 文字列で機械証明する(罠29)。

git diff -w では「消えたつもりで残っている」を見落とすため、
構文木上の識別子と生文字列の両方でゼロ件を証明する。
"""
from __future__ import annotations

import ast
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
G = os.path.join(REPO, "views", "grid.py")
src = open(G, encoding="utf-8").read()
tree = ast.parse(src)

# ast.unparse でコメントを落とした「実行されるコードだけ」を作る。
# 生の src には撤去理由を書いた説明コメントが残るため、コード上の撤去を
# 証明するにはコメント除去後で判定する必要がある。
code_only = ast.unparse(tree)

fails = 0


def chk(ok, label, extra=""):
    global fails
    print(("  PASS  " if ok else "  FAIL  ") + label + (("  " + extra) if extra else ""))
    if not ok:
        fails += 1


# --- AST 上の識別子を全部集める ---
names = set()
attrs = set()
imported = set()
calls = []
for node in ast.walk(tree):
    if isinstance(node, ast.Name):
        names.add(node.id)
    elif isinstance(node, ast.Attribute):
        attrs.add(node.attr)
    elif isinstance(node, ast.Import):
        for a in node.names:
            imported.add(a.asname or a.name.split(".")[0])
    elif isinstance(node, ast.ImportFrom):
        for a in node.names:
            imported.add(a.asname or a.name)
    elif isinstance(node, ast.Call):
        f = node.func
        if isinstance(f, ast.Attribute):
            calls.append(f.attr)
        elif isinstance(f, ast.Name):
            calls.append(f.id)

print("=" * 66)
print("AST による撤去証明 (views/grid.py)")
print("=" * 66)
chk("sort_items" not in names and "sort_items" not in imported and "sort_items" not in calls,
    "sort_items が AST 上に存在しない(識別子・import・呼出のいずれも)")
chk("streamlit_sortables" not in imported and "streamlit_sortables" not in code_only,
    "streamlit_sortables への参照がコード上に無い")
chk("grid_just_reset" not in code_only,
    "grid_just_reset がコード上に残っていない")
chk("rerun" not in calls and "rerun" not in attrs,
    "st.rerun() の呼び出しが 1 つも無い(rerun 誘発点が消えた)")
chk("multi_containers" not in code_only, "multi_containers(DnD 固有の引数)が残っていない")

print()
print("=" * 66)
print("文字列による撤去証明(コメント除去後のコードに対して)")
print("=" * 66)
for token in ("sort_items", "grid_just_reset", "st.rerun", "order_changed", "new_flat", "grid_ui"):
    chk(token not in code_only, "コード上に %r が 0 件" % token)
# 説明コメントには撤去理由として旧名が出てよい(むしろ残すべき)。
print("       ※ 撤去理由を書いた説明コメントには旧名が残る(意図的)")

print()
print("=" * 66)
print("残すべきものが残っているか(過剰撤去の検出)")
print("=" * 66)
chk("generate_grid_image" in calls, "generate_grid_image の呼び出しは残っている")
chk("save_active_project" in calls, "save_active_project の呼び出しは残っている")
chk("build_grid_order_from_rows" in calls, "build_grid_order_from_rows を呼んでいる")
chk("get_draft_rows" in calls, "session_manager.get_draft_rows を呼んでいる")
chk("dataframe" in calls, "読み取り専用プレビュー(st.dataframe)がある")
chk("get_artists_by_names" in calls, "get_artists_by_names の呼び出しは残っている")

print()
print("=" * 66)
print("未使用 import の検出")
print("=" * 66)
unused = [
    m for m in sorted(imported)
    if not ((m in names) or (m in calls) or ("%s." % m in code_only))
]
chk(not unused, "未使用 import が無い", "-> %s" % (unused or "なし"))

print()
print("=" * 66)
print("構文健全性")
print("=" * 66)
import py_compile
try:
    py_compile.compile(G, doraise=True)
    chk(True, "py_compile OK")
except Exception as e:
    chk(False, "py_compile 失敗: %s" % e)

print()
print("GRID_DND_REMOVED_ALL_PASS" if fails == 0 else "GRID_DND_REMOVED_FAILED (%d)" % fails)
sys.exit(0 if fails == 0 else 1)
