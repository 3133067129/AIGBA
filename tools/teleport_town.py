"""未白镇瞬移扫描：从 (136,112) 瞬移到各点找可动格。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import yaml

from src.emulator.keys import Key
from src.emulator.mgba_core import Emulator
from src.state.extractor import GameStateExtractor
from src.control.controller import Controller

cfg = yaml.safe_load(open(ROOT / "config" / "settings.yaml", encoding="utf-8"))
emu = Emulator(rom_path=ROOT / cfg["rom"]["path"])
ex = GameStateExtractor()
ctrl = Controller(emu, ex)
CK = ROOT / "data" / "checkpoints"
PX, PY = 0x02020650, 0x02020652
DIR_KEY = {"UP": Key.UP, "DOWN": Key.DOWN, "LEFT": Key.LEFT, "RIGHT": Key.RIGHT}


def can_move(d, frames=60):
    st0 = ex.extract(emu)
    p0 = (st0.player_x, st0.player_y)
    emu.press_hold(DIR_KEY[d])
    moved = False
    for _ in range(frames):
        emu.run_frames(1)
        st = ex.extract(emu)
        if (st.player_x, st.player_y) != p0:
            moved = True
            break
    emu.release()
    emu.run_frames(15)
    st = ex.extract(emu)
    return moved, (st.player_x, st.player_y)


# 未白镇区域候选点（20x14 = 320x224）
POINTS = [
    (136, 112),  # 原点（门口）
    (120, 160), (120, 176), (120, 192),  # 南
    (152, 160), (168, 160), (184, 160),  # 东南
    (88, 160), (72, 160), (56, 160),     # 西南
    (120, 96), (120, 80), (120, 64),     # 北
    (152, 96), (168, 96), (184, 96),     # 东北
    (56, 96), (72, 96), (88, 96),        # 西北
    (200, 128), (232, 128), (120, 48),   # 边缘
    (152, 112), (136, 128), (104, 128),  # 家附近
]

emu.load_state((CK / "outdoor_real.state").read_bytes())
emu.run_frames(30)
st = ex.extract(emu)
print(f"起点: ({st.player_x},{st.player_y}) bright={emu.screenshot().mean():.0f}")

for i, (tx, ty) in enumerate(POINTS):
    emu.write(PX, (tx).to_bytes(2, "little"))
    emu.write(PY, (ty).to_bytes(2, "little"))
    emu.run_frames(25)
    st = ex.extract(emu)
    b = float(emu.screenshot().mean())
    best = None
    for d in ["UP", "DOWN", "LEFT", "RIGHT"]:
        moved, end = can_move(d, 40)
        if moved:
            best = (d, end)
            break
    tag = ""
    if best:
        tag = f"🎉 可动！{best[0]}→{best[1]}"
    elif b > 130:
        tag = "户外高亮"
    print(f"  [{i}] ({tx},{ty}): pos=({st.player_x},{st.player_y}) bright={b:.0f} {tag}")
    if best:
        print(f"🎉🎉🎉 找到可动点！({tx},{ty})")
        Path(CK / "outdoor_real.state").write_bytes(emu.save_state())
        print("已保存 outdoor_real.state（未白镇可动）")
        sys.exit(0)

print("\n全部锁死")
