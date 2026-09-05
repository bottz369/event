"""アー写未登録枠の黒プレースホルダ(段階C C-6a)のテスト。

実 DB / 実 Storage / 実 LINE には触らない。画像取得(_fetch_grid_images_parallel)を
monkeypatch し、生成された PIL 画像のピクセルを直接検査する。

守る不変条件:
  - 写真が無い枠は黒背景 + 案内文(日本語グリフが実際に描かれている = 豆腐でない)
  - 写真がある枠は従来どおり(見た目・レイアウトを変えない)
  - streamlit を import しない経路(API/Bot)でも同じ結果

★.venv 実行専用(logic_grid が cv2 を引くため verify.sh のゲートには入れない。
  既存の tests/test_bot_*.py と同じ扱い):
    .venv/bin/python3 -m pytest tests/test_grid_placeholder.py -v
"""
from __future__ import annotations

import os
import tempfile

import pytest
from PIL import Image

import logic_grid as lg


class _FakeArtist:
    def __init__(self, aid, name, image_filename=None):
        self.id = aid
        self.name = name
        self.image_filename = image_filename
        self.crop_scale = 1.0
        self.crop_x = 0
        self.crop_y = 0


@pytest.fixture(scope="module")
def jp_font_path():
    """日本語フォントを一時 FONT_DIR に materialize して実パスを返す。

    Storage からの read のみ(書き出しはローカル一時ディレクトリ)。
    """
    import tomli

    p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     ".streamlit", "secrets.readonly.toml")
    if not os.path.exists(p):
        pytest.skip("read-only secrets 未配置")
    creds = tomli.load(open(p, "rb"))["supabase"]
    import streamlit.runtime.secrets as st_secrets

    st_secrets.secrets_singleton._secrets = {"supabase": dict(creds)}
    # ★他のテスト(test_generation_service_import)が database を sys.modules から
    #   purge するため、streamlit を封じた状態で database が再 import されうる。
    #   そのとき st.secrets を読めないので env フォールバックを用意しておく
    #   (これが無いと実行順によってだけ落ちる)。
    os.environ.setdefault("SUPABASE_DB_URL", creds["DB_URL"])
    os.environ.setdefault("SUPABASE_URL", creds["URL"])
    os.environ.setdefault("SUPABASE_KEY", creds["KEY"])

    tmp = tempfile.mkdtemp(prefix="c6a_font_")
    import constants
    import services.font_service as fs

    constants.FONT_DIR = tmp
    fs.FONT_DIR = tmp
    if fs.ensure_font_available("keifont.ttf") == "not_found":
        pytest.skip("keifont.ttf を materialize できない")
    return os.path.join(tmp, "keifont.ttf")


def _white_pixels(img):
    return sum(1 for p in img.convert("L").getdata() if p > 200)


# ---------------------------------------------------------------------------
# プレースホルダ単体
# ---------------------------------------------------------------------------
def test_placeholder_is_black_with_visible_text(jp_font_path):
    img = lg.create_unregistered_photo_placeholder(800, 450, font_path=jp_font_path)

    assert img.size == (800, 450)
    # 四隅は黒(枠線の内側を見る)
    for xy in [(5, 5), (794, 5), (5, 444), (794, 444)]:
        r, g, b, _a = img.getpixel(xy)
        assert (r, g, b) == (0, 0, 0), f"{xy} が黒でない: {(r, g, b)}"
    # 案内文が実際に描かれている(日本語グリフが出ている = 豆腐でない)
    assert _white_pixels(img) > 500, "文字が描かれていない"


def test_placeholder_without_font_does_not_crash():
    """フォントが渡らなくても落ちない(黒枠は必ず返す)。"""
    img = lg.create_unregistered_photo_placeholder(400, 225, font_path=None)
    assert img.size == (400, 225)
    assert img.getpixel((5, 5))[:3] == (0, 0, 0)


@pytest.mark.parametrize("size", [(800, 450), (400, 225), (200, 112), (80, 45)])
def test_placeholder_fits_any_cell_size(jp_font_path, size):
    """小さいセルでも落ちず、最低限の文字が読める大きさで収まる。"""
    img = lg.create_unregistered_photo_placeholder(*size, font_path=jp_font_path)
    assert img.size == size
    assert _white_pixels(img) > 0, f"{size} で文字が全く描かれていない"


def test_placeholder_text_constants_carry_the_guidance():
    assert lg.UNREGISTERED_PHOTO_TITLE == "アー写未登録"
    assert "メンションを付けて" in lg.UNREGISTERED_PHOTO_GUIDE
    assert "アー写の新規登録を進めてください" in lg.UNREGISTERED_PHOTO_GUIDE


def test_existing_no_image_placeholder_is_untouched():
    """views/artists.py が使う既存の "No Image" は変えていない。"""
    img = lg.create_no_image_placeholder(100, 100)
    assert img.getpixel((1, 1))[:3] == (30, 30, 30), "既存 No Image の背景色が変わっている"
    assert img.size == (100, 100)


# ---------------------------------------------------------------------------
# グリッド生成に組み込まれているか
# ---------------------------------------------------------------------------
@pytest.fixture
def stub_fetch(monkeypatch):
    """_fetch_grid_images_parallel を差し替える(HTTP も DB も叩かない)。"""
    state = {"cache": {}}

    def _fake(target_artists, failures=None):
        return dict(state["cache"])

    monkeypatch.setattr(lg, "_fetch_grid_images_parallel", _fake)
    return state


def _solid(color, size=(1200, 800)):
    return Image.new("RGB", size, color).convert("RGBA")


def test_unregistered_artist_cell_is_black_placeholder(stub_fetch, jp_font_path):
    """写真が無いアーティストの枠が黒プレースホルダになる。"""
    artists = [_FakeArtist(1, "未登録グループ")]
    img = lg.generate_grid_image(artists, None, font_path=jp_font_path,
                                 row_counts=[1])
    assert img is not None

    # 画像エリアの左上あたり(名前ラベルは下部の白帯なので避ける)
    sample = img.convert("RGB").getpixel((40, 40))
    assert sample == (0, 0, 0), f"未登録枠が黒くない: {sample}"
    # 案内文が描かれている
    assert _white_pixels(img) > 500


def test_registered_artist_cell_keeps_the_photo(stub_fetch, jp_font_path):
    """写真がある枠は従来どおり写真が出る(黒くしない)。"""
    red = (220, 30, 30)
    stub_fetch["cache"][1] = _solid(red)
    artists = [_FakeArtist(1, "登録済みグループ", image_filename="a.jpg")]
    img = lg.generate_grid_image(artists, None, font_path=jp_font_path,
                                 row_counts=[1])

    sample = img.convert("RGB").getpixel((40, 40))
    assert sample == red, f"写真が置き換わっている: {sample}"


def test_mixed_grid_places_photo_and_placeholder_side_by_side(stub_fetch, jp_font_path):
    """登録済みと未登録が混在しても、それぞれ正しく描き分けられる。"""
    blue = (20, 60, 220)
    stub_fetch["cache"][1] = _solid(blue)
    artists = [
        _FakeArtist(1, "登録済み", image_filename="a.jpg"),
        _FakeArtist(2, "未登録"),
    ]
    img = lg.generate_grid_image(artists, None, font_path=jp_font_path,
                                 row_counts=[2]).convert("RGB")

    w = img.width
    left = img.getpixel((int(w * 0.12), 40))     # 1 枠目(登録済み)
    right = img.getpixel((int(w * 0.62), 40))    # 2 枠目(未登録)
    assert left == blue, f"登録済み枠が写真でない: {left}"
    assert right == (0, 0, 0), f"未登録枠が黒でない: {right}"


def test_render_exception_falls_back_to_placeholder(stub_fetch, jp_font_path,
                                                    monkeypatch):
    """加工中に例外が出ても穴を開けず、同じ案内を出す。"""
    stub_fetch["cache"][1] = _solid((10, 200, 10))

    def _boom(*a, **kw):
        raise RuntimeError("crop failed")

    monkeypatch.setattr(lg, "apply_manual_crop", _boom)
    artists = [_FakeArtist(1, "こわれた", image_filename="a.jpg")]
    img = lg.generate_grid_image(artists, None, font_path=jp_font_path,
                                 row_counts=[1])

    assert img is not None, "例外で画像そのものが失われている"
    assert img.convert("RGB").getpixel((40, 40)) == (0, 0, 0)


def test_artist_name_label_still_drawn_for_unregistered(stub_fetch, jp_font_path):
    """未登録でもアーティスト名ラベル(下部の白帯)は従来どおり出る。"""
    artists = [_FakeArtist(1, "未登録グループ")]
    img = lg.generate_grid_image(artists, None, font_path=jp_font_path,
                                 row_counts=[1]).convert("RGB")
    # 下部にラベル用の白背景帯がある
    band = [img.getpixel((x, img.height - 40)) for x in range(20, img.width - 20, 40)]
    assert any(p == (255, 255, 255) for p in band), "名前ラベルの白帯が無い"


def test_no_artists_still_returns_none(stub_fetch):
    assert lg.generate_grid_image([], None, font_path="keifont.ttf") is None


# ---------------------------------------------------------------------------
# streamlit-free 経路
# ---------------------------------------------------------------------------
def test_placeholder_path_is_streamlit_free(monkeypatch, jp_font_path):
    """streamlit が import 不能な Bot/API 環境でも同じ黒プレースホルダになる。"""
    import builtins
    import importlib
    import sys

    real_import = builtins.__import__
    original = sys.modules.get("logic_grid")

    def _blocked(name, *a, **kw):
        if name == "streamlit" or name.startswith("streamlit."):
            raise ImportError("streamlit is unavailable (simulated Bot env)")
        return real_import(name, *a, **kw)

    try:
        for m in list(sys.modules):
            if m == "logic_grid" or m == "streamlit" or m.startswith("streamlit."):
                sys.modules.pop(m, None)
        monkeypatch.setattr(builtins, "__import__", _blocked)

        mod = importlib.import_module("logic_grid")
        assert "streamlit" not in sys.modules

        img = mod.create_unregistered_photo_placeholder(800, 450,
                                                        font_path=jp_font_path)
        assert img.getpixel((5, 5))[:3] == (0, 0, 0)
        assert _white_pixels(img) > 500, "streamlit なし経路で案内文が出ていない"
    finally:
        if original is not None:
            sys.modules["logic_grid"] = original
