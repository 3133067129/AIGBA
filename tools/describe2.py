"""未白镇场景定位：4 方向截图 LLM 找建筑/门/NPC。"""
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
from src.perception.llm_vision import make_provider

cfg = yaml.safe_load(open(ROOT / "config" / "settings.yaml", encoding="utf-8"))
emu = Emulator(rom_path=ROOT / cfg["rom"]["path"])
ex = GameStateExtractor()
vision = make_provider(cfg["llm"])
F = 0x03000F2C
DIR_KEY = {"UP": Key.UP, "DOWN": Key.DOWN, "LEFT": Key.LEFT, "RIGHT": Key.RIGHT}

emu.load_state((ROOT / "data/checkpoints/outdoor_real.state").read_bytes())
emu.run_frames(30)
emu.write(F, b"\x00")
emu.run_frames(10)
st = ex.extract(emu)
print(f"位置: ({st.player_x},{st.player_y}) bright={emu.screenshot().mean():.0f}")

# 当前朝向画面
img = emu.screenshot()
Image.fromarray(img).save(ROOT / "data/tmp_dumps/town_dir0.png")
desc = vision.describe([img],
                       "这是宝可梦绿宝石小镇画面。描述：1)建筑在哪（左/右/上/下、远近）"
                       "2)建筑的门朝向 3)有没有 NPC/人物 4)周围地形（草地/树/路）。")
print(f"当前: {desc[:400]}")

# 每方向看一眼
for i, d in enumerate(["UP", "DOWN", "LEFT", "RIGHT"]):
    emu.press(DIR_KEY[d], 3)
    emu.run_frames(6)
    img2 = emu.screenshot()
    Image.fromarray(img2).save(ROOT / f"data/tmp_dumps/town_dir{d}.png")
    desc2 = vision.describe(
        [img2],
        f"宝可梦小镇，面向{d}。有什么？建筑/门/NPC/路？简短。")
    print(f"--- 面向{d}: {desc2[:250]}")
