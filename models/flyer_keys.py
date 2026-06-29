"""
FLYER_KEY_REGISTRY: フライヤー設定キーの単一情報源。

Phase 2B-1c-②b-1 で新設。
これまで views/flyer.py の init_s 呼び出し列と
gather_flyer_settings_from_session の base_keys / target_keys × style_params が
独立にハードコードされており、二重管理になっていた(P5 で指摘済み)。

本ファイルにキー名・default・persist フラグ・widget min/max を集約し、
views/flyer.py の init_s ループと gather がここから派生するようにする。

挙動不変ポリシー:
  - default は views/flyer.py の init_s 第二引数と完全一致させる(変更しない)。
  - persist=True の項目順は gather_flyer_settings_from_session の旧 base_keys 列と
    target_keys × style_params の二重ループ順に完全一致させる(JSON 出力順を保つ)。
  - persist=False の項目(grid_link / tt_link / preview_width)は init_s 対象だが
    gather/DB には載らない UI 専用フラグ。

Streamlit / DB に依存しないモジュール (純データのみ)。scratch/repro_flyer.py
から直接 import して挙動不変テストに使う。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional


@dataclass(frozen=True)
class FlyerKey:
    """1 個のフライヤー設定キーの定義。

    Attributes:
        short_key: "flyer_" プレフィックスを除いたキー名(DB JSON のキー)。
        default: init_s に渡すハードコード default。
        persist: True なら gather/DB 保存対象。False なら UI 専用。
        widget_min: 該当 widget(slider/number_input)の min_value。無ければ None。
        widget_max: 該当 widget の max_value。無ければ None。
    """
    short_key: str
    default: Any
    persist: bool = True
    widget_min: Optional[Any] = None
    widget_max: Optional[Any] = None


# ----------------------------------------------------------------------
# Base 区画 — views/flyer.py:144-182 の init_s 列をそのまま転記。
# 順序は gather の base_keys 列に合わせる(persist=True を抽出すれば旧 base_keys と
# 完全一致する並び)。persist=False (grid_link/tt_link/preview_width) は init_s
# 列の元位置に置く(gather はこれを skip するので JSON 順は変わらない)。
# ----------------------------------------------------------------------
BASE_ENTRIES: List[FlyerKey] = [
    FlyerKey("bg_id", 0),
    FlyerKey("logo_id", 0),
    FlyerKey("date_format", "EN"),
    FlyerKey("logo_scale", 1.0, widget_min=0.1, widget_max=2.0),
    FlyerKey("logo_pos_x", 0.0),
    FlyerKey("logo_pos_y", 0.0),
    FlyerKey("logo_shadow_on", False),
    FlyerKey("logo_shadow_color", "#000000"),
    FlyerKey("logo_shadow_opacity", 128, widget_min=0, widget_max=255),
    FlyerKey("logo_shadow_spread", 0, widget_min=0, widget_max=20),
    FlyerKey("logo_shadow_blur", 5, widget_min=0, widget_max=20),
    FlyerKey("logo_shadow_off_x", 5),
    FlyerKey("logo_shadow_off_y", 5),
    FlyerKey("grid_scale_w", 95, widget_min=10, widget_max=150),
    FlyerKey("grid_scale_h", 100, widget_min=10, widget_max=150),
    FlyerKey("grid_pos_y", 0),
    FlyerKey("tt_scale_w", 95, widget_min=10, widget_max=150),
    FlyerKey("tt_scale_h", 100, widget_min=10, widget_max=150),
    FlyerKey("tt_pos_y", 0),
    FlyerKey("grid_link", True, persist=False),
    FlyerKey("tt_link", True, persist=False),
    FlyerKey("subtitle_date_gap", 10),
    FlyerKey("date_venue_gap", 10),
    FlyerKey("ticket_gap", 20),
    FlyerKey("area_gap", 40),
    FlyerKey("note_gap", 15),
    FlyerKey("footer_pos_y", 0),
    # fallback_font の default はここでは静的 "keifont.ttf"。
    # views/flyer.py 側で SystemFontConfig 経由の動的 default を init_s に渡す
    # 呼び出しが先に走るため、レジストリ駆動ループの init_s はその後で発火しても
    # 「key 既存 → no-op」になる(挙動不変)。
    FlyerKey("fallback_font", "keifont.ttf"),
    FlyerKey("time_tri_visible", True),
    FlyerKey("time_tri_scale", 1.0, widget_min=0.1, widget_max=2.0),
    FlyerKey("time_line_gap", 0, widget_min=-100, widget_max=100),
    FlyerKey("time_alignment", "center"),
    FlyerKey("preview_width", 500, persist=False, widget_min=300, widget_max=1000),
    FlyerKey("show_buzz_logo", False),
]


# ----------------------------------------------------------------------
# Style 区画 — render_style_editor (views/flyer.py:246 付近) の init_s 列を
# 6 プレフィックス × 12 style param で展開。
# 順序は gather の二重ループ(外: target, 内: param)に合わせる。
# ----------------------------------------------------------------------
STYLE_PREFIXES = ("subtitle", "date", "venue", "time", "ticket_name", "ticket_note")

# 各 style param の (suffix, default, widget_min, widget_max)。
# render_style_editor の init_s 列 + widget 定義から抽出。
_STYLE_PARAM_SPECS = [
    ("font", "keifont.ttf", None, None),
    ("size", 50, 10, 200),                  # st.slider("ベースサイズ", 10, 200)
    ("color", "#FFFFFF", None, None),
    ("shadow_on", False, None, None),
    ("shadow_color", "#000000", None, None),
    ("shadow_blur", 2, 0, 20),              # st.slider("ぼかし", 0, 20)
    ("shadow_off_x", 5, None, None),
    ("shadow_off_y", 5, None, None),
    ("shadow_opacity", 255, 0, 255),        # st.slider("不透明度", 0, 255)
    ("shadow_spread", 0, 0, 10),            # st.slider("太さ", 0, 10)
    ("pos_x", 0, None, None),
    ("pos_y", 0, None, None),
]

STYLE_ENTRIES: List[FlyerKey] = [
    FlyerKey(f"{prefix}_{suffix}", default, widget_min=wmin, widget_max=wmax)
    for prefix in STYLE_PREFIXES
    for (suffix, default, wmin, wmax) in _STYLE_PARAM_SPECS
]


# ----------------------------------------------------------------------
# 公開: 全エントリの順序付きリスト
# ----------------------------------------------------------------------
FLYER_KEY_REGISTRY: List[FlyerKey] = BASE_ENTRIES + STYLE_ENTRIES


# ----------------------------------------------------------------------
# 開発確認用ユーティリティ
# ----------------------------------------------------------------------
def detect_default_min_mismatches() -> List[FlyerKey]:
    """default が widget_min と一致しないエントリを返す。

    これらは「init_s 不全 → widget が min を session_state に書き戻し → 保存」の
    退化ループ温床となるキー。Phase 2B-1c-②a の P1+P2 で防いだが、将来の widget
    追加・改修時にズレが再導入されていないか検出するための開発用関数。

    起動時には呼ばない(警告ログを出さない)。scratch/repro_flyer.py 等から呼ぶ。
    """
    out = []
    for entry in FLYER_KEY_REGISTRY:
        if entry.widget_min is None:
            continue
        if entry.default != entry.widget_min:
            out.append(entry)
    return out
