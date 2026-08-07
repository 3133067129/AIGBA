"""从 2F 状态走到门洞格 (120,128)（正常态）→ 完整按键测试 → 瞬移 (120,144)。"""
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
CK = ROOT / "data" / "checkpoints"
PX, PY = 0x02020650, 0x02020652
DIR_KEY = {"UP": Key.UP, "DOWN": Key.DOWN, "LEFT": Key.LEFT, "RIGHT": Key.RIGHT}


def rep(tag):
    st = ex.extract(emu)
    print(f"{tag}: pos=({st.player_x},{st.player_y}) "
          f"grid=({st.player_x//16},{st.player_y//16}) bright={emu.screenshot().mean():.0f}")


def check_exit(tag):
    st = ex.extract(emu)
    b = float(emu.screenshot().mean())
    print(f"  [{tag}] ({st.player_x},{st.player_y}) bright={b:.0f} dialog={ctrl.dialog_open()}")
    if b > 130:
        print(f"🎉🎉🎉 出门！！[{tag}]")
        Path(CK / "outdoor_real.state").write_bytes(emu.save_state())
        print("已保存 outdoor_real.state")
        sys.exit(0)
    return st, b


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
rep("起点(2F)")
nav_to((7, 8))
rep("门洞格(正常态)")

# 1. 面向 DOWN 按 A
emu.press(Key.DOWN, 4)
emu.run_frames(10)
emu.press(Key.A, 30)
emu.run_frames(250)
check_exit("DOWN+A")

# 2. 面向 DOWN 按方向键（下楼 warp？）
emu.press(Key.DOWN, 4)
emu.run_frames(10)
emu.press(Key.DOWN, 30)
emu.run_frames(250)
check_exit("DOWN方向键")

# 3. 面向 UP 按 A
emu.press(Key.UP, 4)
emu.run_frames(10)
emu.press(Key.A, 30)
emu.run_frames(250)
check_exit("UP+A")

# 4. 面向 UP 按方向键（进门洞）→ 再按 A
emu.press(Key.UP, 4)
emu.run_frames(10)
emu.press(Key.UP, 20)
emu.run_frames(150)
check_exit("UP进门洞")
emu.press(Key.A, 30)
emu.run_frames(250)
check_exit("门洞中A")
emu.press(Key.UP, 30)
emu.run_frames(250)
check_exit("门洞中UP")

# 5. 瞬移 (120,144)（2F 可走格）
emu.load_state((CK / "after_intro_fixed.state").read_bytes())
emu.run_frames(30)
emu.write(PX, (120).to_bytes(2, "little"))
emu.write(PY, (144).to_bytes(2, "little"))
emu.run_frames(30)
rep("瞬移(120,144)")
for d in ["UP", "DOWN", "LEFT", "RIGHT"]:
    st0 = ex.extract(emu)
    p0 = (st0.player_x, st0.player_y)
    emu.press_hold(DIR_KEY[d])
    moved = False
    for _ in range(90):
        emu.run_frames(1)
        st = ex.extract(emu)
        if (st.player_x, st.player_y) != p0:
            moved = True
            break
    emu.release()
    emu.run_frames(20)
    st = ex.extract(emu)
    print(f"  {d}: moved={moved} →({st.player_x},{st.player_y}) "
          f"bright={emu.screenshot().mean():.0f}")
    if moved:
        print("🎉 可动！")
        sys.exit(0)

print("\n全部失败")
