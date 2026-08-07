"""瞬移扫描家地图东侧/南侧（x=96+，y=112+）找可动户外格。"""
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

cfg = yaml.safe_load(open(ROOT / "config" / "settings.yaml", encoding="utf-8"))
emu = Emulator(rom_path=ROOT / cfg["rom"]["path"])
ex = GameStateExtractor()
DIR_KEY = {"UP": Key.UP, "DOWN": Key.DOWN, "LEFT": Key.LEFT, "RIGHT": Key.RIGHT}
PX, PY = 0x02020650, 0x02020652
CK = ROOT / "data" / "checkpoints"

# 从可动态开始（1F 入口区，家地图）
emu.load_state((CK / "outside_room.state").read_bytes())
emu.run_frames(30)


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


# 家地图东/南侧扫描（x 96-240，y 112-224）
print("家地图东/南侧瞬移扫描:")
found = False
for ty in [112, 128, 144, 160, 176, 192, 208]:
    for tx in [96, 112, 128, 144, 160, 176, 192, 208, 224, 240]:
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
        if best:
            print(f"  🎉 ({tx},{ty}): bright={b:.0f} 可动！{best[0]} → {best[1]}")
            Path(CK / "outdoor_real.state").write_bytes(emu.save_state())
            print(f"  已保存 outdoor_real.state（瞬移 ({tx},{ty}) 可动）")
            found = True
            break
        elif b > 130:
            print(f"  ★ ({tx},{ty}): bright={b:.0f}（高亮但锁）")
    if found:
        break
if not found:
    print("未找到可动格")
