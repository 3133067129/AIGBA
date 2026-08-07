"""攻略驱动验证：冷启动 → 新游戏 → 出门 → 进家 → 调电子钟 → 下楼出门。

全程单进程（不保存/恢复 savestate，绕开过场状态不稳定）。
按攻略：进家与妈妈对话 → 上2楼调整电子钟 → 下楼出门。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import hashlib
import time

import numpy as np
import yaml

from src.emulator.keys import Key
from src.emulator.mgba_core import Emulator
from src.brain.new_game import NewGameBootstrap
from src.control.controller import Controller
from src.control.dfs import DfsExplorer
from src.state.extractor import GameStateExtractor
from src.perception.llm_vision import make_provider

cfg = yaml.safe_load(open(ROOT / "config" / "settings.yaml", encoding="utf-8"))
emu = Emulator(rom_path=ROOT / cfg["rom"]["path"])
ex = GameStateExtractor()
vision = make_provider(cfg["llm"])
ctrl = Controller(emu, ex)
b = NewGameBootstrap(emu, ex, vision)


def rep(tag):
    st = ex.extract(emu)
    print(f"{tag}: ({st.player_x},{st.player_y}) bright={float(emu.screenshot().mean()):.0f}")


def push_dialog(max_pages=8, stop_on_move=True, start_pos=None):
    """推进对话：等文字稳定 → A。位置变化 = 转场即停。"""
    start_pos = start_pos or (ex.extract(emu).player_x,
                              ex.extract(emu).player_y)
    for i in range(max_pages):
        for _ in range(30):
            tr = emu.screenshot()[96:158, 8:232]
            h1 = hashlib.sha256(tr.tobytes()).hexdigest()
            emu.run_frames(5)
            if hashlib.sha256(emu.screenshot()[96:158, 8:232].tobytes()).hexdigest() == h1:
                break
        h = hashlib.sha256(emu.screenshot().tobytes()).hexdigest()[:6]
        emu.press(Key.A, 8)
        emu.run_frames(80)
        h2 = hashlib.sha256(emu.screenshot().tobytes()).hexdigest()[:6]
        now = ex.extract(emu)
        if stop_on_move and (now.player_x, now.player_y) != start_pos:
            print(f"  转场完成 (A×{i+1})")
            return True
        if h2 == h:
            print(f"  对话完 (A×{i+1})")
            return True
    return False


# ---- 1. 冷启动新游戏 ----
print("=== 1. 新游戏流程 ===")
assert b.boot_to_title(), "标题失败"
assert b.start_new_game(), "新游戏失败"
print("等待博士对话...")
t0 = time.time()
while time.time() - t0 < 200:
    b.run_frames_quiet(300)
    if "久等" in vision.describe([emu.screenshot()], "一句话")[:40]:
        break


def player_controllable():
    s0 = emu.screenshot()
    emu.run_frames(30)
    s1 = emu.screenshot()
    if float((s0 != s1).mean()) > 0.02:
        return False
    s0 = emu.screenshot()
    emu.press_hold(Key.RIGHT)
    emu.run_frames(30)
    emu.release()
    emu.run_frames(10)
    s1 = emu.screenshot()
    return float((s0 != s1).mean()) > 0.05


print("推进开场...")
t0 = time.time()
while time.time() - t0 < 420:
    if player_controllable():
        print(f"玩家可控 ({time.time()-t0:.0f}s) → 出门")
        # 出门（LLM 判断门方向）
        for _ in range(8):
            s = emu.screenshot()
            d = vision.describe([s], "你在房间里，门/出口在哪个方向？只回答：上/下/左/右")[:8]
            key = {"上": Key.UP, "下": Key.DOWN, "左": Key.LEFT, "右": Key.RIGHT}\
                .get(d.strip()[0] if d.strip() else "", Key.RIGHT)
            emu.press_hold(key)
            emu.run_frames(40)
            emu.release()
            emu.run_frames(10)
            if not player_controllable():
                break
        break
    else:
        b.advance_with_watchdog(120, on_change=lambda d, t: None)
rep("出门后")

# ---- 2. 妈妈对话 → 过场（位置变化=转场判据不可靠，过场动画中坐标也会动）----
print("=== 2. 妈妈对话 → 过场 ===")
push_dialog(10)
emu.run_frames(300)
rep("推进后")

# ---- 3. 过场播完：静止预检 + 可动测试（最长 200s）----
print("=== 3. 等过场完（可动）===")
t0 = time.time()
while time.time() - t0 < 200:
    if player_controllable():
        print("玩家可控 ✓")
        break
    # 推进可能的对话（等文字稳定→A）
    h = hashlib.sha256(emu.screenshot().tobytes()).hexdigest()[:8]
    emu.run_frames(60)
    if hashlib.sha256(emu.screenshot().tobytes()).hexdigest()[:8] == h:
        emu.press(Key.A, 8)
        emu.run_frames(60)
    else:
        emu.run_frames(120)
else:
    print("200s 内未可控")
rep("解锁后")

# ---- 4. 找电子钟（DFS + LLM 确认）----
print("=== 4. 找电子钟 ===")
explorer = DfsExplorer(emu, ex, ctrl, outdoor_bright=999, unlock_dialog=True)
visited = {explorer._grid()}
stack = []
g = explorer._grid()
facing = "UP"
DIRS = ["UP", "RIGHT", "DOWN", "LEFT"]
BACKD = {"UP": "DOWN", "DOWN": "UP", "LEFT": "RIGHT", "RIGHT": "LEFT"}
clock_found = False
for step in range(80):
    if step % 2 == 0:
        desc = vision.describe(
            [emu.screenshot()],
            "画面里有没有电子钟（墙上钟表/显示数字）？有的话在哪个方向？只回答：没有/上/下/左/右")
        ans = desc.strip()[:3]
        print(f"  找钟[{step}]: {ans}")
        if "没有" not in ans and ans:
            zh = {"上": "UP", "下": "DOWN", "左": "LEFT", "右": "RIGHT"}
            cd = zh.get(ans[0])
            if cd:
                print(f"🎯 电子钟在{cd}方向")
                emu.press(getattr(Key, cd), 4)
                emu.run_frames(10)
                emu.press(Key.A, 8)
                emu.run_frames(150)
                rep("打开调钟界面")
                desc2 = vision.describe([emu.screenshot()],
                                        "这是什么界面？有时间设置吗？逐字列出文字。")
                print(f"  界面: {desc2[:150]}")
                # 完整调钟序列（绿宝石标准）：调小时→确认→调分钟→确认
                for _ in range(3):
                    emu.press(Key.UP, 8)
                    emu.run_frames(20)
                emu.press(Key.A, 8)
                emu.run_frames(60)
                for _ in range(3):
                    emu.press(Key.UP, 8)
                    emu.run_frames(20)
                emu.press(Key.A, 8)
                emu.run_frames(60)
                emu.press(Key.A, 8)
                emu.run_frames(100)
                rep("调钟完成")
                desc3 = vision.describe([emu.screenshot()],
                                        "还在时间设置界面吗？还是回到房间了？")
                print(f"  完成后: {desc3[:120]}")
                clock_found = True
                break
    right = {"UP": "RIGHT", "RIGHT": "DOWN", "DOWN": "LEFT", "LEFT": "UP"}[facing]
    left = {"UP": "LEFT", "LEFT": "DOWN", "DOWN": "RIGHT", "RIGHT": "UP"}[facing]
    moved = False
    for d in [right, facing, left, BACKD[facing]]:
        ng = explorer.move_one(d)
        if ng is None:
            continue
        if ng in visited:
            explorer.move_one(BACKD[d])
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
    explorer.move_one(BACKD[came])
    g = prev
print(f"找钟: found={clock_found} visited={len(visited)}")

# ---- 5. 下楼 → 出门 ----
print("=== 5. 下楼出门 ===")
for i in range(10):
    if explorer.move_one("DOWN") is None:
        break
rep("下楼后")
for d in ["DOWN", "UP", "LEFT", "RIGHT"]:
    s0 = ex.extract(emu)
    emu.press_hold(getattr(Key, d))
    emu.run_frames(30)
    emu.release()
    emu.run_frames(60)
    s1 = ex.extract(emu)
    b = float(emu.screenshot().mean())
    print(f"  {d}: ({s0.player_x},{s0.player_y})->({s1.player_x},{s1.player_y}) bright={b:.0f}")
    if b > 135:
        print(f"🎉🎉 出门成功！{d}方向")
        Path(ROOT / "data/checkpoints" / "outdoor.state").write_bytes(emu.save_state())
        print("已保存 outdoor.state")
        break
    if (s1.player_x, s1.player_y) != (s0.player_x, s0.player_y):
        back = {"UP": "DOWN", "DOWN": "UP", "LEFT": "RIGHT", "RIGHT": "LEFT"}[d]
        emu.press_hold(getattr(Key, back))
        emu.run_frames(30)
        emu.release()
        emu.run_frames(60)
print("完成")
