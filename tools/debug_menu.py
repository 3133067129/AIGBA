"""菜单（173）→ 按 A 看进入什么；失败则 DOWN/UP 切换再试。"""
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

b.boot_to_title(timeout_frames=9000)
# 变焦 + DOWN+A×2 进菜单
emu.press(Key.A, 10)
emu.run_frames(300)
emu.press(Key.DOWN, 8)
emu.press(Key.A, 10)
emu.run_frames(60)
emu.press(Key.DOWN, 8)
emu.press(Key.A, 10)
emu.run_frames(200)
print(f"菜单? bright={b._brightness():.0f} is_menu={b.is_menu()}")

# 截图分析菜单文字行位置（找选项位置）
screen = emu.screenshot()
g = screen.mean(axis=2)
# 找文字行（暗底上的亮字）
rows = [y for y in range(40, 160) if g[y].min() < 80 and g[y].max() > 150]
print(f"文字行: {rows[:20]}...（{len(rows)} 行）")

# 按 A 选第一项
emu.press(Key.A, 10)
emu.run_frames(300)
br = b._brightness()
print(f"\nA 后: bright={br:.0f}")
if br < 60:
    print("🎉 黑屏 = 新游戏开始！")
else:
    print("非黑屏——可能在设置界面")
    # B 退出重试：UP+A（选上一项？）
    emu.press(Key.B, 10)
    emu.run_frames(60)
    emu.press(Key.UP, 8)
    emu.press(Key.A, 10)
    emu.run_frames(300)
    br2 = b._brightness()
    print(f"UP+A 后: bright={br2:.0f}")
    if br2 < 60:
        print("🎉 UP+A 黑屏 = 新游戏开始！")
