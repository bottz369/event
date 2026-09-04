"""タブ遅延描画で未保存編集が消えないこと(session_state ピン留め)の検証。

背景:
    「現在のタブのプレビューだけ再生成する」ためにタブを遅延描画
    (選択中のタブだけ render)へ移行した。しかし Streamlit は
    そのランで描画されなかったウィジェットの session_state を破棄するため、
    素直に遅延描画するとタブを切り替えるたびに未保存の編集が消える。

    このアプリは明示保存型(DB に入るのは保存ボタンだけ)なので、
    タブ移動で編集が失われるのは許容できない。views/workspace.py の
    _pin_session_keys() がランの先頭で保持対象キーを自身に再代入して延命する。

このファイルは (a) Streamlit の破棄挙動そのもの と (b) ピン留めで直ること を
同一の最小アプリで対比し、将来 Streamlit 側の挙動が変わったら気づけるようにする。
DB には一切アクセスしない。
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

PROBE = str(Path(__file__).parent / "fixtures" / "tab_pin_probe.py")


def _get(at, key):
    try:
        return at.session_state[key]
    except Exception:
        return "(キー消滅)"


def _run_probe(pin: bool):
    """A で入力 → B へ切替 → A へ戻す、を行い w_a の最終値を返す。"""
    from streamlit.testing.v1 import AppTest

    old = os.environ.get("PIN")
    os.environ["PIN"] = "1" if pin else "0"
    try:
        at = AppTest.from_file(PROBE, default_timeout=30).run()
        at.text_input(key="w_a").set_value("ユーザーが入力した値").run()
        assert _get(at, "w_a") == "ユーザーが入力した値"
        at.radio(key="tab").set_value("B").run()   # A は描画されない
        after_switch = _get(at, "w_a")
        at.run()                                    # B のまま再レンダー
        after_rerender = _get(at, "w_a")
        at.radio(key="tab").set_value("A").run()    # A へ戻す
        return after_switch, after_rerender, _get(at, "w_a"), at
    finally:
        if old is None:
            os.environ.pop("PIN", None)
        else:
            os.environ["PIN"] = old


def test_streamlit_discards_unrendered_widget_state():
    """前提の確認: ピン留めが無いと非表示タブのウィジェット値は破棄される。

    これが失敗するようになったら Streamlit 側の挙動が変わったということなので、
    _pin_session_keys() の必要性を見直してよい。
    """
    after_switch, after_rerender, back_in_a, _at = _run_probe(pin=False)
    assert after_switch == "(キー消滅)"
    assert after_rerender == "(キー消滅)"
    assert back_in_a == "", f"戻ったときに空文字へ戻るはずが {back_in_a!r}"


def test_pinning_preserves_unrendered_widget_state():
    """ピン留めすればタブ切替・再レンダーを跨いで未保存編集が保持される。"""
    after_switch, after_rerender, back_in_a, at = _run_probe(pin=True)
    assert not at.exception, f"ピン留めで例外: {at.exception}"
    assert after_switch == "ユーザーが入力した値"
    assert after_rerender == "ユーザーが入力した値"
    assert back_in_a == "ユーザーが入力した値"


@pytest.mark.parametrize(
    "button_key",
    [
        "btn_tt_generate",
        "btn_overview_save",
        "btn_proj_duplicate",
        "btn_grid_generate",
        "btn_none_flyer_logo_id",
        "del_t_39_1",
        "dl_tt_single",
        "tt_pending_rm_0",
        "csv_upload_key",
        "save_pos",
        "up_39",
        "tt_editor_0",
    ],
)
def test_pin_set_excludes_unsettable_widget_keys(button_key):
    """ボタン / download_button / file_uploader のキーは延命対象に入らない。

    これらは session_state 経由で値を設定できず、代入すると例外になる。
    tt_pending_rm_* は "tt_" 前置きだが除外側が勝つことも確認する。
    """
    from views.workspace import _pinned_keys

    assert button_key not in _pinned_keys([button_key])


def test_pin_set_includes_project_data_keys():
    """プロジェクトデータ系のキー(静的・動的とも)は延命対象に入る。"""
    from views.workspace import _pinned_keys

    dynamic = ["t_name_39_0", "t_price_39_1", "f_title_39_0", "txt_overview_preview_area"]
    pinned = _pinned_keys(dynamic)
    for k in dynamic:
        assert k in pinned, f"{k} が延命対象から漏れている"
    for k in ("tt_columns", "tt_font", "grid_font", "grid_order", "flyer_grid_scale_h"):
        assert k in pinned, f"{k} が延命対象から漏れている"
