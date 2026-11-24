"""关键帧块级可视化：打印指定回放/录制帧的 7x8 块 mean（跳过顶部白条行）。
用法: py -3.14 -u data/tmp_frames.py [回放目录] [帧t1] [帧t2 ...]（回放帧）
      --rec [帧t1 ...] 查看录制帧
"""
import sys, re
from pathlib import Path
import numpy as np
from PIL import Image

SHOTS = Path('data/demos/img')
RUN = Path('data/demos/replay/demo_20260807_234704')

def load(path, pat):
    out = {}
    for f in Path(path).glob('*.png'):
        m = re.search(pat, f.name)
        if m:
            out[int(m.group(1))] = np.asarray(Image.open(f).convert('RGB')).astype(int)
    return out

def show(name, im):
    h, w = im.shape[:2]
    nb = 8
    bh, bw = h // nb, w // nb
    print(f"--- {name}  mean={im.mean():.1f} ---")
    for i in range(1, nb):
        row = []
        for j in range(nb):
            m = im[i*bh:(i+1)*bh, j*bw:(j+1)*bw].reshape(-1, 3).mean()
            row.append(f"{m:4.0f}")
        print("  " + " ".join(row))

rec = load(SHOTS, r'^.*_t(\d+)\.png$')
rp = load(RUN, r'^t(\d+)\.png$')
args = sys.argv[1:]
mode = 'rp'
for a in args:
    if a == '--rec':
        mode = 'rec'
        continue
    t = int(a)
    if mode == 'rp' and t in rp:
        show(f"回放 {t}ms", rp[t])
    elif mode == 'rec' and t in rec:
        show(f"录制 {t}ms", rec[t])
    else:
        print(f"未找到: {mode} {t}ms")
