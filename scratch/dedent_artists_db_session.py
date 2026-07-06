"""Phase 5-⑤b E3: views/artists.py の未使用 DB セッション撤去(構造的 dedent)。

Edit ツールはインデント変更を伴う構造撤去に不向き(罠27)。本スクリプトで機械的に:
  1. import 行から get_db を除去(get_image_url は残す)
  2. `    db = next(get_db())` 行を削除
  3. 関数レベル `    try:`(4sp)行を削除し、その本体を対応する `    finally:` まで 1 段 dedent
  4. `    finally:` / `        db.close()` 行を削除

対象は render_artists_page の唯一の関数レベル try/finally(4sp)のみ。
本体には ⑤-a で db 参照が消えており DB 非依存。冪等性は無い(1 回だけ実行する前提)。

triple-quote ガード: 複数行文字列の内部行(lineno+1 .. end_lineno)は文字列の中身=
表示テキストなので dedent 対象から除外する(空白を変えると表示が変わる。git diff -w では
検出できない穴。scratch/verify_artists_strings.py の AST 比較で担保)。

実行: python3 scratch/dedent_artists_db_session.py
"""
import ast
import os

PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "views", "artists.py")
)

with open(PATH, "r", encoding="utf-8") as f:
    src = f.read()
lines = src.splitlines(keepends=True)

# --- 複数行文字列の内部行(1-indexed)を保護集合に集める ---
# 開始行(lineno)は st.info( 等のコード行なので dedent 対象。
# 2 行目以降(lineno+1 .. end_lineno)は文字列内容なので保護。
protected = set()
for node in ast.walk(ast.parse(src)):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        if node.end_lineno and node.end_lineno > node.lineno:
            for ln in range(node.lineno + 1, node.end_lineno + 1):
                protected.add(ln)

out = []
i = 0
n = len(lines)
removed = {"import_get_db": False, "db_assign": False, "try": False,
           "finally": False, "close": False, "dedented": 0, "protected": 0}

while i < n:
    line = lines[i]
    stripped = line.rstrip("\n")

    # 1. import 行の get_db 除去
    if stripped == "from database import get_db, get_image_url":
        out.append("from database import get_image_url\n")
        removed["import_get_db"] = True
        i += 1
        continue

    # 2. db = next(get_db()) 行を削除
    if stripped.strip() == "db = next(get_db())":
        removed["db_assign"] = True
        i += 1
        continue

    # 3. 関数レベル try:(ちょうど 4 スペース)を検出 → 本体を finally まで dedent
    if stripped == "    try:":
        removed["try"] = True
        i += 1  # try: 行自体は出力しない
        # 本体を `    finally:` まで dedent して出力
        while i < n and lines[i].rstrip("\n") != "    finally:":
            body = lines[i]
            if (i + 1) in protected:
                # 複数行文字列の内部行 = 表示テキスト。空白を変えない(保護)
                out.append(body)
                removed["protected"] += 1
            elif body.startswith("    "):
                out.append(body[4:])
                if body.strip() != "":
                    removed["dedented"] += 1
            else:
                # 4 スペース未満(空行など)はそのまま
                out.append(body)
            i += 1
        # ここで lines[i] == "    finally:"
        if i < n and lines[i].rstrip("\n") == "    finally:":
            removed["finally"] = True
            i += 1  # finally: 行を削除
            # 直後の db.close() 行を削除
            if i < n and lines[i].strip() == "db.close()":
                removed["close"] = True
                i += 1
        continue

    out.append(line)
    i += 1

with open(PATH, "w", encoding="utf-8") as f:
    f.writelines(out)

print("removed/updated:", removed)
assert all([removed["import_get_db"], removed["db_assign"], removed["try"],
            removed["finally"], removed["close"]]), removed
print(f"OK: dedented {removed['dedented']} non-blank body lines")
