"""未白镇全图建筑门扫描：每格 4 方向按 A，找所有可进建筑（排除玩家家门）。"""
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
BACK = {"UP": "DOWN", "DOWN": "UP", "LEFT": "RIGHT", "RIGHT": "LEFT"}
MOVE_FLAG = 0x03000F2C

emu.load_state((CK / "outdoor_real.state").read_bytes())
emu.run_frames(30)
emu.write(MOVE_FLAG, b"\x00")
emu.run_frames(10)
st = ex.extract(emu)
print(f"起点: ({st.player_x},{st.player_y}) grid=({st.player_x//16},{st.player_y//16})")

# DFS 全图收集
explorer = DfsExplorer(emu, ex, ctrl, outdoor_bright=999, unlock_dialog=False)
visited = {explorer._grid()}
stack = []
g = explorer._grid()
facing = "UP"
walls = {}
for steps in range(3000):
    right = {"UP": "RIGHT", "RIGHT": "DOWN", "DOWN": "LEFT", "LEFT": "UP"}[facing]
    left = {"UP": "LEFT", "LEFT": "DOWN", "DOWN": "RIGHT", "RIGHT": "UP"}[facing]
    moved = False
    for d in [right, facing, left, BACK[facing]]:
        ng = explorer.move_one(d)
        if ng is None:
            walls.setdefault(g, set()).add(d)
            continue
        if ng in visited:
            explorer.move_one(BACK[d])
            walls.setdefault(g, set()).add(d)
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
        break
    prev, came = stack.pop()
    explorer.move_one(BACK[came])
    g = prev

print(f"全图 {len(visited)} 格")

# 门扫描：每格面向墙方向按 A
print("\n=== 门扫描 ===")
DOORS = []
SKIP = {((8, 7), "RIGHT")}  # 玩家家门（已知）
for g0 in sorted(visited):
    for d in walls.get(g0, set()):
        if (g0, d) in SKIP:
            continue
        # 导航到 g0（重走 DFS 太慢——用 move_one 逐步导航）
        # 简化：用当前位置 + 方向
        cur = (ex.extract(emu).player_x // 16, ex.extract(emu).player_y // 16)
        if cur != g0:
            continue  # 只测当前位置（后续轮次移动后再测）
    break

# 直接法：DFS 过程中每到一格测 4 方向 A（检测"进门"=坐标大变或转场）
print("边走边测（每格 4 方向按 A）...")
emu.load_state((CK / "outdoor_real.state").read_bytes())
emu.run_frames(30)
emu.write(MOVE_FLAG, b"\x00")
emu.run_frames(10)
explorer2 = DfsExplorer(emu, ex, ctrl, outdoor_bright=999, unlock_dialog=False)
visited2 = {explorer2._grid()}
stack2 = []
g2 = explorer2._grid()
facing2 = "UP"
found_doors = []
for steps in range(3000):
    # 当前格测门（4 方向 A）
    p0 = ex.extract(emu)
    for d in ["UP", "DOWN", "LEFT", "RIGHT"]:
        if (g2, d) == ((8, 7), "RIGHT"):
            continue  # 玩家家门跳过
        p_a = ex.extract(emu)
        emu.press(DIR_KEY[d], 4)
        emu.run_frames(6)
        emu.press(Key.A, 8)
        emu.run_frames(100)
        p1 = ex.extract(emu)
        b1 = float(emu.screenshot().mean())
        moved = (p1.player_x, p1.player_y) != (p_a.player_x, p_a.player_y)
        if moved:
            print(f"  🎉 门！格{g2} 面向{d}: →({p1.player_x},{p1.player_y}) bright={b1:.0f}")
            found_doors.append((g2, d, (p1.player_x, p1.player_y)))
            # 走回（如果还在原地图）
            emu.press(BACK[d], 4)
            emu.run_frames(6)
            emu.press(BACK[d], 10)
            emu.run_frames(80)
            emu.write(MOVE_FLAG, b"\x00")
            emu.run_frames(5)
            # 若回不来就重载
            p2 = ex.extract(emu)
            if (p2.player_x // 16, p2.player_y // 16) != g2:
                emu.load_state((CK / "outdoor_real.state").read_bytes())
                emu.run_frames(30)
                emu.write(MOVE_FLAG, b"\x00")
                emu.run_frames(10)
                break
    # DFS 前进
    right = {"UP": "RIGHT", "RIGHT": "DOWN", "DOWN": "LEFT", "LEFT": "UP"}[facing2]
    left = {"UP": "LEFT", "LEFT": "DOWN", "DOWN": "RIGHT", "RIGHT": "UP"}[facing2]
    moved = False
    for d in [right, facing2, left, BACK[facing2]]:
        ng = explorer2.move_one(d)
        if ng is None:
            continue
        if ng in visited2:
            explorer2.move_one(BACK[d])
            continue
        facing2 = d
        visited2.add(ng)
        stack2.append((g2, d))
        g2 = ng
        moved = True
        break
    if moved:
        continue
    if not stack2:
        break
    prev, came = stack2.pop()
    explorer2.move_one(BACK[came])
    g2 = prev
    if len(visited2) % 30 == 0:
        print(f"  已测 {len(visited2)} 格，发现 {len(found_doors)} 个门")

print(f"\n扫描完成：全图 {len(visited2)} 格，发现门: {found_doors}")
