""""是/否"界面选"是"：4 方向 × A 穷举，检测界面退出（bright 降/位置变/可动）。"""
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

cfg = yaml.safe_load(open(ROOT / "config" / "settings.yaml", encoding="utf-8"))
emu = Emulator(rom_path=ROOT / cfg["rom"]["path"])
ex = GameStateExtractor()
DIR_KEY = {"UP": Key.UP, "DOWN": Key.DOWN, "LEFT": Key.LEFT, "RIGHT": Key.RIGHT}
CK = ROOT / "data" / "checkpoints"


def reset_to_yesno():
    """恢复 → A（进是/否界面 bright~161）。"""
    emu.load_state((CK / "outdoor_real.state").read_bytes())
    emu.run_frames(30)
    emu.press(Key.A, 8)
    emu.run_frames(120)
    return float(emu.screenshot().mean())


def can_move(d, frames=90):
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
    emu.run_frames(20)
    st = ex.extract(emu)
    return moved, (st.player_x, st.player_y)


print(f"是/否界面初始 bright: {reset_to_yesno():.0f}")

for d in ["UP", "DOWN", "LEFT", "RIGHT"]:
    reset_to_yesno()
    b0 = float(emu.screenshot().mean())
    emu.press(DIR_KEY[d], 8)
    emu.run_frames(60)
    b1 = float(emu.screenshot().mean())
    emu.press(Key.A, 8)
    emu.run_frames(250)
    st = ex.extract(emu)
    b2 = float(emu.screenshot().mean())
    # 界面退出判据：bright 明显变化（界面 150-161，场景应不同）
    tag = "无变化"
    if b2 < b1 - 20 or b2 < 140:
        tag = "🎉 界面关闭？"
    if (st.player_x, st.player_y) != (120, 80):
        tag = f"⚠ 位置变化 ({st.player_x},{st.player_y})"
    print(f"  {d}+A: bright {b0:.0f}→{b1:.0f}(按{d}后)→{b2:.0f} {tag}")
    if tag.startswith("🎉") or tag.startswith("⚠"):
        # 验证可动
        moved, end = can_move("UP")
        print(f"    验证 UP: moved={moved} → {end}")
        if moved:
            print(f"🎉🎉🎉 解锁！{d}+A 成功")
            Path(CK / "outdoor_real.state").write_bytes(emu.save_state())
            sys.exit(0)

print("\n穷举完成，未找到退出组合")
