"""从 (152,112) 可控点：确认场景 + RIGHT warp 实验（等转场完）。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import yaml
from PIL import Image

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


emu.load_state((CK / "outdoor_real.state").read_bytes())
emu.run_frames(30)
rep("可控点")
img = emu.screenshot()
Image.fromarray(img).save(ROOT / "data/tmp_dumps/intro_start.png")

# LLM 描述场景
from src.perception.llm_vision import make_provider
vision = make_provider(cfg["llm"])
desc = vision.describe([img], "这是宝可梦画面。室内还是室外？描述场景（床/家具/草/树/路/天空？）逐字列出文字。")
print(f"LLM: {desc[:300]}")

# RIGHT warp 实验
print("\n面向 RIGHT 按方向键:")
emu.press(Key.RIGHT, 4)
emu.run_frames(10)
emu.press(Key.RIGHT, 30)
for i in range(10):
    emu.run_frames(60)
    st = ex.extract(emu)
    b = float(emu.screenshot().mean())
    print(f"  +{(i+1)*60}帧: ({st.player_x},{st.player_y}) bright={b:.0f} dialog={ctrl.dialog_open()}")
    if b > 130:
        print(f"🎉🎉🎉 出门！！bright={b:.0f}")
        Path(CK / "outdoor_real.state").write_bytes(emu.save_state())
        print("已保存 outdoor_real.state")
        sys.exit(0)

rep("RIGHT后")
# 若到了新位置：4 方向测试
for d in ["UP", "DOWN", "LEFT", "RIGHT"]:
    st0 = ex.extract(emu)
    p0 = (st0.player_x, st0.player_y)
    emu.press_hold(DIR_KEY[d])
    moved = False
    for _ in range(90):
        emu.run_frames(1)
        st = ex.extract(emu)
        if (st.player_x, st.player_y) != p0:
            moved = True
            break
    emu.release()
    emu.run_frames(20)
    st = ex.extract(emu)
    b = float(emu.screenshot().mean())
    print(f"  {d}: moved={moved} →({st.player_x},{st.player_y}) bright={b:.0f}")
    if b > 130:
        print(f"🎉🎉🎉 出门！！")
        Path(CK / "outdoor_real.state").write_bytes(emu.save_state())
        sys.exit(0)
print("\n完成")
