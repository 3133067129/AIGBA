"""快速恢复测试：load_state → 立即写0 → 立即动（少帧数）；两次出门测试。"""
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
CK = ROOT / "data" / "checkpoints"


def mv_test(tag):
    """方向验证 UP。"""
    st0 = ex.extract(emu)
    p0 = (st0.player_x, st0.player_y)
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
    print(f"  {tag}: ok={ok} →({st.player_x},{st.player_y})")
    return ok


# 1. 恢复后立即写 0 立即动
print("=== 恢复后立即写0立即动 ===")
emu.load_state((CK / "outdoor_real.state").read_bytes())
emu.write(F, b"\x00")
emu.run_frames(3)
mv_test("立即")

# 2. 恢复后等 5 帧再写
print("=== 恢复后等5帧再写 ===")
emu.load_state((CK / "outdoor_real.state").read_bytes())
emu.run_frames(5)
emu.write(F, b"\x00")
emu.run_frames(3)
mv_test("等5帧")

# 3. 恢复后等 120 帧再写
print("=== 恢复后等120帧再写 ===")
emu.load_state((CK / "outdoor_real.state").read_bytes())
emu.run_frames(120)
emu.write(F, b"\x00")
emu.run_frames(3)
mv_test("等120帧")

# 4. 恢复后按 B 再写 0
print("=== 恢复后按B再写0 ===")
emu.load_state((CK / "outdoor_real.state").read_bytes())
emu.run_frames(30)
emu.press(Key.B, 8)
emu.run_frames(20)
emu.write(F, b"\x00")
emu.run_frames(3)
mv_test("按B后")

# 5. 恢复后按 START 再写 0
print("=== 恢复后按START再写0 ===")
emu.load_state((CK / "outdoor_real.state").read_bytes())
emu.run_frames(30)
emu.press(Key.START, 8)
emu.run_frames(30)
emu.write(F, b"\x00")
emu.run_frames(3)
mv_test("按START后")
