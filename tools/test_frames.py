"""测试：恢复 outdoor_real → 每帧写0 → 方向验证可动？"""
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

emu.load_state((ROOT / "data/checkpoints/outdoor_real.state").read_bytes())
emu.run_frames(30)

# 每帧写 0
def unlock(e):
    e.write(F, b"\x00")
emu.on_frame = unlock
emu.run_frames(60)

st = ex.extract(emu)
print(f"位置: ({st.player_x},{st.player_y}) bright={emu.screenshot().mean():.0f}")

# 方向验证 UP
p0 = (st.player_x, st.player_y)
emu.press_hold(Key.UP)
ok = False
for _ in range(60):
    emu.run_frames(1)
    st = ex.extract(emu)
    if st.player_y < p0[1] - 10 and abs(st.player_x - p0[0]) < 8:
        ok = True
        break
emu.release()
emu.run_frames(10)
st = ex.extract(emu)
print(f"UP 方向验证: ok={ok} →({st.player_x},{st.player_y})")

# 再测 DOWN
if not ok:
    p0 = (st.player_x, st.player_y)
    emu.press_hold(Key.DOWN)
    for _ in range(60):
        emu.run_frames(1)
        st = ex.extract(emu)
        if st.player_y > p0[1] + 10 and abs(st.player_x - p0[0]) < 8:
            ok = True
            break
    emu.release()
    emu.run_frames(10)
    st = ex.extract(emu)
    print(f"DOWN 方向验证: ok={ok} →({st.player_x},{st.player_y})")
