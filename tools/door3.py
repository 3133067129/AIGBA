"""门洞完整序列：面向 UP 按 A（进门洞）→ 再按 A/方向键（出门）。

实验 A：2F → (120,128) → 面向 UP 按 A → 检测 → 面向 UP 按 A/方向键 → 检测
实验 B：town.state（(120,112) 门洞态）→ 面向 UP 按 A 长按 → 检测
"""
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
DIR_KEY = {"UP": Key.UP, "DOWN": Key.DOWN, "LEFT": Key.LEFT, "RIGHT": Key.RIGHT}


def rep(tag):
    st = ex.extract(emu)
    print(f"{tag}: pos=({st.player_x},{st.player_y}) "
          f"grid=({st.player_x//16},{st.player_y//16}) bright={emu.screenshot().mean():.0f}")


def check_exit(tag):
    """检测是否出门，返回 True 则保存并退出。"""
    st = ex.extract(emu)
    b = float(emu.screenshot().mean())
    print(f"  [{tag}] ({st.player_x},{st.player_y}) bright={b:.0f} dialog={ctrl.dialog_open()}")
    if b > 130:
        print(f"🎉🎉🎉 出门！！{tag}")
        Path(CK / "outdoor_real.state").write_bytes(emu.save_state())
        print("已保存 outdoor_real.state")
        sys.exit(0)


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


# ===== 实验 A：2F → (120,128) 门洞格 → 面向 UP 按 A =====
print("=== 实验 A：门洞格面向 UP 按 A ===")
emu.load_state((CK / "after_intro_fixed.state").read_bytes())
emu.run_frames(30)
nav_to((7, 8))
rep("门洞格(120,128)")
check_exit("到达")

# 面向 UP 按 A（进门洞）
emu.press(Key.UP, 4)
emu.run_frames(10)
emu.press(Key.A, 10)
emu.run_frames(150)
rep("UP+A后")
check_exit("UP+A")

# 面向 UP 按方向键（出门？）
emu.press(Key.UP, 4)
emu.run_frames(10)
emu.press(Key.UP, 20)
emu.run_frames(150)
rep("再UP后")
check_exit("再UP")

# 面向 UP 按 A 长按
emu.press(Key.UP, 4)
emu.run_frames(10)
emu.press(Key.A, 40)
emu.run_frames(250)
rep("UP+A长按")
check_exit("UP+A长按")

# ===== 实验 B：town.state 门洞态 =====
print("\n=== 实验 B：town.state (120,112) 面向 UP 按 A 长按 ===")
emu.load_state((CK / "town.state").read_bytes())
emu.run_frames(30)
rep("town")
for d in ["UP", "DOWN"]:
    emu.press(DIR_KEY[d], 4)
    emu.run_frames(10)
    emu.press(Key.A, 40)
    emu.run_frames(300)
    rep(f"面向{d}+A长按")
    check_exit(f"town-{d}+A")

print("\n未出门")
