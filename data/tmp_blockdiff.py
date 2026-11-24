"""块级 diff 分析：抗窗口缩放伪影的「回放快照 vs 录制快照」对齐验证。

问题：回放窗口 1278x704（用户拉大）vs 录制窗口 240x160，capture_hwnd NEAREST
resize 到 240x160 有采样错位伪影 → 同一画面像素级 diff≈2059px（5.4%），
像素级判别力丧失。块级（8x8 块均值）diff：NEAREST 1px 错位对 30x20 像素块
均值影响 <0.5%，真画面差异（文本行/光标/名字）改变块均值 → 判别力恢复。

判别力基线（录制原始快照间）：
- 同状态重复帧 vs 不同状态帧的块 diff 分布 → 确定阈值

用法：py -3.14 data/tmp_blockdiff.py <run_dir>
"""
import sys, re
from pathlib import Path
import numpy as np
from PIL import Image

SHOTS = Path('data/demos/img')
RUN = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('data/demos/replay/demo_20260807_234704')

def block_mean(img: np.ndarray, nb: int = 8) -> np.ndarray:
    """240x160 → nb*nb 块均值（RGB 3 通道），返回 (nb, nb, 3)"""
    h, w = img.shape[:2]
    bh, bw = h // nb, w // nb
    out = np.zeros((nb, nb, 3), dtype=float)
    for i in range(nb):
        for j in range(nb):
            out[i, j] = img[i*bh:(i+1)*bh, j*bw:(j+1)*bw].reshape(-1, 3).mean(axis=0)
    return out

def load_shots(dirpath: Path, t0=0.0, t1=760.0):
    out = []
    for f in dirpath.glob('*.png'):
        m = re.search(r'(?:.*_t|t)(\d+)\.png', f.name)
        if not m:
            continue
        ts = int(m.group(1)) / 1000.0
        if t0 <= ts <= t1:
            out.append((ts, np.asarray(Image.open(f).convert('RGB')).astype(int)))
    out.sort()
    return out

def diff_blocks(a: np.ndarray, b: np.ndarray, thr: float = 12.0) -> int:
    """块均值差超阈值的块数（0-64）。thr=12/255 约等于可见差异"""
    return int((np.abs(block_mean(a) - block_mean(b)).sum(axis=2) > thr).sum())

def main():
    rec = load_shots(SHOTS)
    rp = load_shots(RUN)
    print(f"录制 {len(rec)} 张 | 回放 {len(rp)} 张")
    # 预计算录制块向量
    rec_blocks = [(ts, block_mean(im)) for ts, im in rec]
    # 判别力基线：录制相邻快照的块 diff（<1s 间隔 = 通常同状态）
    import collections
    d_adj, d_mid = [], []
    for i in range(1, len(rec)):
        dt = rec[i][0] - rec[i-1][0]
        d = diff_blocks(rec[i][1], rec[i-1][1])
        if dt < 0.7:
            d_adj.append(d)
    # 间隔 5-10s 的对（通常已不同状态，但同场景也可能稳定）——采样 300 对
    step = max(1, len(rec) // 300)
    for i in range(0, len(rec) - 10, step):
        j = min(i + 10, len(rec) - 1)
        d = diff_blocks(rec[i][1], rec[j][1])
        d_mid.append(d)
    print(f"基线 相邻(<0.7s)块diff: n={len(d_adj)} 中位={np.median(d_adj):.0f} p90={np.percentile(d_adj,90):.0f}")
    print(f"基线 间隔5-10s块diff: n={len(d_mid)} 中位={np.median(d_mid):.0f} p90={np.percentile(d_mid,90):.0f}")
    print("\n回放时间线（回放t → 最优匹配录制t → 块diff）：")
    print("  " + "-" * 72)
    for ts, im in rp:
        best = min(rec_blocks, key=lambda r: np.abs(r[1] - block_mean(im)).sum())
        d = diff_blocks(im, np.zeros_like(im))  # 占位
        # 重算真实块 diff
        d = int((np.abs(block_mean(im) - best[1]).sum(axis=2) > 12.0).sum())
        drift = ts - best[0]
        print(f"  t={ts*1000:6.0f}ms → rec {best[0]*1000:6.0f}ms  块diff={d:2d}  漂移={drift:+.1f}s")

if __name__ == '__main__':
    main()
