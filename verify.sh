#!/bin/bash
# verify.sh - コミット前必須ゲート。全チェック緑でないコミットは禁止。
set -e
echo "=== [1/2] py_compile: 全 .py ==="
git ls-files '*.py' | while read f; do
  python3 -m py_compile "$f" || exit 1
done
echo "COMPILE_OK"
echo "=== [2/2] pytest: スモーク + 回帰網 ==="
python3 -m pytest tests/test_smoke_apptest.py tests/test_tt_editor_repro.py tests/test_flyer_scale_link.py tests/test_tab_state_pinning.py tests/test_unified_save.py -v --disable-warnings
echo "=== VERIFY_ALL_GREEN ==="
