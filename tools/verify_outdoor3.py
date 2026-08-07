"""验证 outdoor_real.state（(304,160) bright=150）：可动性 + 场景。"""
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

cfg = yaml.safe_load(open(ROOT / "config" / "settings.yaml", encoding="utf-8"))
emu = Emulator(rom_path=ROOT / cfg["rom"]["path"])
ex = GameStateExtractor()
DIR_KEY = {"UP": Key.UP, "DOWN": Key.DOWN, "LEFT": Key.LEFT, "RIGHT": Key.RIGHT}

emu.load_state((ROOT / "data/checkpoints/outdoor_real.state").read_bytes())
emu.run_frames(30)
st = ex.extract(emu)
print(f"恢复: pos=({st.player_x},{st.player_y}) bright={emu.screenshot().mean():.0f}")

# 四方向移动
for d in ["UP", "DOWN", "LEFT", "RIGHT"]:
    p0 = (st.player_x, st.player_y)
    emu.press_hold(DIR_KEY[d])
    moved = False
    for _ in range(90):
        emu.run_frames(1)
        st = ex.extract(emu)
        if (st.player_x, st.player_y) != p0:
            moved = True
    emu.release()
    emu.run_frames(20)
    st = ex.extract(emu)
    print(f"  {d}: moved={moved} →({st.player_x},{st.player_y}) "
          f"bright={emu.screenshot().mean():.0f}")
    if moved:
        # 回来
        emu.press_hold({"UP": Key.DOWN, "DOWN": Key.UP,
                        "LEFT": Key.RIGHT, "RIGHT": Key.LEFT}[d])
        for _ in range(90):
            emu.run_frames(1)
            st = ex.extract(emu)
            if (st.player_x, st.player_y) == p0:
                break
        emu.release()
        emu.run_frames(20)

# 场景确认
st = ex.extract(emu)
img = emu.screenshot()
Image.fromarray(img).save(ROOT / "data/tmp_dumps/outdoor3.png")
print(f"最终: ({st.player_x},{st.player_y}) bright={emu.screenshot().mean():.0f}")
from src.perception.llm_vision import make_provider
vision = make_provider(cfg["llm"])
desc = vision.describe([img], "这是宝可梦绿宝石画面。描述场景（户外/室内？建筑/草地/树/路？有无文字？）。")
print(f"LLM: {desc[:300]}")
