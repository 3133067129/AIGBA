"""差异块定位：回放快照 vs 最优匹配录制快照 → 8x8 块网格差异图。

输出每个块的 |Δ| 数值（0-255 均值），定位差异在对话框区（下中）还是场景区。
同时输出参考帧（0-45s 同画面帧）的差异图作对照。
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

def show_map(ba, bb, label):
    d = np.abs(ba - bb).sum(axis=2)  # (8,8)
    print(f"--- {label} 块均值差（每块 |Δ|，>12 计 diff）---")
    for i in range(8):
        row = " ".join(f"{d[i,j]:5.0f}" for j in range(8))
        print(f"  行{i}: {row}")
    nd = int((d > 12).sum())
    print(f"  diff块数={nd}")
    return nd

def main():
    rec = load(SHOTS, r'^.*_t(\d+)\.png$')
    rp = load(RUN, r'^t(\d+)\.png$')
    pairs = [
        (20.4, 20.0, '参照同画面帧'),      # 0-45s 对齐段
        (41.2, 53.0, 'Lua段前最后帧'),     # 45s 前
        (58.5, 56.5, '转场后(对话6行)'),   # 回放 58.5 → 录制 56.5
        (60.4, 60.0, '转场后(推进后)'),    # 回放 60.4 → 录制 60.0
    ]
    for r_ts, m_ts, label in pairs:
        rim = min(rp, key=lambda x: abs(x[0] - r_ts))[1]
        mim = min(rec, key=lambda x: abs(x[0] - m_ts))[1]
        show_map(block_mean(rim), block_mean(mim), f"{label} (回放{r_ts}s vs 录制{m_ts}s)")

if __name__ == '__main__':
    main()
