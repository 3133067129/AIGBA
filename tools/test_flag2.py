"""每帧解锁 + 位置校正 + 4 方向可动测试。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import yaml

from src.emulator.keys import Key
from src.emulator.mgba_core import Emulator
from src.state.extractor import GameStateExtractor

cfg = yaml.safe_load(open(ROOT / "config" / "settings.yaml", encoding="utf-8"))
emu = Emulator(rom_path=ROOT / cfg["rom"]["path"])
ex = GameStateExtractor()
F = 0x03000F2C
PX, PY = 0x02020650, 0x02020652
DIR_KEY = {"UP": Key.UP, "DOWN": Key.DOWN, "LEFT": Key.LEFT, "RIGHT": Key.RIGHT}

emu.load_state((ROOT / "data/checkpoints/outdoor_real.state").read_bytes())
emu.run_frames(30)

# 每帧解锁
def unlock(e):
    e.write(F, b"\x00")
emu.on_frame = unlock

st = ex.extract(emu)
print(f"当前: ({st.player_x},{st.player_y}) bright={emu.screenshot().mean():.0f}")

# 瞬移到未白镇已知可动点 (136,128)
emu.write(PX, (136).to_bytes(2, "little"))
emu.write(PY, (128).to_bytes(2, "little"))
emu.run_frames(20)
st = ex.extract(emu)
print(f"瞬移(136,128)后: ({st.player_x},{st.player_y}) bright={emu.screenshot().mean():.0f}")

# 4 方向
for d in ["UP", "DOWN", "LEFT", "RIGHT"]:
    st0 = ex.extract(emu)
    p0 = (st0.player_x, st0.player_y)
    emu.press_hold(DIR_KEY[d])
    moved = False
    for _ in range(60):
        emu.run_frames(1)
        st = ex.extract(emu)
        if (st.player_x, st.player_y) != p0:
            moved = True
            break
    emu.release()
    emu.run_frames(10)
    st = ex.extract(emu)
    print(f"  {d}: moved={moved} →({st.player_x},{st.player_y}) "
          f"bright={emu.screenshot().mean():.0f}")
