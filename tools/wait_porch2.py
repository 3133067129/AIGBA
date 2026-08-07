"""调钟确认（UP+A）→ (88,128) 门洞 → 不按键等出门动画完成 → 检测可动。

若等待无效：瞬移 (88,128) 周围点找可动格。
"""
from __future__ import annotations

import sys
import time
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
PX, PY = 0x02020650, 0x02020652
CK = ROOT / "data" / "checkpoints"


def rep(tag):
    st = ex.extract(emu)
    print(f"{tag}: pos=({st.player_x},{st.player_y}) "
          f"grid=({st.player_x//16},{st.player_y//16}) bright={emu.screenshot().mean():.0f}")


def reset_to_porch88():
    """恢复 → A → UP+A → (88,128) 门洞。"""
    emu.load_state((CK / "outdoor_real.state").read_bytes())
    emu.run_frames(30)
    emu.press(Key.A, 8)
    emu.run_frames(120)
    emu.press(Key.UP, 8)
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


# ===== 1. 等待动画 =====
reset_to_porch88()
rep("门洞 (88,128)")
t0 = time.time()
unlocked = False
for i in range(200):  # 200 × 60 = 12000 帧
    emu.run_frames(60)
    if i % 10 == 0:
        st = ex.extract(emu)
        print(f"+{(i+1)*60}帧 ({time.time()-t0:.0f}s): ({st.player_x},{st.player_y}) "
              f"bright={emu.screenshot().mean():.0f} dialog={ctrl.dialog_open()}")
    if i > 10 and i % 5 == 0:
        for d in ["UP", "DOWN", "LEFT", "RIGHT"]:
            moved, end = can_move(d, 40)
            if moved:
                print(f"🎉🎉🎉 动画完成！{d} 可动 → {end}")
                Path(CK / "outdoor_real.state").write_bytes(emu.save_state())
                print("已保存 outdoor_real.state")
                sys.exit(0)

print("\n等待无效，尝试瞬移周围点")
# ===== 2. 瞬移周围 =====
POINTS = [(88, 112), (88, 144), (104, 128), (72, 128), (88, 128),
          (104, 112), (72, 112), (88, 96), (104, 144), (72, 144),
          (120, 112), (56, 128), (88, 160), (104, 160), (56, 160)]
for tx, ty in POINTS:
    reset_to_porch88()
    emu.write(PX, (tx).to_bytes(2, "little"))
    emu.write(PY, (ty).to_bytes(2, "little"))
    emu.run_frames(30)
    st = ex.extract(emu)
    b = float(emu.screenshot().mean())
    for d in ["UP", "DOWN", "LEFT", "RIGHT"]:
        moved, end = can_move(d, 50)
        if moved:
            print(f"🎉🎉🎉 瞬移 ({tx},{ty}) 可动！{d} → {end} bright={b:.0f}")
            Path(CK / "outdoor_real.state").write_bytes(emu.save_state())
            print("已保存 outdoor_real.state（瞬移可动）")
            sys.exit(0)
    print(f"  ({tx},{ty}): pos={st.player_x},{st.player_y} bright={b:.0f} 锁")

print("\n全部失败")
