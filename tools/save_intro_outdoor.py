"""冷启动 → 新游戏 → 推进开场 → 玩家可控（户外）→ 保存 → 验证 → DFS 探索未白镇。"""
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
from src.perception.llm_vision import make_provider

cfg = yaml.safe_load(open(ROOT / "config" / "settings.yaml", encoding="utf-8"))
emu = Emulator(rom_path=ROOT / cfg["rom"]["path"])
ex = GameStateExtractor()
ctrl = Controller(emu, ex)
vision = make_provider(cfg["llm"])
b = NewGameBootstrap(emu, ex, vision)
CK = ROOT / "data" / "checkpoints"


def player_controllable():
    import numpy as np
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


print("=== 1. 新游戏流程 ===")
assert b.boot_to_title(), "标题失败"
assert b.start_new_game(), "新游戏失败"
print("等待博士对话...")
t0 = time.time()
while time.time() - t0 < 200:
    b.run_frames_quiet(300)
    if "久等" in vision.describe([emu.screenshot()], "一句话")[:40]:
        break

print("推进开场...")
t0 = time.time()
while time.time() - t0 < 420:
    if player_controllable():
        print(f"🎉 玩家可控 ({time.time()-t0:.0f}s)")
        st = ex.extract(emu)
        print(f"pos=({st.player_x},{st.player_y}) bright={emu.screenshot().mean():.0f}")
        CK.joinpath("outdoor_real.state").write_bytes(emu.save_state())
        print("✅ 已保存 outdoor_real.state")
        break
    else:
        b.advance_with_watchdog(120, on_change=lambda d, t: None)

# 验证可动
print("\n=== 2. 可动验证 ===")
emu.load_state((CK / "outdoor_real.state").read_bytes())
emu.run_frames(30)
st = ex.extract(emu)
print(f"恢复: pos=({st.player_x},{st.player_y}) bright={emu.screenshot().mean():.0f}")
moved_any = False
for d, k in [("UP", Key.UP), ("DOWN", Key.DOWN), ("LEFT", Key.LEFT), ("RIGHT", Key.RIGHT)]:
    p0 = (st.player_x, st.player_y)
    emu.press_hold(k)
    moved = False
    for _ in range(90):
        emu.run_frames(1)
        st2 = ex.extract(emu)
        if (st2.player_x, st2.player_y) != p0:
            moved = True
            break
    emu.release()
    emu.run_frames(15)
    print(f"  {d}: moved={moved} →({st2.player_x},{st2.player_y})")
    moved_any = moved_any or moved

if not moved_any:
    print("✗ 不可动")
    sys.exit(1)

# DFS 探索未白镇
print("\n=== 3. DFS 探索未白镇 ===")
explorer = DfsExplorer(emu, ex, ctrl, outdoor_bright=999, unlock_dialog=False,
                       on_step=lambda t: print(f"  {t}"))
result = explorer.run(max_steps=1500)
print("RESULT:", result)
print("\n完成")
