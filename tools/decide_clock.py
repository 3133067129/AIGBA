"""调钟界面慢速探索：每次按键后 LLM 读界面文字，找出正确调钟序列。

起点：outdoor_real.state（恢复后 (120,80) 调钟界面开着，bright 150）。
"""
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
DIR_KEY = {"UP": Key.UP, "DOWN": Key.DOWN, "LEFT": Key.LEFT, "RIGHT": Key.RIGHT}

emu.load_state((ROOT / "data/checkpoints/outdoor_real.state").read_bytes())
emu.run_frames(30)

shot_n = [0]


def read_screen(tag):
    shot_n[0] += 1
    img = emu.screenshot()
    Image.fromarray(img).save(ROOT / f"data/tmp_dumps/clock_{shot_n[0]}_{tag}.png")
    st = ex.extract(emu)
    b = float(img.mean())
    desc = vision.describe(
        [img],
        "这是宝可梦游戏界面。逐字列出画面中所有文字（包括数字、选项、标题）。"
        "这是时间设置界面吗？当前显示什么？")
    print(f"--- [{tag}] pos=({st.player_x},{st.player_y}) bright={b:.0f}")
    print(f"    LLM: {desc[:400]}")
    return desc


read_screen("初始")

# 逐个按键探测（每步后读界面）
import time
seq = [
    ("UP", Key.UP, 8),
    ("DOWN", Key.DOWN, 8),
    ("A", Key.A, 8),
    ("B", Key.B, 8),
    ("LEFT", Key.LEFT, 8),
    ("RIGHT", Key.RIGHT, 8),
]
for name, key, frames in seq:
    emu.press(key, frames)
    emu.run_frames(120)
    read_screen(name)
