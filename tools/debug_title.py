"""标题→变焦→菜单时序调试：逐帧打印 bright。"""
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
from src.brain.new_game import NewGameBootstrap
from src.state.extractor import GameStateExtractor

cfg = yaml.safe_load(open(ROOT / "config" / "settings.yaml", encoding="utf-8"))
emu = Emulator(rom_path=ROOT / cfg["rom"]["path"])
ex = GameStateExtractor()
b = NewGameBootstrap(emu, ex, None)

# 等标题
print("等标题...")
ok = b.boot_to_title(timeout_frames=9000)
print(f"标题: {ok} bright={b._brightness():.0f}")

# 按 A（变焦1）
print("\n按 A...")
emu.press(Key.A, 10)
for i in range(20):
    emu.run_frames(30)
    br = b._brightness()
    print(f"  +{(i+1)*30}帧: bright={br:.0f}")

# 暗屏阶段：DOWN+A ×2
print("\nDOWN+A ×2...")
emu.press(Key.DOWN, 8)
emu.press(Key.A, 10)
emu.run_frames(60)
emu.press(Key.DOWN, 8)
emu.press(Key.A, 10)
for i in range(20):
    emu.run_frames(30)
    br = b._brightness()
    print(f"  +{(i+1)*30}帧: bright={br:.0f}")

# 检测菜单
print(f"\n最终: bright={b._brightness():.0f} is_menu={b.is_menu()}")
