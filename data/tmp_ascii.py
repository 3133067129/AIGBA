"""帧区域 ASCII 可视化：把指定帧的指定区域转成字符画（2x1 像素合并，亮度映射）。
用法: py -3.14 -u data/tmp_ascii.py [回放|rec] [t_ms] [y0 y1] [x0 x1]
  例:  py -3.14 -u data/tmp_ascii.py rp 90748 100 160 0 240
"""
import sys
from pathlib import Path
import numpy as np
from PIL import Image

SHOTS = Path('data/demos/img')
RUN = Path('data/demos/replay/demo_20260807_234704')
CHARS = ' .:-=+*#%@'

def load(path, pat):
    for f in Path(path).glob('*.png'):
        m = re_s(pat, f.name)
        if m:
            return np.asarray(Image.open(f).convert('RGB')).astype(int)
    return None

import re
def re_s(pat, s):
    m = re.search(pat, s)
    return m

def main():
    which, t, y0, y1, x0, x1 = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5]), int(sys.argv[6])
    if which == 'rec':
        f = None
        for f0 in SHOTS.glob('*.png'):
            if f0.name.endswith(f'_t{t:07d}.png'):
                f = f0
                break
        im = np.asarray(Image.open(f).convert('RGB')).astype(int) if f else None
    else:
        f = RUN / f't{t:07d}.png'
        im = np.asarray(Image.open(f).convert('RGB')).astype(int) if f.exists() else None
    if im is None:
        print(f"未找到帧 {which} {t}ms")
        return
    h, w = im.shape[:2]
    y0, y1 = max(0, y0), min(h, y1)
    x0, x1 = max(0, x0), min(w, x1)
    print(f"{which} {t}ms  区域 y[{y0}:{y1}] x[{x0}:{x1}]  mean={im[y0:y1, x0:x1].mean():.1f}")
    for y in range(y0, y1, 2):
        row = []
        for x in range(x0, x1, 2):
            m = im[y:y+2, x:x+2].reshape(-1, 3).mean()
            row.append(CHARS[min(9, int(m / 25.5))])
        print("".join(row))

if __name__ == '__main__':
    main()
