"""像素级移动判定：静止 vs 按 UP 的画面变化对比。"""
from __future__ import annotations

import hashlib
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

cfg = yaml.safe_load(open(ROOT / "config" / "settings.yaml", encoding="utf-8"))
emu = Emulator(rom_path=ROOT / cfg["rom"]["path"])
ex = GameStateExtractor()
F = 0x03000F2C
CK = ROOT / "data" / "checkpoints"


def hash_screen():
    return hashlib.sha256(emu.screenshot().tobytes()).hexdigest()[:16]


def diff_pct(s0, s1):
    return float((s0 != s1).mean())


emu.load_state((CK / "outdoor_real.state").read_bytes())
emu.run_frames(30)
emu.write(F, b"\x00")
emu.run_frames(10)
st = ex.extract(emu)
print(f"位置: ({st.player_x},{st.player_y}) bright={emu.screenshot().mean():.0f}")

# 1. 静止基线：300 帧画面变化
s0 = emu.screenshot()
changes = []
for i in range(15):
    emu.run_frames(20)
    s1 = emu.screenshot()
    changes.append(diff_pct(s0, s1))
    s0 = s1
print(f"静止 300 帧: 平均变化 {np.mean(changes)*100:.2f}%（NPC 动画基线）")

# 2. 按 UP 300 帧
s0 = emu.screenshot()
emu.press_hold(Key.UP)
up_changes = []
for i in range(15):
    emu.run_frames(20)
    s1 = emu.screenshot()
    up_changes.append(diff_pct(s0, s1))
    s0 = s1
emu.release()
print(f"按 UP 300 帧: 平均变化 {np.mean(up_changes)*100:.2f}%")

# 3. 按 RIGHT 300 帧
emu.run_frames(30)
s0 = emu.screenshot()
emu.press_hold(Key.RIGHT)
r_changes = []
for i in range(15):
    emu.run_frames(20)
    s1 = emu.screenshot()
    r_changes.append(diff_pct(s0, s1))
    s0 = s1
emu.release()
print(f"按 RIGHT 300 帧: 平均变化 {np.mean(r_changes)*100:.2f}%")

# 结论
print(f"\n静止基线: {np.mean(changes)*100:.2f}%")
print(f"UP: {np.mean(up_changes)*100:.2f}%  RIGHT: {np.mean(r_changes)*100:.2f}%")
if np.mean(up_changes) > np.mean(changes) * 3:
    print("🎉 玩家在动（UP 画面变化远大于基线）！坐标不可靠但玩家可动！")
else:
    print("✗ 玩家没动（画面变化与基线相当）——真的锁着")
