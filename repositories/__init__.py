"""
DB操作を集約するレイヤー。

- 直接の SQLAlchemy 操作はこの層に閉じ込める。
- service 層からのみ呼ばれる想定。
- view 層からは直接呼ばない(必ず service を介する)。
"""
