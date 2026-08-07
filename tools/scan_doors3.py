"""未白镇建筑门扫描 v3：校正位置 → DFS 收集墙方向 → 只测墙向按 A。"""
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
PX, PY = 0x02020650, 0x02020652


def rep(tag):
    st = ex.extract(emu)
    print(f"{tag}: pos=({st.player_x},{st.player_y}) "
          f"grid=({st.player_x//16},{st.player_y//16}) bright={emu.screenshot().mean():.0f}")


def reset():
    emu.load_state((CK / "outdoor_real.state").read_bytes())
    emu.run_frames(30)
    emu.write(MOVE_FLAG, b"\x00")
    emu.run_frames(10)
    # 校正位置到未白镇可动区 (136,128) 格(8,8)
    emu.write(PX, (136).to_bytes(2, "little"))
    emu.write(PY, (128).to_bytes(2, "little"))
    emu.run_frames(20)
    return ex.extract(emu)


reset()
rep("校正后")

# DFS 全图收集（验证 ≥80 格）
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

print(f"全图 {len(visited)} 格（墙方向记录 {sum(len(v) for v in walls.values())} 条）")
if len(visited) < 60:
    print("⚠ 全图太小，位置可能不对")
    sys.exit(1)

# 门扫描：每格面向墙方向按 A
print("\n=== 门扫描 ===")
SKIP = {((8, 7), "RIGHT")}  # 玩家家门（已知：未白镇(8,7) RIGHT→家(152,112)）
DOORS = []

# 重新导航扫描（边走边测墙方向）
reset()
rep("扫描起点")
explorer2 = DfsExplorer(emu, ex, ctrl, outdoor_bright=999, unlock_dialog=False)
visited2 = {explorer2._grid()}
stack2 = []
g2 = explorer2._grid()
facing2 = "UP"
for steps in range(3000):
    # 当前格测墙方向门
    for d in walls.get(g2, set()):
        if (g2, d) in SKIP:
            continue
        emu.press(DIR_KEY[d], 4)
        emu.run_frames(6)
        p_pre = ex.extract(emu)  # 确认没移动（墙）
        if (p_pre.player_x, p_pre.player_y) != (g2[0] * 16 + 8, g2[1] * 16 + 8) \
                and abs(p_pre.player_x - (g2[0] * 16 + 8)) > 2:
            continue  # 该方向可走（不是墙）
        emu.press(Key.A, 8)
        emu.run_frames(120)
        p1 = ex.extract(emu)
        b1 = float(emu.screenshot().mean())
        moved = abs(p1.player_x - (g2[0] * 16 + 8)) > 2 or \
                abs(p1.player_y - (g2[1] * 16 + 8)) > 2
        if moved:
            print(f"  🎉 门！格{g2} 面向{d}: →({p1.player_x},{p1.player_y}) bright={b1:.0f}")
            DOORS.append((g2, d, (p1.player_x, p1.player_y), b1))
            # 回退（若回不来则重置）
            emu.press(DIR_KEY[BACK[d]], 4)
            emu.run_frames(6)
            emu.press(DIR_KEY[BACK[d]], 20)
            emu.run_frames(80)
            emu.write(MOVE_FLAG, b"\x00")
            emu.run_frames(5)
            p2 = ex.extract(emu)
            if abs(p2.player_x // 16 - g2[0]) > 1 or abs(p2.player_y // 16 - g2[1]) > 1:
                reset()
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
    if len(visited2) % 25 == 0:
        print(f"  已测 {len(visited2)} 格，门: {DOORS}")

print(f"\n扫描完成：{len(visited2)} 格，发现门 {len(DOORS)} 个:")
for g, d, target, b in DOORS:
    print(f"  {g} 面向{d} → {target} bright={b:.0f}")
