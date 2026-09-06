#!/bin/bash
# verify.sh - コミット前必須ゲート。全チェック緑でないコミットは禁止。
set -e
echo "=== [1/2] py_compile: 全 .py ==="
git ls-files '*.py' | while read f; do
  python3 -m py_compile "$f" || exit 1
done
echo "COMPILE_OK"
echo "=== [2/2] pytest: スモーク + 回帰網 ==="
# ★AppTest を使うテストは先に並べる。tests/test_event_intake.py の
#   streamlit-free 検証が streamlit を import 不能にして再 import するため、
#   その後ろに置いた AppTest 系は st.cache_data の状態が壊れて落ちる。
python3 -m pytest tests/test_smoke_apptest.py tests/test_tt_editor_repro.py tests/test_flyer_scale_link.py tests/test_tab_state_pinning.py tests/test_unified_save.py tests/test_planned_artist_count_ui.py tests/test_event_intake.py tests/test_timetable_engine.py tests/test_text_generator.py -v --disable-warnings
echo "=== VERIFY_ALL_GREEN ==="
