"""出门时序窗口扫描：冷启动 → 可动 → 出门 → 逐帧测 UP 可动 + 记录 MOVE_FLAG。

假设（summary：曾一次出门后成功移动 90 格，不可复现）：未白镇锁可能有
「出门后 N 帧内的时序窗口」。之前实验都是出门后等 300 帧再测，窗口可能被错过。

方法：出门后连续 3000 帧，每帧：
  1. 记录 MOVE_FLAG (0x03000F2C)
  2. 按 UP 1 帧 → 查坐标 → 松开
  3. 若坐标变化 → 窗口命中！立即连续移动测试 + 保存 savestate
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

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


def real_move_any():
    for d in ["UP", "DOWN", "LEFT", "RIGHT"]:
        if real_move(d):
            return True
    return False


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


# 1. 冷启动 → 可动
print("=== 冷启动 ===")
assert b.boot_to_title(), "标题失败"
assert b.start_new_game(), "新游戏失败"
print("推进开场...")
t0 = time.time()
while time.time() - t0 < 600:
    if real_move_any():
        print(f"🎉 真可动 ({time.time()-t0:.0f}s)")
        break
    b.advance_with_watchdog(120)
else:
    print("✗ 未可控")
    sys.exit(1)
st = ex.extract(emu)
print(f"可控点: ({st.player_x},{st.player_y})")

# 2. 导航门口 + 出门
ok = nav_to_door()
print(f"到门口: {ok}")
emu.press(Key.RIGHT, 4)
emu.run_frames(10)
emu.press(Key.RIGHT, 30)
emu.run_frames(300)
st = ex.extract(emu)
print(f"出门后: ({st.player_x},{st.player_y}) bright={emu.screenshot().mean():.0f}")

# 3. 逐帧窗口扫描：3000 帧
print("逐帧扫描 UP 窗口（3000 帧）...")
p0 = (st.player_x, st.player_y)
flag_history = []
hit_frame = None
for i in range(3000):
    emu.run_frames(1)
    fl = emu.u8(F)
    if len(flag_history) < 20 or fl != flag_history[-1]:
        flag_history.append(fl)
    # 按 UP 1 帧测移动
    emu.press_hold(Key.UP)
    emu.run_frames(1)
    p = (emu.u16(0x02020650), emu.u16(0x02020652))
    if abs(p[1] - p0[1]) > 4 or abs(p[0] - p0[0]) > 4:
        hit_frame = i
        print(f"🎉🎉 窗口命中！帧 {i}: {p0} → {p}（MOVE_FLAG={emu.u8(F)}）")
        emu.release()
        # 立即连续移动测试
        moves = 0
        for j in range(300):
            emu.press_hold(Key.UP)
            emu.run_frames(1)
            p = (emu.u16(0x02020650), emu.u16(0x02020652))
            if abs(p[1] - p0[1]) > 4:
                moves += 1
                p0 = p
            else:
                emu.release()
                break
        emu.release()
        print(f"  窗口内连续移动 {moves} 格, 终位 {p0}")
        Path(CK / "window_unlocked.state").write_bytes(emu.save_state())
        print("已保存 window_unlocked.state")
        break
    emu.release()
else:
    print(f"3000 帧未命中。MOVE_FLAG 变化历史: {flag_history}")

st = ex.extract(emu)
print(f"最终: ({st.player_x},{st.player_y}) bright={emu.screenshot().mean():.0f}")
