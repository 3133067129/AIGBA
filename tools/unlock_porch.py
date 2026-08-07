"""在门洞态 (88,128)（bright 105，全墙）穷举解锁操作。

流程：恢复 outdoor_real → 调钟（界面关）→ (88,128) → 穷举。
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
DIR_KEY = {"UP": Key.UP, "DOWN": Key.DOWN, "LEFT": Key.LEFT, "RIGHT": Key.RIGHT}

CK = ROOT / "data/checkpoints"


def rep(tag):
    st = ex.extract(emu)
    print(f"{tag}: pos=({st.player_x},{st.player_y}) "
          f"grid=({st.player_x//16},{st.player_y//16}) bright={emu.screenshot().mean():.0f}")


def reset_to_porch():
    """恢复 → 调钟 → 门洞态 (88,128)。"""
    emu.load_state((CK / "outdoor_real.state").read_bytes())
    emu.run_frames(30)
    for _ in range(3):
        emu.press(Key.UP, 8)
        emu.run_frames(20)
    emu.press(Key.A, 8)
    emu.run_frames(60)
    for _ in range(3):
        emu.press(Key.UP, 8)
        emu.run_frames(20)
    emu.press(Key.A, 8)
    emu.run_frames(60)
    emu.press(Key.A, 8)
    emu.run_frames(150)
    return ex.extract(emu)


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


def any_move():
    for d in ["UP", "DOWN", "LEFT", "RIGHT"]:
        moved, end = can_move(d)
        if moved:
            return d, end
    return None, None


reset_to_porch()
rep("门洞态")
print(f"  dialog_open: {ctrl.dialog_open()}")

OPS = []
for d in ["UP", "DOWN", "LEFT", "RIGHT"]:
    OPS.append((f"面向{d}按A长按40帧", [(d, 4), ("A", 40)]))
for d in ["UP", "DOWN", "LEFT", "RIGHT"]:
    OPS.append((f"面向{d}按B长按40帧", [(d, 4), ("B", 40)]))
OPS += [
    ("连按A×5(间隔60帧)", [("A", 8)] * 5),
    ("A长按60帧", [("A", 60)]),
    ("B长按60帧", [("B", 60)]),
    ("A+B同时", [("AB", 40)]),
    ("START开菜单", [("START", 8)]),
    ("A+方向键同时(UP)", [("AU", 40)]),
]

for name, seq in OPS:
    reset_to_porch()
    p0 = ex.extract(emu)
    for k, f in seq:
        if k == "A":
            emu.press(Key.A, f)
        elif k == "B":
            emu.press(Key.B, f)
        elif k == "START":
            emu.press(Key.START, f)
        elif k == "AB":
            emu.press_hold(Key.A)
            emu.press_hold(Key.B)
            emu.run_frames(f)
            emu.release()
        elif k == "AU":
            emu.press_hold(Key.A)
            emu.press_hold(Key.UP)
            emu.run_frames(f)
            emu.release()
        elif k in DIR_KEY:
            emu.press(DIR_KEY[k], f)
        emu.run_frames(10)
    emu.run_frames(250)
    st = ex.extract(emu)
    b = float(emu.screenshot().mean())
    d, end = any_move()
    tag = ""
    if d:
        tag = f"🎉 可动！{d} → {end}"
    elif b > 130:
        tag = f"🎉 户外！bright={b:.0f}"
    else:
        tag = "无变化"
    print(f"  {name}: pos=({st.player_x},{st.player_y}) bright={b:.0f} {tag}")
    if d or b > 130:
        print(f"🎉🎉 解锁成功！({name})")
        Path(CK / "outdoor_real.state").write_bytes(emu.save_state())
        print("已保存 outdoor_real.state（解锁）")
        sys.exit(0)

print("\n全部操作无效，仍未解锁")
