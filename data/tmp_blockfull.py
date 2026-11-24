"""全段块级复查：忽略顶部白条行（y<10，PrintWindow 标题栏伪影）的块级 diff。

回放快照 vs 录制全段逐张匹配。判别：diff<=3 同画面，4-12 相近，>20 真发散。
输出：每张回放快照的最优匹配 + 大 diff 帧列表（真发散点）。
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

def blocks_no_top(img, nb=8, skip_rows=1):
    """8x8 块均值，跳过顶部 skip_rows 行（白条区）→ (nb-skip_rows, nb, 3)"""
    h, w = img.shape[:2]
    bh = h // nb
    out = np.zeros((nb - skip_rows, nb, 3), dtype=float)
    for i in range(skip_rows, nb):
        for j in range(nb):
            out[i - skip_rows, j] = img[i*bh:(i+1)*bh, j*(w//nb):(j+1)*(w//nb)].reshape(-1, 3).mean(axis=0)
    return out

def main():
    rec = load(SHOTS, r'^.*_t(\d+)\.png$')
    rp = load(RUN, r'^t(\d+)\.png$')
    print(f"录制 {len(rec)} 张 | 回放 {len(rp)} 张")
    rec_b = [(ts, blocks_no_top(im)) for ts, im in rec]
    # 记录每张回放的最优匹配
    res = []
    for rts, rim in rp:
        rb = blocks_no_top(rim)
        d, bts = min((int((np.abs(rb - b).sum(axis=2) > 12).sum()), ts) for ts, b in rec_b)
        res.append((rts, d, bts))
    # 统计
    d_arr = np.array([r[1] for r in res])
    align = (d_arr <= 3).mean() * 100
    near = ((d_arr > 3) & (d_arr <= 12)).mean() * 100
    diverge = (d_arr > 20).mean() * 100
    print(f"同画面(<=3): {align:.1f}% | 相近(4-12): {near:.1f}% | 发散(>20): {diverge:.1f}%")
    print(f"diff 中位={np.median(d_arr):.0f} p90={np.percentile(d_arr, 90):.0f} max={d_arr.max():.0f}")
    # 发散点列表（连续段合并）
    div = [r for r in res if r[1] > 12]
    print(f"\n发散帧(diff>12): {len(div)} 张")
    for rts, d, bts in div[:40]:
        print(f"  回放 {rts*1000:7.0f}ms → 最优录制 {bts*1000:7.0f}ms diff={d}")

if __name__ == '__main__':
    main()
