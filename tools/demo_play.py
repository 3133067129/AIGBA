"""带预览窗的 AI 演示：冷启动 → 新游戏 → 开场 → 可控 → 出门 → 未白镇。

预览窗实时显示 + HUD 状态；用户可方向键/A/B 人工接管、+/- 调速、p 暂停。
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
from src.emulator.preview import PreviewWindow

cfg = yaml.safe_load(open(ROOT / "config" / "settings.yaml", encoding="utf-8"))
emu = Emulator(rom_path=ROOT / cfg["rom"]["path"])
ex = GameStateExtractor()
ctrl = Controller(emu, ex)
b = NewGameBootstrap(emu, ex, None)
CK = ROOT / "data" / "checkpoints"
F = 0x03000F2C
DIR_KEY = {"UP": Key.UP, "DOWN": Key.DOWN, "LEFT": Key.LEFT, "RIGHT": Key.RIGHT}

win = PreviewWindow(scale=4, speed=3, emu=emu, title="AI 玩绿宝石386 - 演示")
emu.on_frame = lambda e: win.push(e.screenshot())


def status(text):
    print(text)
    win.set_status(text)


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


try:
    status("1/5 标题...")
    assert b.boot_to_title(timeout_frames=9000), "标题失败"
    status("2/5 新游戏...")
    assert b.start_new_game(), "新游戏失败"
    status("3/5 推进开场...")
    t0 = time.time()
    while time.time() - t0 < 600:
        if win.abort_requested():
            sys.exit(0)
        if real_move("UP"):
            status(f"🎉 可控 ({time.time()-t0:.0f}s)！导航到门口")
            break
        b.advance_with_watchdog(120)
    status("4/5 导航到门口 (152,112)...")
    explorer = DfsExplorer(emu, ex, ctrl, outdoor_bright=999, unlock_dialog=False)
    target = (9, 7)
    visited = {explorer._grid()}
    stack = []
    g = explorer._grid()
    facing = "UP"
    BACK = {"UP": "DOWN", "DOWN": "UP", "LEFT": "RIGHT", "RIGHT": "LEFT"}
    found = False
    for steps in range(300):
        if win.abort_requested():
            sys.exit(0)
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
    status(f"到门口: {found}")
    st = ex.extract(emu)
    status(f"门口 ({st.player_x},{st.player_y})，按 RIGHT 出门")
    emu.press(Key.RIGHT, 4)
    emu.run_frames(10)
    emu.press(Key.RIGHT, 30)
    emu.run_frames(300)
    st = ex.extract(emu)
    status(f"5/5 出门后: ({st.player_x},{st.player_y}) bright={emu.screenshot().mean():.0f}")
    status("未白镇！(移动锁待解) 可人工接管试按键")
    # 保持窗口开着让用户看/操作
    while not win.abort_requested():
        emu.run_frames(1)
except Exception as e:
    print(f"ERROR: {e}")
finally:
    win.close()
print("演示结束")
