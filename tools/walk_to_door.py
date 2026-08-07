"""从 2F (152,96) 正常走路到门洞格 (120,128)，测四方向可动性。"""
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


emu.load_state((CK / "after_intro_fixed.state").read_bytes())
emu.run_frames(30)
rep("起点(2F)")

# DFS 导航到 (7,8) = (120,128) 门洞格
explorer = DfsExplorer(emu, ex, ctrl, outdoor_bright=130, unlock_dialog=False)
target = (7, 8)
visited = {explorer._grid()}
stack = []
g = explorer._grid()
facing = "UP"
found = False
BACK = {"UP": "DOWN", "DOWN": "UP", "LEFT": "RIGHT", "RIGHT": "LEFT"}
for steps in range(200):
    if g == target:
        found = True
        break
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
        break
    prev, came = stack.pop()
    explorer.move_one(BACK[came])
    g = prev

print(f"到达目标 (7,8): {found} visited={len(visited)}")
rep("门洞格")

# 四方向移动测试（60 帧 + 补走余量 120）
for d in ["UP", "DOWN", "LEFT", "RIGHT"]:
    st0 = ex.extract(emu)
    p0 = (st0.player_x, st0.player_y)
    emu.press_hold(DIR_KEY[d])
    moved = False
    for _ in range(120):
        emu.run_frames(1)
        st = ex.extract(emu)
        if (st.player_x, st.player_y) != p0:
            moved = True
            break
    emu.release()
    emu.run_frames(20)
    st = ex.extract(emu)
    b = float(emu.screenshot().mean())
    tag = "🎉" if moved else ""
    print(f"  {d}: moved={moved} →({st.player_x},{st.player_y}) bright={b:.0f} {tag}")
    if moved and d == "DOWN":
        print("🎉🎉 门洞格可走！继续探索...")
        # 继续 DOWN 深入
        for step in range(10):
            st0 = ex.extract(emu)
            p0 = (st0.player_x, st0.player_y)
            emu.press_hold(DIR_KEY[d])
            moved2 = False
            for _ in range(60):
                emu.run_frames(1)
                st = ex.extract(emu)
                if (st.player_x, st.player_y) != p0:
                    moved2 = True
                    break
            emu.release()
            emu.run_frames(15)
            st = ex.extract(emu)
            b2 = float(emu.screenshot().mean())
            print(f"    步{step+1}: moved={moved2} →({st.player_x},{st.player_y}) bright={b2:.0f}")
            if not moved2 or b2 > 130:
                if b2 > 130:
                    print(f"🎉🎉🎉 户外！！bright={b2:.0f}")
                break
        break
