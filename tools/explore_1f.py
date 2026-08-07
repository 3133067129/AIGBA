"""逐步探索 1F：打印 DFS 每一步，追踪 (19,10) 与 UP 偏移机制，检测户外。"""
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
emu.load_state((ROOT / "data/checkpoints/outside_room.state").read_bytes())
emu.run_frames(30)


def rep(tag):
    st = ex.extract(emu)
    print(f"{tag}: pos=({st.player_x},{st.player_y}) grid=({st.player_x//16},{st.player_y//16}) "
          f"bright={emu.screenshot().mean():.0f}")


rep("起点")
explorer = DfsExplorer(emu, ex, ctrl, outdoor_bright=130, unlock_dialog=False,
                       on_step=lambda t: print(f"  {t}"))
result = explorer.run(max_steps=300)
print("RESULT:", result)
