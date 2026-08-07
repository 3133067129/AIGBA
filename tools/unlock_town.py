"""冷启动单进程：家 2F 可控 → 出门 → 立即解锁 → DFS 探索未白镇。

关键：不保存/恢复 savestate（不稳定）；写 0x03000F2C=0 后立即测动。
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


def can_move(d, frames=50):
    st0 = ex.extract(emu)
    p0 = (st0.player_x, st0.player_y)
    emu.press_hold(DIR_KEY[d])
    moved = False
    for _ in range(frames):
        emu.run_frames(1)
        st = ex.extract(emu)
        if (st.player_x, st.player_y) != p0:
            moved = True
            break
    emu.release()
    emu.run_frames(10)
    st = ex.extract(emu)
    return moved, (st.player_x, st.player_y)


# ---- 1. 冷启动 ----
print("=== 冷启动 ===")
assert b.boot_to_title(), "标题失败"
assert b.start_new_game(), "新游戏失败"
print("推进开场...")
t0 = time.time()
while time.time() - t0 < 600:
    if player_controllable():
        print(f"🎉 可控 ({time.time()-t0:.0f}s)")
        break
    # on_change=None：不调 LLM（CPU 推理 96s/次太慢）
    b.advance_with_watchdog(120)

st = ex.extract(emu)
print(f"可控点: ({st.player_x},{st.player_y}) bright={emu.screenshot().mean():.0f}")

# ---- 2. 出门（面向 RIGHT 按方向键）----
print("面向 RIGHT 出门...")
emu.press(Key.RIGHT, 4)
emu.run_frames(10)
emu.press(Key.RIGHT, 30)
emu.run_frames(300)  # 转场
st = ex.extract(emu)
print(f"出门后: ({st.player_x},{st.player_y}) bright={emu.screenshot().mean():.0f}")

# ---- 3. 解锁 + 可动测试 ----
emu.write(F, b"\x00")
emu.run_frames(10)
moved_any = False
for d in ["UP", "DOWN", "LEFT", "RIGHT"]:
    moved, end = can_move(d)
    print(f"  {d}: moved={moved} →{end} bright={emu.screenshot().mean():.0f}")
    moved_any = moved_any or moved

if not moved_any:
    print("✗ 未解锁")
    sys.exit(1)

print("🎉 解锁成功！")
Path(CK / "outdoor_real.state").write_bytes(emu.save_state())
print("已保存 outdoor_real.state")

# ---- 4. DFS 探索（找建筑门/NPC）----
print("\n=== DFS 探索 ===")
explorer = DfsExplorer(emu, ex, ctrl, outdoor_bright=999, unlock_dialog=False,
                       on_step=lambda t: print(f"  {t}"))
result = explorer.run(max_steps=3000)
print("RESULT:", result)
Path(CK / "outdoor_real.state").write_bytes(emu.save_state())
print("已重存 outdoor_real.state")
