"""终极方案：写玩家坐标瞬移出坏门。

流程：1F → (7,7) → LEFT warp → 转场完成（门口态 (120,128) 全墙 = hack 坏门）
→ 直接写玩家坐标到门外格 → 验证可移动 → 走出去。

顺带补测转场完成态的按键穷举（A 长按/B/START/SELECT/L/R/组合）。
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
emu.load_state((ROOT / "data/checkpoints/outside_room.state").read_bytes())
emu.run_frames(30)

PX, PY = 0x02020650, 0x02020652  # 已标定玩家坐标
explorer = DfsExplorer(emu, ex, ctrl, outdoor_bright=130, unlock_dialog=False)
DIR_KEY = {"UP": Key.UP, "DOWN": Key.DOWN, "LEFT": Key.LEFT, "RIGHT": Key.RIGHT}


def rep(tag):
    st = ex.extract(emu)
    print(f"{tag}: pos=({st.player_x},{st.player_y}) "
          f"grid=({st.player_x//16},{st.player_y//16}) bright={emu.screenshot().mean():.0f}")


def goto_door():
    """走到 (7,7) 并触发 LEFT warp，转场完成。"""
    emu.load_state((ROOT / "data/checkpoints/outside_room.state").read_bytes())
    emu.run_frames(30)
    PATH = [("RIGHT", (8, 13)), ("UP", (8, 12)), ("UP", (8, 11)), ("UP", (8, 10)),
            ("UP", (8, 9)), ("UP", (8, 8)), ("LEFT", (7, 8)), ("UP", (7, 7))]
    for d, _ in PATH:
        if explorer.move_one(d) is None:
            return False
    explorer.move_one("LEFT")
    emu.run_frames(240)
    return True


def hold_dir(d, frames=90):
    st = ex.extract(emu)
    g0 = (st.player_x // 16, st.player_y // 16)
    emu.press_hold(DIR_KEY[d])
    changed = False
    for _ in range(frames):
        emu.run_frames(1)
        st = ex.extract(emu)
        if (st.player_x // 16, st.player_y // 16) != g0:
            changed = True
    emu.release()
    emu.run_frames(20)
    st = ex.extract(emu)
    return changed, (st.player_x, st.player_y)


# ===== 1. 按键穷举（转场完成态）=====
print("=== 1. 门口态按键穷举 ===")
if not goto_door():
    print("导航失败")
    sys.exit(1)
rep("门口态")
for name, keys in [
    ("A 长按 40帧", [(Key.A, 40)]),
    ("B 长按 40帧", [(Key.B, 40)]),
    ("START", [(Key.START, 10)]),
    ("SELECT", [(Key.SELECT, 10)]),
    ("L", [(Key.L, 10)]),
    ("R", [(Key.R, 10)]),
    ("A+DOWN 组合", [(Key.A, 8), (Key.DOWN, 30)]),
    ("DOWN 4帧+A 长按", [(Key.DOWN, 4), (Key.A, 40)]),
]:
    goto_door()
    for k, f in keys:
        emu.press(k, f)
        emu.run_frames(10)
    emu.run_frames(180)
    st = ex.extract(emu)
    b = float(emu.screenshot().mean())
    tag = "🎉" if b > 130 else ""
    print(f"  {name}: pos=({st.player_x},{st.player_y}) bright={b:.0f} {tag}")
    if b > 130:
        Path(ROOT / "data/checkpoints/outdoor_real.state").write_bytes(emu.save_state())
        print("🎉🎉 出门成功！已保存 outdoor_real.state")
        sys.exit(0)

# ===== 2. 坐标瞬移 =====
print("\n=== 2. 坐标瞬移 ===")
goto_door()
rep("瞬移前")

# 候选目标：门口下方/下方两格/四角
CANDIDATES = [(120, 144), (120, 160), (136, 144), (104, 144), (120, 176)]
solved = False
for tx, ty in CANDIDATES:
    goto_door()
    emu.write(PX, (tx).to_bytes(2, "little"))
    emu.write(PY, (ty).to_bytes(2, "little"))
    emu.run_frames(30)
    st = ex.extract(emu)
    b0 = float(emu.screenshot().mean())
    print(f"  写坐标 →({tx},{ty}): 读回 ({st.player_x},{st.player_y}) bright={b0:.0f}")
    if (st.player_x, st.player_y) != (tx, ty):
        print("    ⚠ 坐标被引擎修正/撞回")
        continue
    # 验证可移动：按 DOWN 检测
    moved, end = hold_dir("DOWN", 60)
    st = ex.extract(emu)
    b1 = float(emu.screenshot().mean())
    print(f"    DOWN 60帧: moved={moved} end={end} bright={b1:.0f}")
    if b1 > 130:
        print(f"🎉🎉🎉 瞬移出门成功！目标=({tx},{ty}) bright={b1:.0f}")
        Path(ROOT / "data/checkpoints/outdoor_real.state").write_bytes(emu.save_state())
        solved = True
        break
    if moved:
        # 已可动，继续走
        for step in range(10):
            moved2, end2 = hold_dir("DOWN", 60)
            b2 = float(emu.screenshot().mean())
            if b2 > 130:
                print(f"🎉🎉🎉 瞬移后走出！bright={b2:.0f} pos={end2}")
                Path(ROOT / "data/checkpoints/outdoor_real.state").write_bytes(
                    emu.save_state())
                solved = True
                break
            if not moved2:
                break
        if solved:
            break

if not solved:
    print("\n瞬移未出门。最后状态：")
    rep("end")
