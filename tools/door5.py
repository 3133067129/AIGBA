"""门洞连贯：走路态 (120,128) → 面向 UP 进门洞（bright 120）→ 面向 DOWN/A 穿过门。"""
from __future__ import annotations

import hashlib
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
CK = ROOT / "data" / "checkpoints"
DIR_KEY = {"UP": Key.UP, "DOWN": Key.DOWN, "LEFT": Key.LEFT, "RIGHT": Key.RIGHT}


def rep(tag):
    st = ex.extract(emu)
    print(f"{tag}: pos=({st.player_x},{st.player_y}) "
          f"grid=({st.player_x//16},{st.player_y//16}) bright={emu.screenshot().mean():.0f}")


def nav_to(grid_target):
    explorer = DfsExplorer(emu, ex, ctrl, outdoor_bright=130, unlock_dialog=False)
    visited = {explorer._grid()}
    stack = []
    g = explorer._grid()
    facing = "UP"
    BACK = {"UP": "DOWN", "DOWN": "UP", "LEFT": "RIGHT", "RIGHT": "LEFT"}
    for _ in range(200):
        if g == grid_target:
            return True
        right = {"UP": "RIGHT", "RIGHT": "DOWN", "DOWN": "LEFT", "LEFT": "UP"}[facing]
        left = {"UP": "LEFT", "LEFT": "DOWN", "DOWN": "RIGHT", "RIGHT": "UP"}[facing]
        moved = False
        for d in [right, facing, left, BACK[facing]]:
            ng = explorer.move_one(d)
            if ng is None:
                continue
            if ng in visited:
                explorer.move_one(BACK[d])
                continue
            facing = d
            visited.add(ng)
            stack.append((g, d))
            g = ng
            moved = True
            break
        if moved:
            continue
        if not stack:
            return False
        prev, came = stack.pop()
        explorer.move_one(BACK[came])
        g = prev
    return False


emu.load_state((CK / "after_intro_fixed.state").read_bytes())
emu.run_frames(30)
nav_to((7, 8))
rep("门洞格(走路态)")

# 1. 面向 UP 按方向键 → 进门洞（bright 120）
emu.press(Key.UP, 4)
emu.run_frames(10)
emu.press(Key.UP, 20)
emu.run_frames(150)
rep("进门洞")
print(f"  dialog: {ctrl.dialog_open()}")

# 2. 门洞中面向 DOWN 按方向键（穿过门？）
for step in range(4):
    emu.press(Key.DOWN, 4)
    emu.run_frames(10)
    emu.press(Key.DOWN, 30)
    emu.run_frames(200)
    st = ex.extract(emu)
    b = float(emu.screenshot().mean())
    print(f"  门洞中DOWN×{step+1}: →({st.player_x},{st.player_y}) bright={b:.0f}")
    if b > 130:
        print(f"🎉🎉🎉 出门！！bright={b:.0f}")
        Path(CK / "outdoor_real.state").write_bytes(emu.save_state())
        print("已保存 outdoor_real.state")
        sys.exit(0)

# 3. 门洞中 A 长按
emu.press(Key.A, 40)
emu.run_frames(300)
st = ex.extract(emu)
b = float(emu.screenshot().mean())
print(f"  门洞中A长按: →({st.player_x},{st.player_y}) bright={b:.0f}")
if b > 130:
    print(f"🎉🎉🎉 出门！！")
    Path(CK / "outdoor_real.state").write_bytes(emu.save_state())
    sys.exit(0)

# 4. 门洞中 B
emu.press(Key.B, 40)
emu.run_frames(300)
st = ex.extract(emu)
b = float(emu.screenshot().mean())
print(f"  门洞中B长按: →({st.player_x},{st.player_y}) bright={b:.0f}")
if b > 130:
    print(f"🎉🎉🎉 出门！！")
    Path(CK / "outdoor_real.state").write_bytes(emu.save_state())
    sys.exit(0)

# 5. 重置：重新进门洞后 面向 DOWN 按 A
emu.load_state((CK / "after_intro_fixed.state").read_bytes())
emu.run_frames(30)
nav_to((7, 8))
emu.press(Key.UP, 4)
emu.run_frames(10)
emu.press(Key.UP, 20)
emu.run_frames(150)
rep("再进门洞")
emu.press(Key.DOWN, 4)
emu.run_frames(10)
emu.press(Key.A, 30)
emu.run_frames(300)
st = ex.extract(emu)
b = float(emu.screenshot().mean())
print(f"  门洞中DOWN+A: →({st.player_x},{st.player_y}) bright={b:.0f}")
if b > 130:
    print(f"🎉🎉🎉 出门！！")
    Path(CK / "outdoor_real.state").write_bytes(emu.save_state())
    sys.exit(0)

print("\n完成")
