"""时间约束块级匹配：回放每帧在录制 ±WIN 窗口内找最优匹配（跳过顶部白条行）。

比全谱匹配严格：冻结帧（原地不动）在窗口内找不到自己起源帧的后续帧 → diff
必然大。输出：每帧的匹配录制时间、时间漂移、diff；以及分段统计。

用法: py -3.14 -u data/tmp_blocktime.py [回放目录] [±窗口秒，默认3]
"""
import sys, re
from pathlib import Path
import numpy as np
from PIL import Image

SHOTS = Path('data/demos/img')
RUN = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('data/demos/replay/demo_20260807_234704')
WIN = float(sys.argv[2]) if len(sys.argv) > 2 else 3.0

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

def main():
    rec = load(SHOTS, r'^.*_t(\d+)\.png$')
    rp = load(RUN, r'^t(\d+)\.png$')
    print(f"录制 {len(rec)} 张 | 回放 {len(rp)} 张 | 匹配窗口 ±{WIN:.0f}s")
    rec_b = [(ts, blocks_no_top(im)) for ts, im in rec]
    rows = []
    for rts, rim in rp:
        rb = blocks_no_top(rim)
        lo, hi = rts - WIN, rts + WIN
        cands = [(b, ts) for ts, b in rec_b if lo <= ts <= hi]
        if not cands:
            rows.append((rts, -1, None, 999))
            continue
        d, bts = min((bdiff(rb, b), ts) for b, ts in cands)
        rows.append((rts, d, bts, rts - bts))
    # 统计
    d_arr = np.array([r[1] for r in rows])
    off = [r[3] for r in rows if r[3] is not None]
    align = (d_arr <= 3).mean() * 100
    near = ((d_arr > 3) & (d_arr <= 12)).mean() * 100
    diverge = (d_arr > 12).mean() * 100
    print(f"同画面(<=3): {align:.1f}% | 相近(4-12): {near:.1f}% | 发散(>12): {diverge:.1f}%")
    print(f"diff 中位={np.median(d_arr):.0f} p90={np.percentile(d_arr, 90):.0f} max={d_arr.max():.0f}")
    print(f"时间漂移 中位={np.median(off):+.0f}ms 范围=[{min(off)*1000:+.0f}, {max(off)*1000:+.0f}]ms")
    # 大 diff 帧
    bad = [r for r in rows if r[1] > 12]
    print(f"\n发散帧(diff>12): {len(bad)} 张")
    for rts, d, bts, offs in bad[:50]:
        bt = f"匹配录制 {bts*1000:.0f}ms" if bts is not None else "无候选"
        print(f"  回放 {rts*1000:7.0f}ms → {bt} diff={d} 漂移{offs*1000:+.0f}ms")
    # 连续冻结段检测：同 diff 连续 ≥4 张
    print("\n连续同值帧段（冻结候选）：")
    n = 1
    for i in range(1, len(rows)):
        same = rows[i][1] == rows[i-1][1] and rows[i][3] is not None and rows[i-1][3] is not None
        if same:
            n += 1
        else:
            if n >= 4:
                seg = rows[i-n:i]
                print(f"  {seg[0][0]*1000:.0f}-{seg[-1][0]*1000:.0f}ms diff={seg[0][1]} x{n} 张")
            n = 1
    if n >= 4:
        seg = rows[len(rows)-n:]
        print(f"  {seg[0][0]*1000:.0f}-{seg[-1][0]*1000:.0f}ms diff={seg[0][1]} x{n} 张")

if __name__ == '__main__':
    main()
