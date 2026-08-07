"""关闭 (120,80) 处的调钟界面（guide_clock 验证序列）→ 检测解锁 → 探索。"""
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
DIR_KEY = {"UP": Key.UP, "DOWN": Key.DOWN, "LEFT": Key.LEFT, "RIGHT": Key.RIGHT}

emu.load_state((ROOT / "data/checkpoints/outdoor_real.state").read_bytes())
emu.run_frames(30)


def rep(tag):
    st = ex.extract(emu)
    print(f"{tag}: pos=({st.player_x},{st.player_y}) "
          f"grid=({st.player_x//16},{st.player_y//16}) bright={emu.screenshot().mean():.0f}")


rep("恢复（界面开？）")
b0 = float(emu.screenshot().mean())

# 调钟序列（guide_clock 实证）：调小时→确认→调分钟→确认→完成
print("调钟序列...")
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
emu.run_frames(150)
rep("调钟后")
print(f"bright: {b0:.0f} → {emu.screenshot().mean():.0f}")

# 可动检测
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
    print(f"  {d}: moved={moved} →({st.player_x},{st.player_y}) "
          f"bright={emu.screenshot().mean():.0f}")
    if moved:
        print(f"🎉 {d} 可动！")
        # 保存解锁状态
        Path(ROOT / "data/checkpoints/outdoor_real.state").write_bytes(emu.save_state())
        print("已保存 outdoor_real.state（解锁）")
        # 探索
        explorer = DfsExplorer(emu, ex, ctrl, outdoor_bright=130, unlock_dialog=False,
                               on_step=lambda t: print(f"  {t}"))
        r = explorer.run(max_steps=200)
        print("探索 RESULT:", r)
        sys.exit(0)

print("仍锁死")
