"""锁性质测试：从未白镇锁态瞬移回家地图可动区 → 检测可动性。"""
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
CK = ROOT / "data" / "checkpoints"
PX, PY = 0x02020650, 0x02020652
DIR_KEY = {"UP": Key.UP, "DOWN": Key.DOWN, "LEFT": Key.LEFT, "RIGHT": Key.RIGHT}


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


def probe(tx, ty, tag):
    emu.write(PX, (tx).to_bytes(2, "little"))
    emu.write(PY, (ty).to_bytes(2, "little"))
    emu.run_frames(25)
    st = ex.extract(emu)
    b = float(emu.screenshot().mean())
    ok = False
    for d in ["UP", "DOWN", "LEFT", "RIGHT"]:
        moved, end = can_move(d, 40)
        if moved:
            print(f"  🎉 {tag} ({tx},{ty}): bright={b:.0f} 可动！{d}→{end}")
            return True
    print(f"  {tag} ({tx},{ty}): bright={b:.0f} 锁")
    return False


# 从未白镇锁态开始
emu.load_state((CK / "outdoor_real.state").read_bytes())
emu.run_frames(30)
st = ex.extract(emu)
print(f"起点(未白镇): ({st.player_x},{st.player_y}) bright={emu.screenshot().mean():.0f}")

# 瞬移回家地图可动区
probe(152, 112, "家2F东侧")
probe(120, 208, "1F入口")
probe(152, 96, "2F餐厅")
probe(120, 128, "门洞格(走路可达)")
