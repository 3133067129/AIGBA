"""冷启动 v2：方向验证可控判定 + 推进剧情到真可动 + 出门。

"真可动"判定：按 UP 后 y 减 16±2 且 x 不变（坐标方向验证，防 NPC 动画假阳性）。
"""
from __future__ import annotations

import hashlib
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
from src.perception.llm_vision import make_provider

cfg = yaml.safe_load(open(ROOT / "config" / "settings.yaml", encoding="utf-8"))
emu = Emulator(rom_path=ROOT / cfg["rom"]["path"])
ex = GameStateExtractor()
ctrl = Controller(emu, ex)
vision = make_provider(cfg["llm"])
b = NewGameBootstrap(emu, ex, vision)
CK = ROOT / "data" / "checkpoints"
F = 0x03000F2C
DIR_KEY = {"UP": Key.UP, "DOWN": Key.DOWN, "LEFT": Key.LEFT, "RIGHT": Key.RIGHT}


def real_move_test():
    """方向验证移动：按 UP 后 y 减 ~16 且 x 不变 = 真移动。返回 (ok, pos)。"""
    st0 = ex.extract(emu)
    p0 = (st0.player_x, st0.player_y)
    emu.press_hold(Key.UP)
    for _ in range(60):
        emu.run_frames(1)
        st = ex.extract(emu)
        if st.player_y < p0[1] - 10 and abs(st.player_x - p0[0]) < 8:
            emu.release()
            emu.run_frames(10)
            return True, (st.player_x, st.player_y)
    emu.release()
    emu.run_frames(10)
    return False, (st.player_x, st.player_y)


def stable_text(frames=30):
    tr = emu.screenshot()[96:158, 8:232]
    h1 = hashlib.sha256(tr.tobytes()).hexdigest()
    for _ in range(frames):
        emu.run_frames(5)
        if hashlib.sha256(emu.screenshot()[96:158, 8:232].tobytes()).hexdigest() == h1:
            return True
    return False


def push_dialog(max_pages=12):
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


# ---- 1. 冷启动 ----
print("=== 冷启动 ===")
assert b.boot_to_title(), "标题失败"
assert b.start_new_game(), "新游戏失败"
print("推进开场（最长 10 分钟）...")
t0 = time.time()
while time.time() - t0 < 600:
    ok, pos = real_move_test()
    if ok:
        print(f"🎉 真可动 ({time.time()-t0:.0f}s) pos={pos} "
              f"bright={emu.screenshot().mean():.0f}")
        break
    # 推进对话
    if ctrl.dialog_open():
        p = push_dialog(6)
        if p:
            print(f"  对话推进 {p} 页")
    b.advance_with_watchdog(120)
else:
    print("✗ 600s 未真可动")
    sys.exit(1)

# ---- 2. 导航到门口 (152,112) ----
print("导航到门口 (152,112)...")
explorer = DfsExplorer(emu, ex, ctrl, outdoor_bright=999, unlock_dialog=False)
target = (9, 7)
visited = {explorer._grid()}
stack = []
g = explorer._grid()
facing = "UP"
BACK = {"UP": "DOWN", "DOWN": "UP", "LEFT": "RIGHT", "RIGHT": "LEFT"}
found = False
for steps in range(300):
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
print(f"到门口: {found}（visited={len(visited)}）")
st = ex.extract(emu)
print(f"门口: ({st.player_x},{st.player_y}) bright={emu.screenshot().mean():.0f}")

# ---- 3. 出门 ----
print("面向 RIGHT 按方向键出门...")
emu.press(Key.RIGHT, 4)
emu.run_frames(10)
emu.press(Key.RIGHT, 30)
emu.run_frames(300)
st = ex.extract(emu)
print(f"出门后: ({st.player_x},{st.player_y}) bright={emu.screenshot().mean():.0f}")

# ---- 4. 解锁 + 推进剧情 + 方向验证 ----
print("出门后：推进剧情/对话直到真可动（最长 5 分钟）...")
emu.write(F, b"\x00")
emu.run_frames(10)
t1 = time.time()
while time.time() - t1 < 300:
    ok, pos = real_move_test()
    if ok:
        print(f"🎉 未白镇真可动 ({time.time()-t1:.0f}s) pos={pos}")
        break
    # 推进对话
    p = push_dialog(8)
    if p:
        print(f"  对话推进 {p} 页")
    else:
        emu.run_frames(300)
    st = ex.extract(emu)
    if int(time.time() - t1) % 30 == 0:
        print(f"  [{int(time.time()-t1)}s] pos=({st.player_x},{st.player_y}) "
              f"bright={emu.screenshot().mean():.0f}")
else:
    print("✗ 300s 未真可动")
    sys.exit(1)

print("🎉 未白镇解锁成功！")
Path(CK / "outdoor_real.state").write_bytes(emu.save_state())
print("已保存 outdoor_real.state")

# ---- 5. DFS 探索 ----
print("\n=== DFS 探索 ===")
explorer2 = DfsExplorer(emu, ex, ctrl, outdoor_bright=999, unlock_dialog=False,
                        on_step=lambda t: print(f"  {t}"))
result = explorer2.run(max_steps=3000)
print("RESULT:", result)
Path(CK / "outdoor_real.state").write_bytes(emu.save_state())
print("已重存 outdoor_real.state")
