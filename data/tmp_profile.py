"""行级 mean 剖面：回放 vs 录制各帧每 10px 行的 mean 曲线 + 每帧整体 mean。

定位顶部整行差异（回放 58.5/60.4 vs 录制 56.5/60.0/61.0/62.0）。
"""
import sys, re
from pathlib import Path
import numpy as np
from PIL import Image

SHOTS = Path('data/demos/img')
RUN = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('data/demos/replay/demo_20260807_234704')

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

def row_profile(im, h=10):
    """每 h 像素一行的整体 mean → 一维数组"""
    return im.reshape(-1, h, im.shape[1], 3).mean(axis=(1, 2, 3))

def main():
    rec = load(SHOTS, r'^.*_t(\d+)\.png$')
    rp = load(RUN, r'^t(\d+)\.png$')
    targets = [
        ('回放 58.5s', min(rp, key=lambda x: abs(x[0]-58.5))),
        ('回放 60.4s', min(rp, key=lambda x: abs(x[0]-60.4))),
        ('录制 56.5s', min(rec, key=lambda x: abs(x[0]-56.5))),
        ('录制 60.0s', min(rec, key=lambda x: abs(x[0]-60.0))),
        ('录制 61.0s', min(rec, key=lambda x: abs(x[0]-61.0))),
        ('录制 62.0s', min(rec, key=lambda x: abs(x[0]-62.0))),
        ('录制 53.5s', min(rec, key=lambda x: abs(x[0]-53.5))),
        ('录制 51.0s', min(rec, key=lambda x: abs(x[0]-51.0))),
    ]
    profs = {}
    for label, (ts, im) in targets:
        profs[label] = row_profile(im)
        print(f"{label}: t={ts*1000:.0f}ms mean={im.mean():.1f}")
    print()
    # 打印行剖面表（每 10px 行，0-15 共 16 行）
    print("行剖面（y 每 10px，RGB mean）：")
    print(f"{'y':>5}" + "".join(f"{l:>14}" for l, _ in targets))
    for y in range(16):
        vals = [profs[l][y] for l, _ in targets]
        print(f"{y*10:>4}" + "".join(f"{v:14.1f}" for v in vals))
    # 差异对：回放 58.5 vs 录制 56.5/60.0/61.0；回放 60.4 vs 录制 60.0/61.0/62.0
    print()
    pairs = [('回放58.5-录56.5', '回放 58.5s', '录制 56.5s'),
             ('回放58.5-录60.0', '回放 58.5s', '录制 60.0s'),
             ('回放58.5-录61.0', '回放 58.5s', '录制 61.0s'),
             ('回放60.4-录60.0', '回放 60.4s', '录制 60.0s'),
             ('回放60.4-录61.0', '回放 60.4s', '录制 61.0s'),
             ('回放60.4-录62.0', '回放 60.4s', '录制 62.0s')]
    print("逐行 |Δ|：")
    print(f"{'y':>5}" + "".join(f"{p[0]:>14}" for p in pairs))
    for y in range(16):
        vals = [abs(profs[p[1]][y] - profs[p[2]][y]) for p in pairs]
        print(f"{y*10:>4}" + "".join(f"{v:14.1f}" for v in vals))

if __name__ == '__main__':
    main()
