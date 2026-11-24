"""精细块级 diff：回放转场后快照 vs 录制 54-62s 全谱。

回答：回放 58.5-62.2s 画面与录制哪个时刻最近、diff 多大、分布形态。
diff<5 = 同画面；5-13 = 相近（行级差异）；>20 = 不同画面。
"""
import sys, re
from pathlib import Path
import numpy as np
from PIL import Image

SHOTS = Path('data/demos/img')
RUN = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('data/demos/replay/demo_20260807_234704')

def block_mean(img, nb=8):
    h, w = img.shape[:2]
    bh, bw = h // nb, w // nb
    out = np.zeros((nb, nb, 3), dtype=float)
    for i in range(nb):
        for j in range(nb):
            out[i, j] = img[i*bh:(i+1)*bh, j*bw:(j+1)*bw].reshape(-1, 3).mean(axis=0)
    return out

def load(dirpath, pat):
    out = []
    for f in dirpath.glob('*.png'):
        m = re.search(pat, f.name)
        if not m:
            continue
        ts = int(m.group(1)) / 1000.0
        out.append((ts, np.asarray(Image.open(f).convert('RGB')).astype(int)))
    out.sort()
    return out

def bdiff(a, b, thr=12.0):
    return int((np.abs(block_mean(a) - block_mean(b)).sum(axis=2) > thr).sum())

def main():
    rec = load(SHOTS, r'^.*_t(\d+)\.png$')
    rp = load(RUN, r'^t(\d+)\.png$')
    rec54 = [(ts, im) for ts, im in rec if 54.0 <= ts <= 62.0]
    print(f"录制 54-62s: {len(rec54)} 张 | 回放: {len(rp)} 张")
    # 回放转场后快照（t>50s）逐张 vs 录制 54-62s 全谱
    for rts, rim in rp:
        if rts < 50.0:
            continue
        ds = [(d, bts) for bts, bim in rec54 for d in [bdiff(rim, bim)]]
        ds.sort()
        top = ds[:5]
        print(f"回放 {rts*1000:6.0f}ms (mean={rim.mean():.0f}): " +
              " | ".join(f"rec {t*1000:.0f}ms d={d}" for d, t in top))
    # 录制 60.0-62s 稳定段自对比（基线：稳定段帧间 diff）
    stab = [(ts, im) for ts, im in rec54 if 60.0 <= ts <= 62.0]
    ds = []
    for i in range(len(stab)):
        for j in range(i+1, len(stab)):
            ds.append(bdiff(stab[i][1], stab[j][1]))
    print(f"\n录制稳定段(60-62s)帧间块diff: n={len(ds)} 中位={np.median(ds):.0f} max={max(ds)}")

if __name__ == '__main__':
    main()
