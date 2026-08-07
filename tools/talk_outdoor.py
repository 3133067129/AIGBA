"""未白镇找 NPC 对话：qwen 定位 NPC → 面向对话 → 推进 → 解锁测试。"""
from __future__ import annotations

import hashlib
import sys
import time
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
from src.perception.llm_vision import make_provider

cfg = yaml.safe_load(open(ROOT / "config" / "settings.yaml", encoding="utf-8"))
emu = Emulator(rom_path=ROOT / cfg["rom"]["path"])
ex = GameStateExtractor()
ctrl = Controller(emu, ex)
vision = make_provider(cfg["llm"])
F = 0x03000F2C
CK = ROOT / "data" / "checkpoints"
DIR_KEY = {"UP": Key.UP, "DOWN": Key.DOWN, "LEFT": Key.LEFT, "RIGHT": Key.RIGHT}


def stable_text(frames=30):
    tr = emu.screenshot()[96:158, 8:232]
    h1 = hashlib.sha256(tr.tobytes()).hexdigest()
    for _ in range(frames):
        emu.run_frames(5)
        if hashlib.sha256(emu.screenshot()[96:158, 8:232].tobytes()).hexdigest() == h1:
            return True
    return False


def push_dialog(max_pages=12):
    pages = 0
    for _ in range(max_pages):
        if not ctrl.dialog_open():
            break
        if not stable_text():
            continue
        h = hashlib.sha256(emu.screenshot().tobytes()).hexdigest()[:6]
        emu.press(Key.A, 8)
        emu.run_frames(80)
        h2 = hashlib.sha256(emu.screenshot().tobytes()).hexdigest()[:6]
        pages += 1
        if h2 == h:
            break
    return pages


def mv_test():
    st0 = ex.extract(emu)
    p0 = (st0.player_x, st0.player_y)
    emu.press_hold(Key.UP)
    ok = False
    for _ in range(60):
        emu.run_frames(1)
        st = ex.extract(emu)
        if st.player_y < p0[1] - 10 and abs(st.player_x - p0[0]) < 8:
            ok = True
            break
    emu.release()
    emu.run_frames(10)
    return ok


emu.load_state((CK / "outdoor_real.state").read_bytes())
emu.run_frames(30)
emu.write(F, b"\x00")
emu.run_frames(10)
st = ex.extract(emu)
print(f"位置: ({st.player_x},{st.player_y}) bright={emu.screenshot().mean():.0f}")

# 4 方向截图 qwen 找 NPC
for i, d in enumerate(["UP", "DOWN", "LEFT", "RIGHT"]):
    emu.press(DIR_KEY[d], 3)
    emu.run_frames(6)
    img = emu.screenshot()
    Image.fromarray(img).save(ROOT / f"data/tmp_dumps/npc_{d}.png")
    try:
        desc = vision.describe(
            [img],
            f"宝可梦小镇画面面向{d}。有没有人物（NPC）？在画面什么位置（左/右/中/远/近）？"
            "有没有门？简短。")
        print(f"面向{d}: {desc[:200]}")
    except Exception as e:
        print(f"面向{d}: LLM 失败 {str(e)[:80]}")
    emu.press(DIR_KEY[{"UP": "DOWN", "DOWN": "UP", "LEFT": "RIGHT", "RIGHT": "LEFT"}[d]], 3)
    emu.run_frames(6)
