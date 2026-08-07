"""正确调钟：A(确认时间) → A(选"是") → 界面关闭 → 解锁出门！"""
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
from src.perception.llm_vision import make_provider

cfg = yaml.safe_load(open(ROOT / "config" / "settings.yaml", encoding="utf-8"))
emu = Emulator(rom_path=ROOT / cfg["rom"]["path"])
ex = GameStateExtractor()
ctrl = Controller(emu, ex)
vision = make_provider(cfg["llm"])
DIR_KEY = {"UP": Key.UP, "DOWN": Key.DOWN, "LEFT": Key.LEFT, "RIGHT": Key.RIGHT}
CK = ROOT / "data" / "checkpoints"


def rep(tag):
    st = ex.extract(emu)
    print(f"{tag}: pos=({st.player_x},{st.player_y}) "
          f"grid=({st.player_x//16},{st.player_y//16}) bright={emu.screenshot().mean():.0f}")


def read_screen(tag):
    st = ex.extract(emu)
    b = float(emu.screenshot().mean())
    desc = vision.describe([emu.screenshot()],
                           "逐字列出画面所有文字。这是时间设置界面吗？还在吗？")
    print(f"--- [{tag}] pos=({st.player_x},{st.player_y}) bright={b:.0f}")
    print(f"    LLM: {desc[:250]}")
    return desc


def can_move(d, frames=90):
    st0 = ex.extract(emu)
    p0 = (st0.player_x, st0.player_y)
    emu.press_hold(DIR_KEY[d])
    moved = False
    for _ in range(frames):
        emu.run_frames(1)
        st = ex.extract(emu)
        if (st.player_x, st.player_y) != p0:
            moved = True
            break
    emu.release()
    emu.run_frames(20)
    st = ex.extract(emu)
    return moved, (st.player_x, st.player_y)


emu.load_state((CK / "outdoor_real.state").read_bytes())
emu.run_frames(30)
rep("恢复")
read_screen("界面确认")

# A → 是/否
emu.press(Key.A, 8)
emu.run_frames(120)
read_screen("A后")

# A → 选"是"（默认光标）
emu.press(Key.A, 8)
emu.run_frames(200)
read_screen("选是")

# 若界面还在（选了"否"？）→ 试 LEFT/RIGHT 切换 + A
for attempt in range(2):
    st = ex.extract(emu)
    if not ctrl.dialog_open() and float(emu.screenshot().mean()) < 140:
        break
    desc = read_screen(f"重试{attempt}")
    if "正确" in desc or "是" in desc:
        # 是/否界面：先按 LEFT 或 RIGHT 切换选项再 A
        emu.press(Key.LEFT, 8)
        emu.run_frames(60)
        emu.press(Key.A, 8)
        emu.run_frames(200)
        read_screen(f"LEFT+A{attempt}")
        st = ex.extract(emu)
        if not ctrl.dialog_open() and float(emu.screenshot().mean()) < 140:
            break

# 检测解锁
rep("调钟完成")
for d in ["UP", "DOWN", "LEFT", "RIGHT"]:
    moved, end = can_move(d)
    b = float(emu.screenshot().mean())
    print(f"  {d}: moved={moved} → {end} bright={b:.0f}")
    if moved:
        print(f"🎉🎉🎉 解锁成功！{d} 可动")
        Path(CK / "outdoor_real.state").write_bytes(emu.save_state())
        print("已保存 outdoor_real.state（解锁）")
        sys.exit(0)
    if b > 130:
        print(f"🎉 bright={b:.0f}（户外？）")

print("\n仍未解锁")
