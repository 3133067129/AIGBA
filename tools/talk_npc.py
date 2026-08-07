"""与附近 NPC 对话：4 方向按 A → 检测对话 → 推进 → LLM 读内容。"""
from __future__ import annotations

import hashlib
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
from src.perception.llm_vision import make_provider

cfg = yaml.safe_load(open(ROOT / "config" / "settings.yaml", encoding="utf-8"))
emu = Emulator(rom_path=ROOT / cfg["rom"]["path"])
ex = GameStateExtractor()
ctrl = Controller(emu, ex)
vision = make_provider(cfg["llm"])
F = 0x03000F2C
DIR_KEY = {"UP": Key.UP, "DOWN": Key.DOWN, "LEFT": Key.LEFT, "RIGHT": Key.RIGHT}
CK = ROOT / "data" / "checkpoints"


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


def reset():
    emu.load_state((CK / "outdoor_real.state").read_bytes())
    emu.run_frames(30)
    emu.write(F, b"\x00")
    emu.run_frames(10)
    st = ex.extract(emu)
    return st


for d in ["LEFT", "DOWN", "UP", "RIGHT"]:
    st = reset()
    print(f"\n=== 面向{d} 按 A ===")
    emu.press(DIR_KEY[d], 3)
    emu.run_frames(6)
    emu.press(Key.A, 8)
    emu.run_frames(150)
    dlg = ctrl.dialog_open()
    st2 = ex.extract(emu)
    print(f"  dialog={dlg} pos=({st2.player_x},{st2.player_y}) "
          f"bright={emu.screenshot().mean():.0f}")
    if dlg:
        desc = vision.describe([emu.screenshot()], "逐字列出画面中对话框内所有文字。")
        print(f"  LLM: {desc[:300]}")
        pages = push_dialog(12)
        print(f"  对话推进 {pages} 页")
        desc2 = vision.describe([emu.screenshot()],
                                "对话框还在吗？列出当前文字。有选项吗？")
        print(f"  推进后 LLM: {desc2[:300]}")
        # 继续推进直到关闭
        pages2 = push_dialog(12)
        print(f"  再推进 {pages2} 页")
        st3 = ex.extract(emu)
        print(f"  最终: dialog={ctrl.dialog_open()} pos=({st3.player_x},{st3.player_y})")
        Path(CK / "outdoor_real.state").write_bytes(emu.save_state())
        print("  已保存状态")
        break
