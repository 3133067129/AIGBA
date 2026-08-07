"""完整出门尝试：1F → (7,7) → LEFT warp → 转场自然完成 → 走出门廊。

关键：转场期间不按键（town.state 是转场中断卡死态，恢复后全墙）。
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

explorer = DfsExplorer(emu, ex, ctrl, outdoor_bright=130, unlock_dialog=False)
DIR_KEY = {"UP": Key.UP, "DOWN": Key.DOWN, "LEFT": Key.LEFT, "RIGHT": Key.RIGHT}
BACK = {"UP": "DOWN", "DOWN": "UP", "LEFT": "RIGHT", "RIGHT": "LEFT"}


def rep(tag):
    st = ex.extract(emu)
    print(f"{tag}: pos=({st.player_x},{st.player_y}) "
          f"grid=({st.player_x//16},{st.player_y//16}) bright={emu.screenshot().mean():.0f}")


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


PATH = [("RIGHT", (8, 13)), ("UP", (8, 12)), ("UP", (8, 11)), ("UP", (8, 10)),
        ("UP", (8, 9)), ("UP", (8, 8)), ("LEFT", (7, 8)), ("UP", (7, 7))]
for d, expect in PATH:
    ng = explorer.move_one(d)
    print(f"  {d} → {ng} bright={emu.screenshot().mean():.0f}")
    if ng != expect:
        print(f"  ⚠ 导航失败 (期望 {expect})")
        sys.exit(1)

rep("门口前")
ng = explorer.move_one("LEFT")
print(f"  LEFT → {ng}（warp 触发）")

# 转场自然完成（不按键！）
print("转场等待（不按键 240 帧）:")
for i in range(8):
    emu.run_frames(30)
    st = ex.extract(emu)
    print(f"  +{(i+1)*30}帧: pos=({st.player_x},{st.player_y}) "
          f"grid=({st.player_x//16},{st.player_y//16}) bright={emu.screenshot().mean():.0f}")

rep("转场后")
img = emu.screenshot()
from PIL import Image
Image.fromarray(img).save(ROOT / "data/tmp_dumps/porch2.png")
print("已保存 porch2.png")

# 四方向探测
for d in ["DOWN", "UP", "LEFT", "RIGHT"]:
    moved, end = hold_dir(d)
    b = float(emu.screenshot().mean())
    print(f"  {d} 90帧: moved={moved} end={end} bright={b:.0f}")
    if moved:
        print(f"    {d} 可走！继续深入...")
        emu.run_frames(20)
        solved = False
        for step in range(12):
            moved2, end2 = hold_dir(d, 60)
            b2 = float(emu.screenshot().mean())
            print(f"      步{step+1}: moved={moved2} end={end2} bright={b2:.0f}")
            if b2 > 130:
                print(f"🎉🎉🎉 出门成功！bright={b2:.0f} pos={end2}")
                Path(ROOT / "data/checkpoints/outdoor_real.state").write_bytes(emu.save_state())
                solved = True
                break
            if not moved2:
                break
        if solved:
            sys.exit(0)
        # 没出门但能走：继续下一个方向（重置）
        emu.load_state((ROOT / "data/checkpoints/outside_room.state").read_bytes())
        emu.run_frames(30)
        for dd, _ in PATH:
            explorer.move_one(dd)
        explorer.move_one("LEFT")
        emu.run_frames(240)  # 转场完成

print("\n未出门")
rep("end")
