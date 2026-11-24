# -*- coding: utf-8 -*-
"""跳过对话框（y110-140 + 顶部 3 行）的全谱匹配。

回放帧 vs 录制全部快照——排除对话框干扰后，定位回放帧的真实场景时刻。
用法：py -3.14 -u data/tmp_full_match_nodlg.py <rp_t_ms> [<rp_t2> ...]
"""
import os, sys
import numpy as np
from PIL import Image

IMG = r"c:\Users\Administrator\Desktop\projects\AIGBA\data\demos\img"
REP = r"c:\Users\Administrator\Desktop\projects\AIGBA\data\demos\replay\demo_20260807_234704"

def load_img(p):
    return np.asarray(Image.open(p).convert("RGB")).astype(np.int16)

def dr(a, b, skip_top=3, skip_rows=set(range(110, 140))):
    """块级 8x8 diff，跳过顶部 skip_top 行 + 指定行段（对话框 y110-140）。"""
    h, w = a.shape[0] // 8 * 8, a.shape[1] // 8 * 8
    blocks = []
    for y0 in range(skip_top, h - 7, 8):
        yblk = y0 // 8
        if any(True for r in skip_rows if r // 8 == yblk):
            continue
        blocks.append((y0, y0 + 8))
    tot, diff = 0, 0.0
    for y0, y1 in blocks:
        aa = a[y0:y1].reshape(8, -1, 8, 3)
        bb = b[y0:y1].reshape(8, -1, 8, 3)
        # 8x8 块均值（含行内 8px 分块）
        am = aa.mean(axis=(0, 2))
        bm = bb.mean(axis=(0, 2))
        diff += float((np.abs(am - bm) > 20).mean()) * (y1 - y0)
        tot += (y1 - y0)
    return diff / tot if tot else 1.0

# 预载录制快照
shots = []
for f in sorted(os.listdir(IMG)):
    if f.endswith(".png"):
        base = f[:-4]
        if "_t" in base:
            t = int(base.rsplit("_t", 1)[1])
        else:
            t = int(base.rsplit("_", 1)[1])
        shots.append((t, load_img(os.path.join(IMG, f))))
print(f"载入录制快照 {len(shots)} 张")

for ts in sys.argv[1:]:
    t = int(ts)
    p = os.path.join(REP, f"t{t:07d}.png")
    if not os.path.exists(p):
        print(f"rp {t}: 帧不存在")
        continue
    a = load_img(p)
    best = sorted((dr(a, b), tt) for tt, b in shots)[:5]
    print(f"\n=== rp t{t}（abs {t}ms）最优匹配（跳过对话框）===")
    for d, tt in best:
        print(f"  {tt}ms  diff={d:.3f}")
    # 分段区间：走路段开头 107-120s 每 2s
    print("  --- 区间 107000-121000（每 2s）---")
    for tt, b in shots:
        if 107000 <= tt <= 121000 and tt % 2000 < 100:
            print(f"    rec {tt}  diff={dr(a, b):.3f}")
