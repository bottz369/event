"""タブ遅延描画時の session_state 破棄/延命を検証するための最小アプリ。

tests/test_tab_state_pinning.py からのみ使う。PIN 環境変数でピン留めの
有無を切り替え、Streamlit 本体の挙動と対処の効果を同一条件で比較する。
"""
import os

import streamlit as st

if "tab" not in st.session_state:
    st.session_state.tab = "A"

if os.environ.get("PIN") == "1":
    for _k in ("w_a", "w_b"):
        if _k in st.session_state:
            st.session_state[_k] = st.session_state[_k]

st.radio("tab", ["A", "B"], key="tab", horizontal=True)

if st.session_state.tab == "A":
    st.text_input("only in A", key="w_a")
else:
    st.text_input("only in B", key="w_b")
