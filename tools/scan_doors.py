"""未白镇建筑门扫描：DFS 走全图，每到一格面向墙方向按 A 检测进门。"""
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
emu.write(MOVE_FLAG, b"\x00")  # 保险：确保可动
emu.run_frames(10)


def rep(tag):
    st = ex.extract(emu)
    print(f"{tag}: pos=({st.player_x},{st.player_y}) "
          f"grid=({st.player_x//16},{st.player_y//16}) bright={emu.screenshot().mean():.0f}")


# 收集全图格子 + 墙方向
explorer = DfsExplorer(emu, ex, ctrl, outdoor_bright=999, unlock_dialog=False)
visited = {explorer._grid()}
stack = []
g = explorer._grid()
facing = "UP"
walls = {}  # grid -> set(墙方向)
path = []
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
            walls.setdefault(g, set()).add(d)  # 已访问也视为"有墙/有门"
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
# 返回起点（可选）

# 扫描：每格面向墙方向按 A
print("\n=== 门扫描 ===")
found = None
grids = sorted(visited)
for idx, g0 in enumerate(grids):
    # 导航到 g0：用 DFS 路径（简化：只处理少量候选——先扫"墙方向多的格"）
    pass

# 简化实现：直接从当前位置逐步走 + 每步测墙方向
# 先回到起点格
start = (ex.extract(emu).player_x // 16, ex.extract(emu).player_y // 16)
print(f"起点格: {start}")

# 走遍全图测门（每格 4 方向按 A——只测墙方向记录）
emu.load_state((CK / "outdoor_real.state").read_bytes())
emu.run_frames(30)
emu.write(MOVE_FLAG, b"\x00")
emu.run_frames(10)
explorer2 = DfsExplorer(emu, ex, ctrl, outdoor_bright=999, unlock_dialog=False)
visited2 = {explorer2._grid()}
stack2 = []
g2 = explorer2._grid()
facing2 = "UP"
DOOR_HINT = []
for steps in range(3000):
    # 在当前格测墙方向的门
    right = {"UP": "RIGHT", "RIGHT": "DOWN", "DOWN": "LEFT", "LEFT": "UP"}[facing2]
    left = {"UP": "LEFT", "LEFT": "DOWN", "DOWN": "RIGHT", "RIGHT": "UP"}[facing2]
    for d in [right, facing2, left, BACK[facing2]]:
        # 先测：面向 d 按 A（如果该方向是墙）
        probe_pos = ex.extract(emu)
        if d in walls.get(g2, set()) or d not in walls.get(g2, set()):
            # 测 A：按 A 前先面向 d
            p0 = ex.extract(emu)
            emu.press(DIR_KEY[d], 4)
            emu.run_frames(6)
            emu.press(Key.A, 8)
            emu.run_frames(120)
            p1 = ex.extract(emu)
            b1 = float(emu.screenshot().mean())
            if (p1.player_x, p1.player_y) != (p0.player_x, p0.player_y) or b1 < 100:
                print(f"  🎉 门/转场！格{g2} 面向{d} 按A: →({p1.player_x},{p1.player_y}) "
                      f"bright={b1:.0f}")
                DOOR_HINT.append((g2, d, (p1.player_x, p1.player_y), b1))
                Path(CK / "outdoor_real.state").write_bytes(emu.save_state())
                found = (g2, d)
                break
    if found:
        break
    # DFS 前进
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
    if len(visited2) % 20 == 0:
        print(f"  已测 {len(visited2)} 格...")

print(f"\n扫描完成。门线索: {DOOR_HINT}")
if found:
    print(f"找到门：格{found[0]} 面向{found[1]}")
else:
    print("未找到门")
