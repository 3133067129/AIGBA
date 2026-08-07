"""冷启动 → 门口 → 出门方式变体（A/B/方向键）+ 每次出门后解锁检测。"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import yaml

from src.emulator.keys import Key
from src.emulator.mgba_core import Emulator
from src.brain.new_game import NewGameBootstrap
from src.state.extractor import GameStateExtractor
from src.control.controller import Controller
from src.control.dfs import DfsExplorer

cfg = yaml.safe_load(open(ROOT / "config" / "settings.yaml", encoding="utf-8"))
emu = Emulator(rom_path=ROOT / cfg["rom"]["path"])
ex = GameStateExtractor()
ctrl = Controller(emu, ex)
b = NewGameBootstrap(emu, ex, None)
CK = ROOT / "data" / "checkpoints"
F = 0x03000F2C
DIR_KEY = {"UP": Key.UP, "DOWN": Key.DOWN, "LEFT": Key.LEFT, "RIGHT": Key.RIGHT}


def real_move(d, frames=60):
    st0 = ex.extract(emu)
    p0 = (st0.player_x, st0.player_y)
    key = DIR_KEY[d]
    emu.press_hold(key)
    ok = False
    for _ in range(frames):
        emu.run_frames(1)
        st = ex.extract(emu)
        dx, dy = st.player_x - p0[0], st.player_y - p0[1]
        if d == "UP" and dy < -10 and abs(dx) < 8:
            ok = True
            break
        if d == "DOWN" and dy > 10 and abs(dx) < 8:
            ok = True
            break
        if d == "LEFT" and dx < -10 and abs(dy) < 8:
            ok = True
            break
        if d == "RIGHT" and dx > 10 and abs(dy) < 8:
            ok = True
            break
    emu.release()
    emu.run_frames(10)
    return ok


def nav_to_door():
    explorer = DfsExplorer(emu, ex, ctrl, outdoor_bright=999, unlock_dialog=False)
    target = (9, 7)
    visited = {explorer._grid()}
    stack = []
    g = explorer._grid()
    facing = "UP"
    BACK = {"UP": "DOWN", "DOWN": "UP", "LEFT": "RIGHT", "RIGHT": "LEFT"}
    for steps in range(300):
        if g == target:
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


# 1. 冷启动
print("=== 冷启动 ===")
assert b.boot_to_title(), "标题失败"
assert b.start_new_game(), "新游戏失败"
print("推进开场...")
t0 = time.time()
while time.time() - t0 < 600:
    if real_move("UP"):
        print(f"🎉 真可动 ({time.time()-t0:.0f}s)")
        break
    b.advance_with_watchdog(120)
else:
    print("✗ 未可控")
    sys.exit(1)

nav_to_door()
print("门口 (152,112)")

# 2. 出门方式变体
VARIANTS = [
    ("A键", [(Key.A, 10)]),
    ("B键", [(Key.B, 10)]),
    ("方向键RIGHT", [(Key.RIGHT, 30)]),
    ("A+B", [(Key.A, 10), (Key.B, 10)]),
    ("A长按30", [(Key.A, 30)]),
    ("方向键DOWN", [(Key.DOWN, 30)]),
]
for name, seq in VARIANTS:
    # 回到门口（导航）
    if not nav_to_door():
        print(f"  ⚠ 导航失败 {name}")
        continue
    st = ex.extract(emu)
    p0 = (st.player_x, st.player_y)
    for k, f in seq:
        emu.press(k, f)
        emu.run_frames(15)
    emu.run_frames(300)
    st = ex.extract(emu)
    b1 = float(emu.screenshot().mean())
    emu.write(F, b"\x00")
    emu.run_frames(10)
    ok = real_move("UP")
    print(f"  {name}: →({st.player_x},{st.player_y}) bright={b1:.0f} 出门后UP={ok}")
    if ok:
        print(f"🎉🎉🎉 {name} 出门解锁！！")
        Path(CK / "outdoor_real.state").write_bytes(emu.save_state())
        sys.exit(0)
    if b1 > 130 and abs(st.player_x - p0[0]) > 8:
        print(f"    （出门到户外了但锁）")

print("全部变体未解锁")
