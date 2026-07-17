"""logic_grid._downscale_max_edge の不変条件テスト(OOM 対策・§A2)。

- 1200px 超 → 最長辺 1200px 以下へ縮小・アスペクト比維持
- 1200px 以下 → 一切変更しない(拡大しない・同一オブジェクト)
- None → None

logic_grid の import が database(import 時に secrets/env 必須)を引くため、
read-only secrets を注入する conftest 前提で .venv 実行を想定。DB/ネットワークには触れない。
"""
from __future__ import annotations

from PIL import Image

from logic_grid import GRID_MAX_LOAD_EDGE, _downscale_max_edge


def test_downscale_large_landscape_keeps_aspect():
    img = Image.new("RGBA", (5766, 3844))  # id=13 の himawari 相当(22MP)
    out = _downscale_max_edge(img)
    assert max(out.size) <= GRID_MAX_LOAD_EDGE
    # アスペクト比維持(丸め誤差 1px 許容)
    assert abs(out.size[0] / out.size[1] - 5766 / 3844) < 0.01
    assert out.size[0] == GRID_MAX_LOAD_EDGE  # 横長なので長辺=幅=1200


def test_downscale_large_portrait_keeps_aspect():
    img = Image.new("RGBA", (2000, 4000))
    out = _downscale_max_edge(img)
    assert max(out.size) <= GRID_MAX_LOAD_EDGE
    assert out.size[1] == GRID_MAX_LOAD_EDGE  # 縦長なので長辺=高さ=1200


def test_no_upscale_small_image_untouched():
    img = Image.new("RGBA", (800, 450))  # タイル相当・1200px 以下
    out = _downscale_max_edge(img)
    assert out is img  # 同一オブジェクト(縮小も拡大もしない)
    assert out.size == (800, 450)


def test_boundary_exactly_max_edge_untouched():
    img = Image.new("RGBA", (1200, 600))
    out = _downscale_max_edge(img)
    assert out is img
    assert out.size == (1200, 600)


def test_none_passthrough():
    assert _downscale_max_edge(None) is None
