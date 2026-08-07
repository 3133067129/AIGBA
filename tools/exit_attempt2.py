"""从门洞态 (town.state) 走出户外：每方向按住 90 帧检测格变/bright。

理论：town.state 是"进门洞"转场完成态（(120,112) bright 114，未白镇家门口
门廊），出门转场会自动前进到 (120,128)。从门廊按方向键走进未白镇 = 出门完成
（bright > 130）。
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
BACK = {"UP": "DOWN", "DOWN": "UP", "LEFT": "RIGHT", "RIGHT": "LEFT"}


def rep(tag):
    st = ex.extract(emu)
    print(f"{tag}: pos=({st.player_x},{st.player_y}) "
          f"grid=({st.player_x//16},{st.player_y//16}) bright={emu.screenshot().mean():.0f}")


def hold_dir(d, frames=90):
    """按住 d 方向 frames 帧，返回 (格变了吗, 最终格子)。"""
    st = ex.extract(emu)
    g0 = (st.player_x // 16, st.player_y // 16)
    emu.press_hold(DIR_KEY[d])
    changed = False
    for _ in range(frames):
        emu.run_frames(1)
        st = ex.extract(emu)
        g = (st.player_x // 16, st.player_y // 16)
        if g != g0:
            changed = True
    emu.release()
    emu.run_frames(20)
    st = ex.extract(emu)
    return changed, (st.player_x, st.player_y)


emu.load_state((ROOT / "data/checkpoints/town.state").read_bytes())
emu.run_frames(30)
rep("门洞态")

solved = False
for d in ["DOWN", "UP", "LEFT", "RIGHT"]:
    emu.load_state((ROOT / "data/checkpoints/town.state").read_bytes())
    emu.run_frames(30)
    moved, end = hold_dir(d)
    b = float(emu.screenshot().mean())
    print(f"  {d} 90帧: moved={moved} end={end} bright={b:.0f}")
    if b > 130:
        print(f"🎉🎉🎉 出门成功！方向={d}")
        Path(ROOT / "data/checkpoints/outdoor_real.state").write_bytes(emu.save_state())
        print("已保存 outdoor_real.state")
        solved = True
        break
    if moved:
        # 有移动：继续朝该方向走（最多 10 格），检测 bright
        print(f"    {d} 方向可走，继续深入...")
        emu.run_frames(30)
        for step in range(10):
            moved2, end2 = hold_dir(d, 60)
            b2 = float(emu.screenshot().mean())
            print(f"      第{step+1}步: moved={moved2} end={end2} bright={b2:.0f}")
            if b2 > 130:
                print(f"🎉🎉🎉 出门成功！继续{d}方向后 bright={b2:.0f}")
                Path(ROOT / "data/checkpoints/outdoor_real.state").write_bytes(emu.save_state())
                solved = True
                break
            if not moved2:
                break
        if solved:
            break

if not solved:
    print("\n未走出户外。最终状态：")
    rep("end")
    # 截图看看门廊长什么样
    from PIL import Image
    img = emu.screenshot()
    Image.fromarray(img).save(ROOT / "data/tmp_dumps/porch.png")
    print("已保存 porch.png")
