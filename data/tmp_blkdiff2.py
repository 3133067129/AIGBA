# -*- coding: utf-8 -*-
"""两帧块级差异网格图：X = 8x8 块差异明显，o = 微差，. = 相同。

用法：py -3.14 -u data/tmp_blkdiff2.py <rec_t_ms> <rp_t_ms>
对比录制快照 t 与回放帧 t（跳过顶部 3 行）。
"""
import os, sys
import numpy as np
from PIL import Image

IMG = r"c:\Users\Administrator\Desktop\projects\AIGBA\data\demos\img"
REP = r"c:\Users\Administrator\Desktop\projects\AIGBA\data\demos\replay\demo_20260807_234704"

def load_rec(t_ms):
    for f in os.listdir(IMG):
        if f.endswith(f"_t{t_ms:07d}.png"):
            return np.asarray(Image.open(os.path.join(IMG, f)).convert("RGB")).astype(np.int16)
    return None

def load_rp(t_ms):
    p = os.path.join(REP, f"t{t_ms:07d}.png")
    if not os.path.exists(p):
        return None
    return np.asarray(Image.open(p).convert("RGB")).astype(np.int16)

rt, rp_t = int(sys.argv[1]), int(sys.argv[2])
if "--rprp" in sys.argv:
    a, b = load_rp(rt), load_rp(rp_t)
    label = f"rp {rt} vs rp {rp_t}"
elif "--rec-rec" in sys.argv:
    a, b = load_rec(rt), load_rec(rp_t)
    label = f"rec {rt} vs rec {rp_t}"
else:
    a, b = load_rec(rt), load_rp(rp_t)
    label = f"rec {rt} vs rp {rp_t}"
if a is None or b is None:
    print(f"载入失败 a={a is not None} b={b is not None}")
    sys.exit(1)

h, w = 160, 240
print(f"{label}：每块 8x8，X=差异块（均值差>20），o=微差（>8）")
for y0 in range(3, h, 8):
    row = ""
    for x0 in range(0, w, 8):
        aa = a[y0:y0 + 8, x0:x0 + 8].reshape(8, 8, 3).mean(axis=(0, 1))
        bb = b[y0:y0 + 8, x0:x0 + 8].reshape(8, 8, 3).mean(axis=(0, 1))
        d = float(np.abs(aa - bb).max())
        row += "X" if d > 20 else ("o" if d > 8 else ".")
    print(f"y{y0:3d} {row}")
