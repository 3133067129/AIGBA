"""修复版 DFS 完整探索 2F（after_intro_fixed (152,96)）：找隐藏格/出口。"""
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
from src.control.controller import Controller
from src.control.dfs import DfsExplorer

cfg = yaml.safe_load(open(ROOT / "config" / "settings.yaml", encoding="utf-8"))
emu = Emulator(rom_path=ROOT / cfg["rom"]["path"])
ex = GameStateExtractor()
ctrl = Controller(emu, ex)
CK = ROOT / "data" / "checkpoints"

emu.load_state((CK / "after_intro_fixed.state").read_bytes())
emu.run_frames(30)
st = ex.extract(emu)
print(f"起点: ({st.player_x},{st.player_y}) bright={emu.screenshot().mean():.0f}")

explorer = DfsExplorer(emu, ex, ctrl, outdoor_bright=130, unlock_dialog=False,
                       on_step=lambda t: print(f"  {t}"))
result = explorer.run(max_steps=3000)
print("RESULT:", result)

if result.get("outdoor"):
    st = ex.extract(emu)
    print(f"🎉 户外！({st.player_x},{st.player_y}) bright={emu.screenshot().mean():.0f}")
    Path(CK / "outdoor_real.state").write_bytes(emu.save_state())
    print("已保存 outdoor_real.state")
