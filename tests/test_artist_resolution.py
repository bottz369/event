"""未解決アーティストをセルとして残す解決ヘルパ(#4 案1)のテスト。

背景:
    repositories.artist_repo.get_artists_by_names は「artists に無い名前は skip」
    という既存仕様。そのまま grid に渡すと未登録の出演者の枠ごと消え、
    「TT には出るのにアー写グリッドに出ない」になる(実機 id=40 の Luna moon)。
    services.artist_service.resolve_artists_in_order が未登録名にスタンドインを立て、
    C-6a の黒プレースホルダで可視化する。

★実 DB には触らない(get_artists_by_names を差し替える)。
★.venv 実行専用(logic_grid が cv2 を引くため verify.sh のゲートには入れない)。
"""
from __future__ import annotations

import hashlib
import io as _io

import pytest
from PIL import Image

from models.artist import ArtistView
from services import artist_service as asvc


def _view(aid, name, image_filename="x.jpg"):
    return ArtistView(id=aid, name=name, image_filename=image_filename,
                      is_deleted=False, crop_scale=1.0, crop_x=0, crop_y=0)


@pytest.fixture
def registered(monkeypatch):
    """artists に登録済みの名前だけを返すスタブ(既存仕様どおり skip する)。"""
    state = {"known": {}}

    def _get(names):
        return [state["known"][n] for n in names if n in state["known"]]

    monkeypatch.setattr(asvc, "get_artists_by_names", _get)
    return state


# ---------------------------------------------------------------------------
# 解決ヘルパ
# ---------------------------------------------------------------------------
def test_all_registered_returns_them_in_order(registered):
    registered["known"] = {"A": _view(1, "A"), "B": _view(2, "B")}
    out = asvc.resolve_artists_in_order(["A", "B"])
    assert [a.id for a in out] == [1, 2]
    assert [a.name for a in out] == ["A", "B"]


def test_unregistered_name_is_kept_as_a_cell(registered):
    """未登録でも落とさず、写真なしのスタンドインとして返す(#4 の本丸)。"""
    registered["known"] = {"アルテミスの翼": _view(8, "アルテミスの翼")}
    out = asvc.resolve_artists_in_order(["アルテミスの翼", "Luna moon"])

    assert len(out) == 2, "未登録の名前が落ちている"
    assert out[1].name == "Luna moon"
    assert out[1].image_filename is None, "スタンドインに写真があってはいけない"
    assert out[1].id < 0, "スタンドインの id は負でなければならない"


def test_multiple_unregistered_get_unique_negative_ids(registered):
    """未登録が複数あっても dedupe で潰れない(_fetch_grid_images_parallel は id で dedupe)。"""
    registered["known"] = {"B": _view(2, "B")}
    out = asvc.resolve_artists_in_order(["X", "B", "Y", "Z"])

    assert [a.name for a in out] == ["X", "B", "Y", "Z"]
    neg_ids = [a.id for a in out if a.id < 0]
    assert len(neg_ids) == 3
    assert len(set(neg_ids)) == 3, f"負 id が重複している: {neg_ids}"


def test_order_and_duplicates_are_preserved(registered):
    registered["known"] = {"A": _view(1, "A")}
    out = asvc.resolve_artists_in_order(["A", "未登録", "A"])
    assert [a.name for a in out] == ["A", "未登録", "A"]


def test_empty_names_returns_empty(registered):
    assert asvc.resolve_artists_in_order([]) == []
    assert asvc.resolve_artists_in_order(None) == []


def test_standin_is_not_persisted(registered, monkeypatch):
    """スタンドインは描画用の一時オブジェクト。DB へは書かない。"""
    registered["known"] = {}
    monkeypatch.setattr(asvc, "SessionLocal",
                        lambda *a, **k: pytest.fail("解決ヘルパが DB を開いた"))
    out = asvc.resolve_artists_in_order(["未登録"])
    assert out[0].name == "未登録"


def test_get_artists_by_names_behaviour_is_untouched():
    """既存仕様(無い名前は skip)は変えない。差し込みは service 側だけ。"""
    src = open("repositories/artist_repo.py", encoding="utf-8").read()
    assert "return [by_name[n] for n in names if n in by_name]" in src


# ---------------------------------------------------------------------------
# failures への積み上げ(#4 案2 のデータ側)
# ---------------------------------------------------------------------------
def test_unresolved_names_are_reported_in_failures(registered):
    registered["known"] = {"B": _view(2, "B")}
    failures = []
    asvc.resolve_artists_in_order(["X", "B", "Y"], failures=failures)

    assert failures == [
        {"kind": asvc.FAILURE_KIND_ARTIST_NOT_REGISTERED, "name": "X"},
        {"kind": asvc.FAILURE_KIND_ARTIST_NOT_REGISTERED, "name": "Y"},
    ]


def test_no_failures_when_all_registered(registered):
    registered["known"] = {"A": _view(1, "A")}
    failures = []
    asvc.resolve_artists_in_order(["A"], failures=failures)
    assert failures == []


def test_failures_is_optional(registered):
    registered["known"] = {}
    asvc.resolve_artists_in_order(["X"])  # 例外にならない


# ---------------------------------------------------------------------------
# 実際のグリッド描画に効くこと
# ---------------------------------------------------------------------------
def _png_sha(img):
    buf = _io.BytesIO()
    img.save(buf, format="PNG")
    return hashlib.sha256(buf.getvalue()).hexdigest()


def _solid(color):
    return Image.new("RGB", (1200, 800), color).convert("RGBA")


def test_grid_keeps_a_cell_for_unregistered_artist(registered, monkeypatch):
    """未登録が混ざっても枠数が減らず、その枠が黒プレースホルダになる。"""
    import logic_grid as lg

    registered["known"] = {"登録済み": _view(1, "登録済み")}
    monkeypatch.setattr(lg, "_fetch_grid_images_parallel",
                        lambda arts, failures=None: {1: _solid((200, 30, 30))})

    artists = asvc.resolve_artists_in_order(["登録済み", "未登録グループ"])
    img = lg.generate_grid_image(artists, None, font_path="keifont.ttf",
                                 row_counts=[2]).convert("RGB")

    w = img.width
    left = img.getpixel((int(w * 0.12), 40))
    right = img.getpixel((int(w * 0.62), 40))
    assert left == (200, 30, 30), f"登録済みの枠が写真でない: {left}"
    assert right == (0, 0, 0), f"未登録の枠が黒プレースホルダでない: {right}"


def test_grid_render_is_byte_identical_when_all_registered(registered, monkeypatch):
    """全員登録済みなら描画は従来と完全に一致する(スタンドインを混ぜない)。

    resolve_artists_in_order を通した結果と、素の get_artists_by_names を
    通した結果で同じ PNG になることを SHA256 で証明する。
    """
    import logic_grid as lg

    known = {"A%d" % i: _view(i, "A%d" % i) for i in range(1, 8)}
    registered["known"] = known
    cache = {i: _solid((30 * i % 255, 80, 200 - 20 * i)) for i in range(1, 8)}
    monkeypatch.setattr(lg, "_fetch_grid_images_parallel",
                        lambda arts, failures=None: dict(cache))

    names = list(known.keys())
    before = lg.generate_grid_image(asvc.get_artists_by_names(names), None,
                                    font_path="keifont.ttf", row_counts=[4, 3])
    after = lg.generate_grid_image(asvc.resolve_artists_in_order(names), None,
                                   font_path="keifont.ttf", row_counts=[4, 3])
    assert _png_sha(before) == _png_sha(after), "解決済みのみの描画が変わっている"


def test_both_grid_paths_go_through_the_service_helper():
    """view / generation_service の両方が service ヘルパを通ること(3層規律)。"""
    gen = open("services/generation_service.py", encoding="utf-8").read()
    view = open("views/grid.py", encoding="utf-8").read()
    for src, label in ((gen, "generation_service"), (view, "views/grid.py")):
        assert "resolve_artists_in_order(" in src, f"{label} がヘルパを通っていない"
        assert "get_artists_by_names(" not in src, f"{label} が repo 相当を直呼びしている"
