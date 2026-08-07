"""带预览窗的人工接管模式：加载当前状态，用户可直接键盘操控。

用法：
    view_play.py [state_name] [speed]
默认加载 outdoor_real.state（未白镇户外）。可用 after_intro_fixed（家 2F 可动）。

按键：方向键/A/B = 人工接管；+/- 调速；p 暂停；ESC 退出。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import yaml

from src.emulator.mgba_core import Emulator
from src.emulator.preview import PreviewWindow

cfg = yaml.safe_load(open(ROOT / "config" / "settings.yaml", encoding="utf-8"))
CK = ROOT / "data" / "checkpoints"

state = sys.argv[1] if len(sys.argv) > 1 else "outdoor_real.state"
speed = float(sys.argv[2]) if len(sys.argv) > 2 else 2.0

emu = Emulator(rom_path=ROOT / cfg["rom"]["path"])
emu.load_state((CK / state).read_bytes())
emu.run_frames(60)

from src.state.extractor import GameStateExtractor
ex = GameStateExtractor()
st = ex.extract(emu)
print(f"加载 {state}: pos=({st.player_x},{st.player_y}) "
      f"bright={emu.screenshot().mean():.0f}")
print("窗口内：方向键/A/B 人工接管 | +/- 调速 | p 暂停 | ESC 退出")

win = PreviewWindow(scale=4, speed=speed, emu=emu,
                    title=f"AIGBA - {state}")
# 人工接管按键也推进帧（KEYDOWN 后模拟器按键已 hold，主循环继续跑帧）
emu.on_frame = lambda e: win.push(e.screenshot())
while not win.abort_requested():
    emu.run_frames(1)
win.close()
print("预览窗已关闭")
