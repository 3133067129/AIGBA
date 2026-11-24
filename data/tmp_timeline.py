"""逐帧时间线：回放 t → diff → 匹配录制 t → 漂移 → 亮度（60-115s 段）。
用法: py -3.14 -u data/tmp_timeline.py [回放目录] [起点s] [终点s]"""
import sys, re
from pathlib import Path
import numpy as np
from PIL import Image

SHOTS = Path('data/demos/img')
RUN = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('data/demos/replay/demo_20260807_234704')
T0 = float(sys.argv[2]) if len(sys.argv) > 2 else 60.0
T1 = float(sys.argv[3]) if len(sys.argv) > 3 else 115.0

def load(path, pat):
    out = []
    for f in Path(path).glob('*.png'):
        m = re.search(pat, f.name)
        if not m:
            continue
        ts = int(m.group(1)) / 1000.0
        out.append((ts, np.asarray(Image.open(f).convert('RGB')).astype(int)))
    out.sort()
    return out

def blocks_no_top(img, nb=8, skip_rows=1):
    h, w = img.shape[:2]
    bh = h // nb
    out = np.zeros((nb - skip_rows, nb, 3), dtype=float)
    for i in range(skip_rows, nb):
        for j in range(nb):
            out[i - skip_rows, j] = img[i*bh:(i+1)*bh, j*(w//nb):(j+1)*(w//nb)].reshape(-1, 3).mean(axis=0)
    return out

def bdiff(a, b, thr=12.0):
    return int((np.abs(a - b).sum(axis=2) > thr).sum())

rec = load(SHOTS, r'^.*_t(\d+)\.png$')
rp = load(RUN, r'^t(\d+)\.png$')
rec_b = [(ts, blocks_no_top(im)) for ts, im in rec]
print(f"回放 {len(rp)} 张 | 段 [{T0:.0f}s, {T1:.0f}s]")
for rts, rim in rp:
    if not (T0 <= rts <= T1):
        continue
    rb = blocks_no_top(rim)
    lo, hi = rts - 3, rts + 3
    cands = [(b, ts) for ts, b in rec_b if lo <= ts <= hi]
    if not cands:
        print(f"  {rts*1000:7.0f}ms  (无候选) mean={rim.mean():.1f}")
        continue
    d, bts = min((bdiff(rb, b), ts) for b, ts in cands)
    print(f"  {rts*1000:7.0f}ms → {bts*1000:7.0f}ms diff={d:3d} 漂移{(rts-bts)*1000:+7.0f}ms mean={rim.mean():6.1f}")
