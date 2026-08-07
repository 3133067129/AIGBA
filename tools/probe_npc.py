"""未白镇 4 方向按 A 对话探测 → 推进 → 解锁。"""
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
from src.control.controller import Controller

cfg = yaml.safe_load(open(ROOT / "config" / "settings.yaml", encoding="utf-8"))
emu = Emulator(rom_path=ROOT / cfg["rom"]["path"])
ex = GameStateExtractor()
ctrl = Controller(emu, ex)
F = 0x03000F2C
CK = ROOT / "data" / "checkpoints"
DIR_KEY = {"UP": Key.UP, "DOWN": Key.DOWN, "LEFT": Key.LEFT, "RIGHT": Key.RIGHT}


def stable_text(frames=30):
    tr = emu.screenshot()[96:158, 8:232]
    h1 = hashlib.sha256(tr.tobytes()).hexdigest()
    for _ in range(frames):
        emu.run_frames(5)
        if hashlib.sha256(emu.screenshot()[96:158, 8:232].tobytes()).hexdigest() == h1:
            return True
    return False


def push_dialog(max_pages=15):
    pages = 0
    for _ in range(max_pages):
        if not ctrl.dialog_open():
            break
        if not stable_text():
            continue
        h = hashlib.sha256(emu.screenshot().tobytes()).hexdigest()[:6]
        emu.press(Key.A, 8)
        emu.run_frames(80)
        h2 = hashlib.sha256(emu.screenshot().tobytes()).hexdigest()[:6]
        pages += 1
        if h2 == h:
            break
    return pages


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


emu.load_state((CK / "outdoor_real.state").read_bytes())
emu.run_frames(30)
emu.write(F, b"\x00")
emu.run_frames(10)
st = ex.extract(emu)
print(f"位置: ({st.player_x},{st.player_y}) bright={emu.screenshot().mean():.0f}")

for d in ["UP", "DOWN", "LEFT", "RIGHT"]:
    emu.load_state((CK / "outdoor_real.state").read_bytes())
    emu.run_frames(30)
    emu.write(F, b"\x00")
    emu.run_frames(10)
    emu.press(DIR_KEY[d], 3)
    emu.run_frames(6)
    emu.press(Key.A, 8)
    emu.run_frames(150)
    dlg = ctrl.dialog_open()
    st = ex.extract(emu)
    print(f"面向{d} 按A: dialog={dlg} pos=({st.player_x},{st.player_y})")
    if dlg:
        pages = push_dialog(15)
        print(f"  对话推进 {pages} 页")
        ok = mv_test()
        print(f"  解锁测试: ok={ok}")
        if ok:
            print("🎉🎉🎉 解锁成功！")
            Path(CK / "outdoor_real.state").write_bytes(emu.save_state())
            sys.exit(0)
        # 再按 A 一轮
        pages2 = push_dialog(15)
        print(f"  再推进 {pages2} 页")
        ok = mv_test()
        print(f"  解锁测试2: ok={ok}")
        if ok:
            print("🎉🎉🎉 解锁成功！")
            Path(CK / "outdoor_real.state").write_bytes(emu.save_state())
            sys.exit(0)

print("\n未解锁")
