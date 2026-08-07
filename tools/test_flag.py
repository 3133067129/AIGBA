"""测试 MOVE_FLAG 是否被游戏每帧重写。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import yaml

from src.emulator.mgba_core import Emulator
from src.state.extractor import GameStateExtractor

cfg = yaml.safe_load(open(ROOT / "config" / "settings.yaml", encoding="utf-8"))
emu = Emulator(rom_path=ROOT / cfg["rom"]["path"])
ex = GameStateExtractor()
F = 0x03000F2C

emu.load_state((ROOT / "data/checkpoints/outdoor_real.state").read_bytes())
emu.run_frames(30)
print(f"恢复后 MOVE_FLAG = {emu.u8(F)}")
emu.write(F, b"\x00")
emu.run_frames(5)
print(f"写0后5帧 = {emu.u8(F)}")
emu.run_frames(30)
print(f"写0后35帧 = {emu.u8(F)}")
emu.write(F, b"\x00")
emu.run_frames(60)
print(f"再写0后60帧 = {emu.u8(F)}")
st = ex.extract(emu)
print(f"pos=({st.player_x},{st.player_y}) bright={emu.screenshot().mean():.0f}")

# 每帧写0（on_frame）测试
count = [0]
def unlock(e):
    e.write(F, b"\x00")
emu.on_frame = unlock
emu.run_frames(120)
emu.on_frame = None
print(f"每帧写0后120帧 = {emu.u8(F)}")
st = ex.extract(emu)
print(f"pos=({st.player_x},{st.player_y}) bright={emu.screenshot().mean():.0f}")

# 可动测试
from src.emulator.keys import Key
p0 = (st.player_x, st.player_y)
emu.write(F, b"\x00")
emu.press_hold(Key.DOWN)
moved = False
for _ in range(60):
    emu.run_frames(1)
    emu.write(F, b"\x00")
    st2 = ex.extract(emu)
    if (st2.player_x, st2.player_y) != p0:
        moved = True
        break
emu.release()
emu.run_frames(10)
print(f"每帧写0 + DOWN: moved={moved} →({st2.player_x},{st2.player_y})")
