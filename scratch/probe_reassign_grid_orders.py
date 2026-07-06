"""Phase 5-⑤b E1 純ロジック検証: project_repo._reassign_grid_json

本番のみ環境(database.py が import 時に st.secrets → st.stop() する)を回避するため、
streamlit / database を MagicMock 化してから実コードを import し、実関数を直接テストする。
DB には一切書き込まない(純関数 _reassign_grid_json のみを対象)。

実行: python3 scratch/probe_reassign_grid_orders.py
"""
from __future__ import annotations

import json
import os
import sys
from unittest.mock import MagicMock

# database.py は import 時に st.secrets / create_engine に触れるため両方モック
sys.modules["streamlit"] = MagicMock()
sys.modules["database"] = MagicMock()

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from repositories.project_repo import _reassign_grid_json  # noqa: E402


def run():
    passed = 0

    # --- 1. dict 形式: order 内 loser を位置維持で置換、他キーは不変 ---
    src = {
        "order": ["A", "loser", "B"],
        "row_counts": "5,5,5",
        "alignment": "中央揃え",
        "layout_mode": "レンガ (サイズ統一)",
        "font": "foo.ttf",
        "rows": 3,
    }
    out = _reassign_grid_json(json.dumps(src, ensure_ascii=False), "loser", "winner")
    d = json.loads(out)
    assert d["order"] == ["A", "winner", "B"], d["order"]
    # order 以外のキーが保存前後で不変(2 人目の書き手が壊さない証明)
    for k in ("row_counts", "alignment", "layout_mode", "font", "rows"):
        assert d[k] == src[k], (k, d.get(k), src[k])
    assert set(d.keys()) == set(src.keys()), (d.keys(), src.keys())
    passed += 1
    print("[OK] 1 dict: 位置維持で置換 + order 以外キー不変")

    # --- 2. dict 形式: winner が既に order に居る → loser を削除(重複回避)---
    src2 = {"order": ["winner", "loser", "B"], "font": "x.ttf"}
    out2 = _reassign_grid_json(json.dumps(src2, ensure_ascii=False), "loser", "winner")
    d2 = json.loads(out2)
    assert d2["order"] == ["winner", "B"], d2["order"]
    assert d2["font"] == "x.ttf", d2["font"]
    passed += 1
    print("[OK] 2 dict: winner 既在 → loser 削除(重複回避)+ 他キー不変")

    # --- 3. 裸 list 形式: 裸 list のまま書き戻す(形状不変)・置換 ---
    out3 = _reassign_grid_json(json.dumps(["A", "loser", "B"], ensure_ascii=False), "loser", "winner")
    d3 = json.loads(out3)
    assert isinstance(d3, list), type(d3)
    assert d3 == ["A", "winner", "B"], d3
    passed += 1
    print("[OK] 3 bare list: 裸 list のまま + 位置維持で置換")

    # --- 4. 裸 list 形式: winner 既在 → loser 削除、裸 list のまま ---
    out4 = _reassign_grid_json(json.dumps(["winner", "loser"], ensure_ascii=False), "loser", "winner")
    d4 = json.loads(out4)
    assert isinstance(d4, list) and d4 == ["winner"], d4
    passed += 1
    print("[OK] 4 bare list: winner 既在 → loser 削除、裸 list のまま")

    # --- 5. loser が order に居ない → 変更不要(None)---
    assert _reassign_grid_json(json.dumps({"order": ["A", "B"]}), "loser", "winner") is None
    assert _reassign_grid_json(json.dumps(["A", "B"]), "loser", "winner") is None
    passed += 1
    print("[OK] 5 loser 不在 → None(変更なし)")

    # --- 6. null / 空文字 → None(スキップ扱い、例外を出さない)---
    assert _reassign_grid_json(None, "loser", "winner") is None
    assert _reassign_grid_json("", "loser", "winner") is None
    assert _reassign_grid_json("   ", "loser", "winner") is None
    passed += 1
    print("[OK] 6 null / 空文字 → None")

    # --- 7. 壊れた JSON → json.JSONDecodeError を送出(呼び出し側で握る契約)---
    raised = False
    try:
        _reassign_grid_json("{not valid json", "loser", "winner")
    except json.JSONDecodeError:
        raised = True
    assert raised, "壊れた JSON で JSONDecodeError が出るべき"
    passed += 1
    print("[OK] 7 壊れた JSON → json.JSONDecodeError 送出")

    # --- 8. 完全一致(前後空白は正規化しない): ' loser ' は 'loser' で置換されない ---
    assert _reassign_grid_json(json.dumps({"order": [" loser "]}), "loser", "winner") is None
    passed += 1
    print("[OK] 8 完全一致照合(前後空白ゆれは対象外・TimetableRow と同一意味論)")

    # --- 9. dict だが order が無い/list でない → None ---
    assert _reassign_grid_json(json.dumps({"font": "x"}), "loser", "winner") is None
    assert _reassign_grid_json(json.dumps({"order": "loser"}), "loser", "winner") is None
    passed += 1
    print("[OK] 9 order 欠落 / 非 list → None")

    print(f"\nALL PASS ({passed} groups)")


if __name__ == "__main__":
    run()
