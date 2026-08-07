"""门洞连贯推进：进门洞后继续按方向键/A 穿过门。

实验 A：town.state (120,112) → 面向 DOWN 长按 → 进门洞 → 继续 DOWN → 检测
实验 B：2F → (120,128) 面向 UP 进门洞 → 继续 UP → 检测
"""
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

cfg = yaml.safe_load(open(ROOT / "config" / "settings.yaml", encoding="utf-8"))
emu = Emulator(rom_path=ROOT / cfg["rom"]["path"])
ex = GameStateExtractor()
ctrl = Controller(emu, ex)
CK = ROOT / "data" / "checkpoints"
DIR_KEY = {"UP": Key.UP, "DOWN": Key.DOWN, "LEFT": Key.LEFT, "RIGHT": Key.RIGHT}


def rep(tag):
    st = ex.extract(emu)
    print(f"{tag}: pos=({st.player_x},{st.player_y}) "
          f"grid=({st.player_x//16},{st.player_y//16}) bright={emu.screenshot().mean():.0f}")


def check_exit(tag):
    st = ex.extract(emu)
    b = float(emu.screenshot().mean())
    if b > 130:
        print(f"🎉🎉🎉 出门！！[{tag}] bright={b:.0f} pos=({st.player_x},{st.player_y})")
        Path(CK / "outdoor_real.state").write_bytes(emu.save_state())
        print("已保存 outdoor_real.state")
        sys.exit(0)
    return st, b


def hold(key, frames):
    emu.press_hold(key)
    for _ in range(frames):
        emu.run_frames(1)
    emu.release()
    emu.run_frames(20)


# ===== 实验 A：town.state (120,112) 门洞态 =====
print("=== 实验 A：town.state (120,112) → DOWN 连贯推进 ===")
emu.load_state((CK / "town.state").read_bytes())
emu.run_frames(30)
rep("town起点")
for step in range(6):
    hold(Key.DOWN, 60)
    st, b = check_exit(f"town DOWN×{step+1}")
    print(f"  DOWN×{step+1}: ({st.player_x},{st.player_y}) bright={b:.0f}")

# 若 DOWN 后位置变了但没出门，试 A
rep("DOWN后")
hold(Key.A, 30)
st, b = check_exit("town DOWN后A")
print(f"  A: ({st.player_x},{st.player_y}) bright={b:.0f}")

# 回到 town 试 UP 方向连贯
emu.load_state((CK / "town.state").read_bytes())
emu.run_frames(30)
for step in range(6):
    hold(Key.UP, 60)
    st, b = check_exit(f"town UP×{step+1}")
    print(f"  UP×{step+1}: ({st.player_x},{st.player_y}) bright={b:.0f}")

print("\n实验 A 未出门")
