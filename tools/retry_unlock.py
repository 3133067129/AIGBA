"""多轮恢复+写0找解锁（unlock_and_explore 曾成功——概率性）。"""
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
F = 0x03000F2C
CK = ROOT / "data" / "checkpoints"
STATE = CK / "outdoor_real.state"
state_bytes = STATE.read_bytes()


def mv_test():
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
    return ok


for i in range(25):
    emu.load_state(state_bytes)
    emu.run_frames(30)
    emu.write(F, b"\x00")
    emu.run_frames(10)
    st = ex.extract(emu)
    ok = mv_test()
    print(f"[{i}] pos=({st.player_x},{st.player_y}) bright={emu.screenshot().mean():.0f} UP={ok}")
    if ok:
        print(f"🎉🎉🎉 第{i}轮解锁成功！！")
        Path(CK / "outdoor_real.state").write_bytes(emu.save_state())
        print("已保存 outdoor_real.state（解锁）")
        sys.exit(0)

print("25 轮均未解锁")
