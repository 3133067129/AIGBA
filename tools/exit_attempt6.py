"""出门第 6 轮：
A) 瞬移到开局户外点 (152,92)（记忆：A×6 后到门口 bright 146 户外可动）
B) 瞬移回 1F (7,7) 重新触发完整 LEFT warp → 检测转场后是否可动
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
from src.control.dfs import DfsExplorer

cfg = yaml.safe_load(open(ROOT / "config" / "settings.yaml", encoding="utf-8"))
emu = Emulator(rom_path=ROOT / cfg["rom"]["path"])
ex = GameStateExtractor()
ctrl = Controller(emu, ex)
PX, PY = 0x02020650, 0x02020652
DIR_KEY = {"UP": Key.UP, "DOWN": Key.DOWN, "LEFT": Key.LEFT, "RIGHT": Key.RIGHT}


def rep(tag):
    st = ex.extract(emu)
    print(f"{tag}: pos=({st.player_x},{st.player_y}) "
          f"grid=({st.player_x//16},{st.player_y//16}) bright={emu.screenshot().mean():.0f}")


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


def teleport(tx, ty):
    emu.write(PX, (tx).to_bytes(2, "little"))
    emu.write(PY, (ty).to_bytes(2, "little"))
    emu.run_frames(30)
    st = ex.extract(emu)
    return (st.player_x, st.player_y), float(emu.screenshot().mean())


def probe_point(tx, ty, tag):
    p, b = teleport(tx, ty)
    print(f"  {tag} ({tx},{ty}): pos={p} bright={b:.0f} dialog={ctrl.dialog_open()}")
    for d in ["DOWN", "UP", "LEFT", "RIGHT"]:
        moved, end = can_move(d)
        if moved:
            print(f"    🎉 可动！{d} → {end} bright={emu.screenshot().mean():.0f}")
            return True
    return False


# ===== A. 开局户外点 =====
print("=== A. 瞬移开局户外点 ===")
emu.load_state((ROOT / "data/checkpoints/outside_room.state").read_bytes())
emu.run_frames(30)
for i, (tx, ty) in enumerate([(152, 92), (152, 76), (136, 92), (168, 92),
                              (152, 108), (120, 92), (184, 92)]):
    if probe_point(tx, ty, f"[A{i}]"):
        print("🎉🎉 户外可动！")
        Path(ROOT / "data/checkpoints/outdoor_real.state").write_bytes(emu.save_state())
        print("已保存 outdoor_real.state")
        sys.exit(0)

# ===== B. 瞬移回 1F 重走 warp =====
print("\n=== B. 瞬移回 1F (7,7) 重新触发 warp ===")
explorer = DfsExplorer(emu, ex, ctrl, outdoor_bright=130, unlock_dialog=False)
# 先回到 1F 可动态
emu.load_state((ROOT / "data/checkpoints/outside_room.state").read_bytes())
emu.run_frames(30)
# 瞬移到 (7,7) 格中心 (120,120)？——格 (7,7) = x112-127, y112-127，中心 (120,120)
p, b = teleport(120, 120)
print(f"  瞬移到 (120,120): pos={p} bright={b:.0f}")
for d in ["UP", "DOWN", "LEFT", "RIGHT"]:
    moved, end = can_move(d)
    print(f"  {d}: moved={moved} end={end}")
# 面向 LEFT 触发 warp（不依赖移动）
emu.press(Key.LEFT, 4)
emu.run_frames(10)
emu.press(Key.LEFT, 10)
emu.run_frames(300)
rep("warp 后")
# 转场完成后再等 200 帧
emu.run_frames(200)
rep("+200帧后")
for d in ["DOWN", "UP", "LEFT", "RIGHT"]:
    moved, end = can_move(d)
    print(f"  {d}: moved={moved} end={end} bright={emu.screenshot().mean():.0f}")
    if moved:
        print("🎉🎉 重新 warp 后可动！")
        Path(ROOT / "data/checkpoints/outdoor_real.state").write_bytes(emu.save_state())
        sys.exit(0)

print("\n仍未解锁")
