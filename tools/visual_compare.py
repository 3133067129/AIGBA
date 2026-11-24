"""rec vs rep 键盘屏区域视觉对比：拼 2x2 图保存。"""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import numpy as np
from pathlib import Path
from PIL import Image

REC = Path("data/demos/img")
OUT = Path("data/demos/replay/compare")

def crop(path, box=None):
    img = Image.open(path).convert("RGB")
    if box:
        img = img.crop(box)
    return img

pairs = [
    ("rec_48547", REC / "demo_20260807_234704_t0048547.png", None),
    ("rep_48532", Path("data/demos/replay/demo_20260807_234704/t0048531.png"), None),
    ("rep_49624", Path("data/demos/replay/demo_20260807_234704/t0049624.png"), None),
    ("rep_50599", Path("data/demos/replay/demo_20260807_234704/t0050499.png"), None),
    ("rec_49547", REC / "demo_20260807_234704_t0049547.png", None),
    ("rep_50608", Path("data/demos/replay/demo_20260807_234704/t0050608.png"), None),
]
OUT.mkdir(parents=True, exist_ok=True)
for name, p, box in pairs:
    if not p.exists():
        print(f"missing {p}")
        continue
    img = crop(p, box)
    img.save(OUT / f"{name}.png")
    print(f"saved {OUT/name}.png {img.size}")
