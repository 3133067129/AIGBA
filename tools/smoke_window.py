"""Phase A 冒烟：mGBA 窗口启动 → 抓屏 → 按键 → 画面变化验证。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import yaml

from src.emulator.window_backend import WindowBackend
from src.emulator.keys import Key
from src.perception.screen import diff_ratio

cfg = yaml.safe_load(open(ROOT / "config" / "settings.yaml", encoding="utf-8"))
MGBA = ROOT / "mGBA.exe"
ROM = ROOT / cfg["rom"]["path"]

print("=== 启动 mGBA + ROM ===")
emu = WindowBackend(mgba_exe=MGBA, rom_path=ROM)
print(f"窗口句柄: {emu.hwnd:#x}")

print("=== 抓屏验证 ===")
emu.run_frames(30)
img = emu.screenshot()
b = float(img.mean())
print(f"截图: {img.shape} bright={b:.1f}（标题画面应 <80）")
assert img.shape == (160, 240, 3), "截图尺寸异常"

print("=== 按键验证：按 A（标题变焦）===")
before = emu.screenshot()
emu.press(Key.A, 10)
emu.run_frames(120)
after = emu.screenshot()
d = diff_ratio(before, after)
print(f"按 A 后画面变化率: {d*100:.1f}%（应 >1%，变焦动画）")
assert d > 0.01, "按 A 无画面响应——键位绑定或 SendInput 有问题"

print("=== 方向键验证（DOWN+A×2 进菜单）===")
emu.press(Key.DOWN, 8)
emu.press(Key.A, 10)
emu.run_frames(60)
emu.press(Key.DOWN, 8)
emu.press(Key.A, 10)
emu.run_frames(240)
img2 = emu.screenshot()
b2 = float(img2.mean())
print(f"按键后 bright={b2:.1f}（菜单应 150-200）")

print("=== savestate 验证（F1 存 / Shift+F1 载）===")
emu.save_state()
emu.run_frames(30)
print("F1 已发（槽 1）")

print("=== 关闭 ===")
emu.close()
print("冒烟完成 ✅")
