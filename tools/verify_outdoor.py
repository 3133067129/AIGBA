"""验证 outdoor_real.state：稳定性 + 可动性 + 场景确认。"""
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

DIR_KEY = {"UP": Key.UP, "DOWN": Key.DOWN, "LEFT": Key.LEFT, "RIGHT": Key.RIGHT}


def rep(tag):
    st = ex.extract(emu)
    print(f"{tag}: pos=({st.player_x},{st.player_y}) "
          f"grid=({st.player_x//16},{st.player_y//16}) bright={emu.screenshot().mean():.0f}")


emu.load_state((ROOT / "data/checkpoints/outdoor_real.state").read_bytes())
emu.run_frames(30)
rep("恢复后")
emu.run_frames(120)
rep("120帧后")

# 四方向移动测试
for d in ["DOWN", "UP", "LEFT", "RIGHT"]:
    st0 = ex.extract(emu)
    p0 = (st0.player_x, st0.player_y)
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
    b = float(emu.screenshot().mean())
    print(f"  {d}: moved={moved} pos=({st.player_x},{st.player_y}) bright={b:.0f}")
    if moved:
        # 走回来继续测其他方向
        emu.press_hold({"UP": DIR_KEY["DOWN"], "DOWN": DIR_KEY["UP"],
                        "LEFT": DIR_KEY["RIGHT"], "RIGHT": DIR_KEY["LEFT"]}[d])
        for _ in range(90):
            emu.run_frames(1)
            st = ex.extract(emu)
            if (st.player_x, st.player_y) == p0:
                break
        emu.release()
        emu.run_frames(20)

# 截图场景确认
rep("最终")
img = emu.screenshot()
Image.fromarray(img).save(ROOT / "data/tmp_dumps/outdoor_confirm.png")
print("已保存 outdoor_confirm.png")

# qwen 描述
from src.perception.llm_vision import make_provider
vision = make_provider(cfg["llm"])
desc = vision.describe([img], "这是宝可梦绿宝石户外场景。描述画面：建筑物、草地、路、NPC？")
print(f"LLM: {desc[:300]}")
