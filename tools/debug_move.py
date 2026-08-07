"""最小复现：恢复→写0→move_one vs press_hold 对比。"""
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
from src.control.dfs import DfsExplorer

cfg = yaml.safe_load(open(ROOT / "config" / "settings.yaml", encoding="utf-8"))
emu = Emulator(rom_path=ROOT / cfg["rom"]["path"])
ex = GameStateExtractor()
ctrl = Controller(emu, ex)
F = 0x03000F2C
DIR_KEY = {"UP": Key.UP, "DOWN": Key.DOWN, "LEFT": Key.LEFT, "RIGHT": Key.RIGHT}

emu.load_state((ROOT / "data/checkpoints/outdoor_real.state").read_bytes())
emu.run_frames(30)
emu.write(F, b"\x00")
emu.run_frames(10)
st = ex.extract(emu)
print(f"起点: ({st.player_x},{st.player_y}) bright={emu.screenshot().mean():.0f}")

# 1. press_hold 直接测
for d in ["UP", "DOWN", "LEFT", "RIGHT"]:
    st0 = ex.extract(emu)
    p0 = (st0.player_x, st0.player_y)
    emu.press_hold(DIR_KEY[d])
    moved = False
    for _ in range(60):
        emu.run_frames(1)
        st = ex.extract(emu)
        if (st.player_x, st.player_y) != p0:
            moved = True
            break
    emu.release()
    emu.run_frames(10)
    st = ex.extract(emu)
    print(f"  press_hold {d}: moved={moved} →({st.player_x},{st.player_y})")
    if moved:
        # 走回
        emu.press_hold({"UP": Key.DOWN, "DOWN": Key.UP,
                        "LEFT": Key.RIGHT, "RIGHT": Key.LEFT}[d])
        for _ in range(60):
            emu.run_frames(1)
            st = ex.extract(emu)
            if (st.player_x, st.player_y) == p0:
                break
        emu.release()
        emu.run_frames(10)

# 2. move_one 测（同状态）
st = ex.extract(emu)
print(f"\nmove_one 测试，当前: ({st.player_x},{st.player_y})")
explorer = DfsExplorer(emu, ex, ctrl, outdoor_bright=999, unlock_dialog=False,
                       door_drop=50)
for d in ["UP", "DOWN", "LEFT", "RIGHT"]:
    ng = explorer.move_one(d)
    b = float(emu.screenshot().mean())
    print(f"  move_one {d}: →{ng} bright={b:.0f}")
    if ng is not None:
        explorer.move_one({"UP": "DOWN", "DOWN": "UP",
                           "LEFT": "RIGHT", "RIGHT": "LEFT"}[d])
