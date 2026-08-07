"""修复版 DFS 全图探索：从 1F 入口区 vs 从 (152,92) 可动点，找完整可达图 + 出口。"""
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
CK = ROOT / "data" / "checkpoints"


def run_dfs(state_name, tag, max_steps=3000):
    print(f"\n===== {tag}（起点={state_name}）=====")
    emu = Emulator(rom_path=ROOT / cfg["rom"]["path"])
    ex = GameStateExtractor()
    ctrl = Controller(emu, ex)
    emu.load_state((CK / state_name).read_bytes())
    emu.run_frames(30)
    st = ex.extract(emu)
    print(f"起点: ({st.player_x},{st.player_y}) bright={emu.screenshot().mean():.0f}")

    counter = [0]
    def on_step(text):
        counter[0] += 1
        if counter[0] % 25 == 0:
            print(f"  {text}")

    explorer = DfsExplorer(emu, ex, ctrl, outdoor_bright=130, unlock_dialog=True,
                           on_step=on_step)
    result = explorer.run(max_steps=max_steps)
    print("RESULT:", result)
    return result


run_dfs("outside_room.state", "1F 入口区（修复版 DFS）")
run_dfs("outdoor_real.state", "(152,92) 可动点探索")
