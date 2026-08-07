"""解锁户外 (136,112)：穷举按键组合（warp 后锁）。"""
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


def can_move(d, frames=60):
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
    emu.run_frames(15)
    st = ex.extract(emu)
    return moved, (st.player_x, st.player_y)


OPS = [
    ("A长按40", [(Key.A, 40)]),
    ("B长按40", [(Key.B, 40)]),
    ("UP+A", [(Key.UP, 4), (Key.A, 30)]),
    ("DOWN+A", [(Key.DOWN, 4), (Key.A, 30)]),
    ("LEFT+A", [(Key.LEFT, 4), (Key.A, 30)]),
    ("RIGHT+A", [(Key.RIGHT, 4), (Key.A, 30)]),
    ("UP长按60", [(Key.UP, 60)]),
    ("DOWN长按60", [(Key.DOWN, 60)]),
    ("START", [(Key.START, 10)]),
    ("A×5", [(Key.A, 8)] * 5),
    ("B×3+A", [(Key.B, 8)] * 3 + [(Key.A, 30)]),
    ("UP+A+B", [(Key.UP, 10), (Key.A, 10), (Key.B, 10)]),
]

for name, seq in OPS:
    emu.load_state((CK / "outdoor_real.state").read_bytes())
    emu.run_frames(30)
    for k, f in seq:
        emu.press(k, f)
        emu.run_frames(15)
    emu.run_frames(250)
    st = ex.extract(emu)
    b = float(emu.screenshot().mean())
    moved, end = can_move("RIGHT")
    moved2, _ = can_move("UP")
    tag = ""
    if moved or moved2:
        tag = f"🎉 可动！RIGHT→{end}"
    else:
        tag = "锁"
    print(f"  {name}: ({st.player_x},{st.player_y}) bright={b:.0f} {tag}")
    if moved or moved2:
        print(f"🎉🎉🎉 解锁！！{name}")
        Path(CK / "outdoor_real.state").write_bytes(emu.save_state())
        print("已保存 outdoor_real.state（解锁）")
        sys.exit(0)

print("\n未解锁")
