"""分析指定回放目录 46-52s 快照：亮度/红区/名字槽/大字符区。"""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import numpy as np
from pathlib import Path
from PIL import Image

REP = Path(sys.argv[1] if len(sys.argv) > 1 else "data/demos/replay/demo_20260807_234704")


def red_boxes(img):
    r = img[:, :, 0].astype(int); g = img[:, :, 1].astype(int); b = img[:, :, 2].astype(int)
    red = (r > 150) & (g < 100) & (b < 100)
    if red.sum() == 0:
        return []
    ys, xs = np.where(red)
    y_sorted = np.sort(np.unique(ys))
    groups, cur = [], [y_sorted[0]]
    for y in y_sorted[1:]:
        if y - cur[-1] <= 8:
            cur.append(y)
        else:
            groups.append(cur); cur = [y]
    groups.append(cur)
    out = []
    for gys in groups:
        m = np.isin(ys, gys)
        out.append((int(gys[0]), int(gys[-1]), int(xs[m].min()), int(xs[m].max()), int(xs[m].size)))
    return out


def fps(img, y0, y1, x0, x1):
    zone = img[y0:y1, x0:x1]
    g = zone[:, :, 0].astype(int) + zone[:, :, 1].astype(int) + zone[:, :, 2].astype(int)
    return int((g < 300).sum())


files = []
for pat in ["t0046*.png", "t0047*.png", "t0048*.png", "t0049*.png", "t0050*.png", "t0051*.png"]:
    files += sorted(REP.glob(pat))
for p in files:
    img = np.asarray(Image.open(p).convert("RGB"))
    m = float(img.mean())
    rb = red_boxes(img)
    ns = fps(img, 20, 44, 40, 100)
    cf = fps(img, 50, 110, 150, 215)
    print(f"{p.stem[1:]}: mean={m:6.1f} 红区={rb} 名字槽={ns} 大字符={cf}")
