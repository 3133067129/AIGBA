"""走路到 1F (120,208)（正常状态）→ 完整 4 方向 + DFS 探索。"""
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


def stable_text(frames=30):
    tr = emu.screenshot()[96:158, 8:232]
    h1 = hashlib.sha256(tr.tobytes()).hexdigest()
    for _ in range(frames):
        emu.run_frames(5)
        if hashlib.sha256(emu.screenshot()[96:158, 8:232].tobytes()).hexdigest() == h1:
            return True
    return False


def push_dialog(max_pages=8):
    pages = 0
    for _ in range(max_pages):
        if not ctrl.dialog_open():
            break
        if not stable_text():
            continue
        h = hashlib.sha256(emu.screenshot().tobytes()).hexdigest()[:6]
        emu.press(Key.A, 8)
        emu.run_frames(80)
        h2 = hashlib.sha256(emu.screenshot().tobytes()).hexdigest()[:6]
        pages += 1
        if h2 == h:
            break
    return pages


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


# 走到 1F (120,208)：2F → (120,128) → DOWN+A → 对话推进 → DOWN×4
emu.load_state((CK / "after_intro_fixed.state").read_bytes())
emu.run_frames(30)
nav_to((7, 8))
emu.press(Key.DOWN, 4)
emu.run_frames(10)
emu.press(Key.A, 10)
emu.run_frames(150)
push_dialog(8)
# DOWN 一路走
for _ in range(6):
    st0 = ex.extract(emu)
    p0 = (st0.player_x, st0.player_y)
    emu.press_hold(Key.DOWN)
    moved = False
    for _ in range(60):
        emu.run_frames(1)
        st = ex.extract(emu)
        if (st.player_x, st.player_y) != p0:
            moved = True
            break
    emu.release()
    emu.run_frames(15)
    if not moved:
        break
rep("1F (120,208)")

# 4 方向测试（正常状态）
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
    b = float(emu.screenshot().mean())
    print(f"  {d}: moved={moved} →({st.player_x},{st.player_y}) bright={b:.0f}")
    if moved:
        # 走回来
        emu.press_hold({"UP": Key.DOWN, "DOWN": Key.UP,
                        "LEFT": Key.RIGHT, "RIGHT": Key.LEFT}[d])
        for _ in range(90):
            emu.run_frames(1)
            st = ex.extract(emu)
            if (st.player_x, st.player_y) == p0:
                break
        emu.release()
        emu.run_frames(20)

# 完整 DFS（正常状态）
print("\nDFS 全图探索（正常状态）:")
explorer = DfsExplorer(emu, ex, ctrl, outdoor_bright=130, unlock_dialog=False,
                       on_step=lambda t: print(f"  {t}"))
result = explorer.run(max_steps=2000)
print("RESULT:", result)
if result.get("outdoor"):
    st = ex.extract(emu)
    print(f"🎉 户外！({st.player_x},{st.player_y}) bright={emu.screenshot().mean():.0f}")
    Path(CK / "outdoor_real.state").write_bytes(emu.save_state())
    print("已保存 outdoor_real.state")
