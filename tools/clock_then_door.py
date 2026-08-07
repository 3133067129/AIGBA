"""完整剧情流程：冷启动 → 可控 → 调钟 → (152,112) 出门 → 未白镇解锁测试。

调钟（guide_clock 实证 + qwen 界面读出）：
  面向钟按 A → 界面开（"AM/確定"）→ A（"这是正确的时间吗？是/否"）
  → UP+A（选"是"）→ 界面关 → 调钟完成
"""
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


def nav_to(target):
    explorer = DfsExplorer(emu, ex, ctrl, outdoor_bright=999, unlock_dialog=False)
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

st = ex.extract(emu)
print(f"可控点: ({st.player_x},{st.player_y})")

# 2. 导航到电子钟 (120,80) 附近
print("导航到电子钟 (120,80)...")
ok = nav_to((7, 5))
print(f"到钟区: {ok}")
st = ex.extract(emu)
print(f"位置: ({st.player_x},{st.player_y})")

# 3. 面向钟按 A → 界面 → 调钟
print("面向 UP 按 A（钟在墙上？）...")
emu.press(Key.UP, 4)
emu.run_frames(10)
emu.press(Key.A, 10)
emu.run_frames(150)
b1 = float(emu.screenshot().mean())
print(f"  按A后 bright={b1:.0f}（150+ = 调钟界面开）")

if b1 > 140:
    print("界面开！调钟确认（A → UP+A）...")
    emu.press(Key.A, 8)
    emu.run_frames(120)
    emu.press(Key.UP, 4)
    emu.run_frames(10)
    emu.press(Key.A, 8)
    emu.run_frames(250)
    b2 = float(emu.screenshot().mean())
    print(f"  调钟后 bright={b2:.0f}")
    st = ex.extract(emu)
    print(f"  位置: ({st.player_x},{st.player_y})")
else:
    print("  界面没开——试 4 方向找钟")
    for d in ["UP", "DOWN", "LEFT", "RIGHT"]:
        emu.press(DIR_KEY[d], 4)
        emu.run_frames(10)
        emu.press(Key.A, 10)
        emu.run_frames(120)
        b3 = float(emu.screenshot().mean())
        if b3 > 140:
            print(f"  面向{d} 打开界面！调钟...")
            emu.press(Key.A, 8)
            emu.run_frames(120)
            emu.press(Key.UP, 4)
            emu.run_frames(10)
            emu.press(Key.A, 8)
            emu.run_frames(250)
            break
        emu.press(DIR_KEY[{"UP": "DOWN", "DOWN": "UP",
                           "LEFT": "RIGHT", "RIGHT": "LEFT"}[d]], 4)
        emu.run_frames(10)

# 4. 出门
print("导航到门口 (152,112)...")
ok = nav_to((9, 7))
print(f"到门口: {ok}")
st = ex.extract(emu)
print(f"门口: ({st.player_x},{st.player_y}) bright={emu.screenshot().mean():.0f}")
print("面向 RIGHT 出门...")
emu.press(Key.RIGHT, 4)
emu.run_frames(10)
emu.press(Key.RIGHT, 30)
emu.run_frames(300)
st = ex.extract(emu)
print(f"出门后: ({st.player_x},{st.player_y}) bright={emu.screenshot().mean():.0f}")

# 5. 解锁测试
emu.write(F, b"\x00")
emu.run_frames(10)
ok = real_move("UP")
print(f"未白镇 UP: {ok}")
if not ok:
    ok2 = real_move("DOWN")
    print(f"未白镇 DOWN: {ok2}")
    if not ok2:
        ok3 = real_move("LEFT")
        print(f"未白镇 LEFT: {ok3}")
        if not ok3:
            ok4 = real_move("RIGHT")
            print(f"未白镇 RIGHT: {ok4}")
if ok or ok2 or ok3 or ok4:
    print("🎉🎉🎉 调钟后出门解锁成功！！")
    Path(CK / "outdoor_real.state").write_bytes(emu.save_state())
    print("已保存 outdoor_real.state")
else:
    print("✗ 仍锁")
