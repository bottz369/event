"""Phase 5-⑤b E3 安全網: views/artists.py の全文字列定数が dedent 前後で不変であることを検証。

git diff -w は空白変更を無視するため、triple-quote 文字列の内部行が dedent されて
表示テキストが変わっても検出できない(機械証明の穴)。そこで AST の文字列定数
(ast.Constant で isinstance(value, str))を多重集合として抽出し、before/after で完全一致を assert する。

使い方:
  python3 scratch/verify_artists_strings.py --before   # dedent 前に基準を保存
  python3 scratch/verify_artists_strings.py --after    # dedent 後に比較(不一致なら SystemExit(1))
"""
import ast
import json
import os
import sys
from collections import Counter

TARGET = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "views", "artists.py")
)
SNAPSHOT = os.path.join(os.path.dirname(__file__), "_artists_strings_before.json")


def extract_string_constants(path):
    with open(path, "r", encoding="utf-8") as f:
        src = f.read()
    tree = ast.parse(src)
    values = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            values.append(node.value)
    return values


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    values = extract_string_constants(TARGET)

    if mode == "--before":
        with open(SNAPSHOT, "w", encoding="utf-8") as f:
            json.dump(values, f, ensure_ascii=False, indent=2)
        print(f"[before] 文字列定数 {len(values)} 個を保存: {SNAPSHOT}")
        # 複数行文字列の内訳を可視化
        multiline = [v for v in values if "\n" in v]
        print(f"[before] うち複数行文字列: {len(multiline)} 個")
        return

    if mode == "--after":
        with open(SNAPSHOT, "r", encoding="utf-8") as f:
            before = json.load(f)
        after = values
        cb, ca = Counter(before), Counter(after)
        if cb == ca:
            print(f"[after] MATCH: 文字列定数 {len(after)} 個が before と完全一致(表示テキスト不変)")
            return
        # 不一致 → 差分を提示して失敗
        only_before = list((cb - ca).elements())
        only_after = list((ca - cb).elements())
        print("[after] MISMATCH: 文字列定数が変化した(表示テキストが変わった可能性)")
        print(f"  before 件数={len(before)} after 件数={len(after)}")
        for v in only_before:
            print(f"  --- before のみ(消えた/変わった元): {v!r}")
        for v in only_after:
            print(f"  +++ after のみ(新たに出現): {v!r}")
        raise SystemExit(1)

    print("usage: verify_artists_strings.py --before | --after")
    raise SystemExit(2)


if __name__ == "__main__":
    main()
