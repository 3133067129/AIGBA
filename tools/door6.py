"""门洞中 4 方向穷举 + 进门洞方式变体（面向 UP 先转好再按 A）。"""
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


def reset_door():
    emu.load_state((CK / "after_intro_fixed.state").read_bytes())
    emu.run_frames(30)
    nav_to((7, 8))
    emu.press(Key.UP, 4)
    emu.run_frames(10)
    emu.press(Key.UP, 20)
    emu.run_frames(150)
    b = float(emu.screenshot().mean())
    return b > 100  # 门洞态（bright ~120）


print("=== 门洞中 4 方向 ===")
for d in ["LEFT", "RIGHT", "UP", "DOWN"]:
    reset_door()
    emu.press(DIR_KEY[d], 4)
    emu.run_frames(10)
    emu.press(DIR_KEY[d], 30)
    emu.run_frames(250)
    st = ex.extract(emu)
    b = float(emu.screenshot().mean())
    print(f"  门洞中{d}: →({st.player_x},{st.player_y}) bright={b:.0f}")
    if b > 130:
        print(f"🎉🎉🎉 出门！！{d}")
        Path(CK / "outdoor_real.state").write_bytes(emu.save_state())
        sys.exit(0)

print("\n=== 进门洞方式变体：面向 UP 转好后按 A ===")
for name, seq in [
    ("UP转好+A10", [(Key.UP, 10), (Key.A, 10)]),
    ("UP转好+A30", [(Key.UP, 10), (Key.A, 30)]),
    ("UP转好+A+B", [(Key.UP, 10), (Key.A, 10), (Key.B, 10)]),
    ("UP转好+START", [(Key.UP, 10), (Key.START, 10)]),
]:
    emu.load_state((CK / "after_intro_fixed.state").read_bytes())
    emu.run_frames(30)
    nav_to((7, 8))
    for k, f in seq:
        emu.press(k, f)
        emu.run_frames(15)
    emu.run_frames(300)
    st = ex.extract(emu)
    b = float(emu.screenshot().mean())
    print(f"  {name}: →({st.player_x},{st.player_y}) bright={b:.0f}")
    if b > 130:
        print(f"🎉🎉🎉 出门！！{name}")
        Path(CK / "outdoor_real.state").write_bytes(emu.save_state())
        sys.exit(0)

print("\n完成")
