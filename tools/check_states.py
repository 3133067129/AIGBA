"""检查已有 savestate：恢复后读取位置/亮度，判断各存档场景。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import yaml

from src.emulator.mgba_core import Emulator
from src.state.extractor import GameStateExtractor

cfg = yaml.safe_load(open(ROOT / "config" / "settings.yaml", encoding="utf-8"))
emu = Emulator(rom_path=ROOT / cfg["rom"]["path"])
ex = GameStateExtractor()

for f in sorted((ROOT / "data" / "checkpoints").glob("*.state")):
    try:
        emu.load_state(f.read_bytes())
    except Exception as e:
        print(f"{f.name}: 加载失败 {e}")
        continue
    emu.run_frames(30)
    st = ex.extract(emu)
    b0 = float(emu.screenshot().mean())
    emu.run_frames(30)
    b1 = float(emu.screenshot().mean())
    st2 = ex.extract(emu)
    anim = "动画中" if abs(b0 - b1) > 2 else "静止"
    print(f"{f.name}: pos=({st.player_x},{st.player_y})→({st2.player_x},{st2.player_y}) "
          f"bright={b0:.0f}→{b1:.0f} {anim} map={st.map_key}")
