# -*- coding: utf-8 -*-
"""TT downscale-on-load の知覚品質 parity 判定(grid の parity_grid13.py と同型)。

完全一致は求めない(リサンプリングが1段増えるため)。
「知覚できないレベル」であることを数値で示す:
  - canvas サイズ一致
  - 全体 MAE(RGB / アルファ)
  - 差分 > 16 の画素割合
  - 64x64 ブロックの最大 MAE
  - MAE > 10 のブロック数

使い方: .venv/bin/python3 scratch/parity_tt_downscale.py <before_dir> <after_dir>
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None

before_dir, after_dir = Path(sys.argv[1]), Path(sys.argv[2])
BLOCK = 64
fails = 0

# 判定しきい値(grid の §45 A2 と同水準)
TH_MAE = 2.0          # 全体 MAE
TH_DIFF16_PCT = 1.0   # 差分>16 の画素割合(%)
TH_BLOCK_MAE = 25.0   # 最大ブロック MAE
TH_BLOCKS_10 = 2.0    # MAE>10 のブロック割合(%)

print("%-8s %-13s %8s %8s %10s %10s %10s" %
      ("project", "canvas", "MAE", "MAE(A)", ">16画素%", "maxBlkMAE", "blk>10 %"))
print("-" * 78)

for bp in sorted(before_dir.glob("tt_*.png")):
    ap = after_dir / bp.name
    if not ap.exists():
        print("  %s: after が無い" % bp.name); fails += 1; continue

    b = Image.open(bp).convert("RGBA")
    a = Image.open(ap).convert("RGBA")
    if b.size != a.size:
        print("  %s: ★canvas 不一致 %s vs %s" % (bp.name, b.size, a.size)); fails += 1; continue

    nb = np.asarray(b, dtype=np.int16)
    na = np.asarray(a, dtype=np.int16)
    diff = np.abs(nb - na)

    mae_rgb = float(diff[:, :, :3].mean())
    mae_a = float(diff[:, :, 3].mean())
    # 画素単位の最大チャネル差
    pix_max = diff[:, :, :3].max(axis=2)
    pct_gt16 = float((pix_max > 16).mean() * 100.0)

    h, w = pix_max.shape
    bh, bw = h // BLOCK, w // BLOCK
    if bh and bw:
        crop = diff[:bh * BLOCK, :bw * BLOCK, :3].astype(np.float32)
        blocks = crop.reshape(bh, BLOCK, bw, BLOCK, 3).mean(axis=(1, 3, 4))
        max_blk = float(blocks.max())
        pct_blk10 = float((blocks > 10).mean() * 100.0)
    else:
        max_blk, pct_blk10 = 0.0, 0.0

    ok = (mae_rgb <= TH_MAE and pct_gt16 <= TH_DIFF16_PCT
          and max_blk <= TH_BLOCK_MAE and pct_blk10 <= TH_BLOCKS_10)
    if not ok:
        fails += 1

    print("%-8s %-13s %8.4f %8.4f %9.3f%% %10.2f %9.3f%%  %s"
          % (bp.stem.replace("tt_", ""), "%dx%d" % b.size, mae_rgb, mae_a,
             pct_gt16, max_blk, pct_blk10, "OK" if ok else "★NG"))

print("-" * 78)
print("しきい値: MAE<=%.1f / >16画素<=%.1f%% / maxBlkMAE<=%.1f / blk>10<=%.1f%%"
      % (TH_MAE, TH_DIFF16_PCT, TH_BLOCK_MAE, TH_BLOCKS_10))
print()
print("TT_DOWNSCALE_PARITY_OK" if fails == 0 else "TT_DOWNSCALE_PARITY_NG (%d)" % fails)
sys.exit(0 if fails == 0 else 1)
