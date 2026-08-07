"""描述当前未白镇场景：找建筑/门/NPC 位置。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import yaml
from PIL import Image

from src.emulator.mgba_core import Emulator
from src.state.extractor import GameStateExtractor
from src.perception.llm_vision import make_provider

cfg = yaml.safe_load(open(ROOT / "config" / "settings.yaml", encoding="utf-8"))
emu = Emulator(rom_path=ROOT / cfg["rom"]["path"])
ex = GameStateExtractor()
vision = make_provider(cfg["llm"])
CK = ROOT / "data" / "checkpoints"

emu.load_state((CK / "outdoor_real.state").read_bytes())
emu.run_frames(30)
st = ex.extract(emu)
print(f"位置: ({st.player_x},{st.player_y}) bright={emu.screenshot().mean():.0f}")

img = emu.screenshot()
Image.fromarray(img).save(ROOT / "data/tmp_dumps/town_now.png")

desc = vision.describe(
    [img],
    "这是宝可梦绿宝石未白镇。详细描述画面：有什么建筑？建筑的门在哪（方向/距离）？"
    "有没有 NPC/人物？有路吗？逐字列出所有文字。")
print(f"LLM: {desc[:500]}")

# 多方向看看
for d in ["UP", "DOWN", "LEFT", "RIGHT"]:
    from src.emulator.keys import Key
    key = {"UP": Key.UP, "DOWN": Key.DOWN, "LEFT": Key.LEFT, "RIGHT": Key.RIGHT}[d]
    emu.press(key, 4)
    emu.run_frames(8)
    img2 = emu.screenshot()
    desc2 = vision.describe(
        [img2],
        f"这是宝可梦绿宝石未白镇，面向{d}方向的画面。有建筑吗？门在哪？有 NPC 吗？简短回答。")
    print(f"--- 面向{d}: {desc2[:200]}")
