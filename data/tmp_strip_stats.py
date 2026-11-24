"""round-22 帧条带统计：找 F_dlg1 的稳健判别条带。

对比盒期（104-117s）vs 无盒期（118-121.5s）vs 睡眠期（66-84s）的条带均值，
确定白盒（~185?）与房间亮度（~90）的稳健分离阈值。
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image

REPLAY_DIR = Path(__file__).resolve().parent.parent / "data/demos/replay/demo_20260807_234704"

def stats(t_abs):
    p = REPLAY_DIR / f"t{t_abs:07d}.png"
    if not p.exists():
        return None
    a = np.asarray(Image.open(p).convert("RGB"))
    return {
        "mean": float(a.mean()),
        "top6_58": float(a[6:58].mean()),
        "dlg110_140": float(a[110:140].mean()),
        "y124_158": float(a[124:158].mean()),
        "y126_158": float(a[126:158].mean()),
        "y132_156": float(a[132:156].mean()),
        "room16_120": float(a[16:120].mean()),
    }

def dump(tag, lo_s, hi_s):
    print(f"\n=== {tag}（{lo_s}-{hi_s}s 墙钟）")
    for s in range(lo_s, hi_s + 1, 2):
        st = stats(s * 1000 + 297)
        if st:
            print(f"  {s}s abs={s*1000+297}: mean={st['mean']:.1f} top={st['top6_58']:.1f} "
                  f"dlg110={st['dlg110_140']:.1f} y124={st['y124_158']:.1f} "
                  f"y126={st['y126_158']:.1f} y132={st['y132_156']:.1f} room={st['room16_120']:.1f}")

if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    if which in ("all", "sleep"):
        dump("睡眠期", 66, 88)
    if which in ("all", "dlg"):
        dump("盒期(对话1)", 104, 117)
    if which in ("all", "nobox"):
        dump("无盒期", 118, 122)
