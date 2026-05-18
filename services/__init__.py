"""
ビジネスロジック層。

- view 層からはこの層のみを呼ぶ。
- DB 操作が必要な場合は repositories 経由で行う。
- ここでは Streamlit の session_state とのやり取りも担う。
"""
