"""逐帧分析 noLR 回放 47.5-48.7s 快照：亮度/红区/名字槽指纹 vs 录制对照。
定位键盘屏出现时刻 + 初始光标位置分叉点。
"""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import numpy as np
from pathlib import Path
from PIL import Image

REP = Path("data/demos/replay/demo_20260807_234704_noLR")
REC = Path("data/demos/img")


def red_boxes(img):
    """红区聚类（窗口坐标）→ [(y0,y1,x0,x1,count)]。"""
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


def name_slot_fp(img):
    """名字槽字符区指纹：窗口坐标 x40-100 y20-44（原生 x~30-95 y~16-35）。"""
    zone = img[20:44, 40:100]
    g = zone[:, :, 0].astype(int) + zone[:, :, 1].astype(int) + zone[:, :, 2].astype(int)
    return int((g < 300).sum())


def char_fp(img):
    """大字符显示区指纹：窗口坐标 x150-215 y50-110。"""
    zone = img[50:110, 150:215]
    g = zone[:, :, 0].astype(int) + zone[:, :, 1].astype(int) + zone[:, :, 2].astype(int)
    return int((g < 300).sum())


def analyze(path):
    img = np.asarray(Image.open(path).convert("RGB"))
    return float(img.mean()), red_boxes(img), name_slot_fp(img), char_fp(img)


print("=== 录制参考（500ms 间隔）===")
for t in ["0045547", "0047547", "0048047", "0048547", "0049047", "0049547", "0050047"]:
    p = REC / f"demo_20260807_234704_t{t}.png"
    if not p.exists():
        continue
    m, rb, nf, cf = analyze(p)
    print(f"rec {t}: mean={m:6.1f} 红区={rb} 名字槽={nf} 大字符={cf}")

print("\n=== noLR 回放（100ms 间隔）===")
for p in sorted(REP.glob("t0047*.png")) + sorted(REP.glob("t0048*.png")):
    m, rb, nf, cf = analyze(p)
    t = p.stem[1:]
    print(f"rep {t}: mean={m:6.1f} 红区={rb} 名字槽={nf} 大字符={cf}")
