"""(120,144) 对话穷举：4方向×A / B / 组合，检测对话关闭或出门。"""
from __future__ import annotations

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
from src.control.dfs import DfsExplorer

cfg = yaml.safe_load(open(ROOT / "config" / "settings.yaml", encoding="utf-8"))
emu = Emulator(rom_path=ROOT / cfg["rom"]["path"])
ex = GameStateExtractor()
ctrl = Controller(emu, ex)
CK = ROOT / "data" / "checkpoints"
DIR_KEY = {"UP": Key.UP, "DOWN": Key.DOWN, "LEFT": Key.LEFT, "RIGHT": Key.RIGHT}


def rep(tag):
    st = ex.extract(emu)
    print(f"{tag}: pos=({st.player_x},{st.player_y}) "
          f"grid=({st.player_x//16},{st.player_y//16}) bright={emu.screenshot().mean():.0f}")


def nav_to(grid_target):
    explorer = DfsExplorer(emu, ex, ctrl, outdoor_bright=130, unlock_dialog=False)
    visited = {explorer._grid()}
    stack = []
    g = explorer._grid()
    facing = "UP"
    BACK = {"UP": "DOWN", "DOWN": "UP", "LEFT": "RIGHT", "RIGHT": "LEFT"}
    for _ in range(200):
        if g == grid_target:
            return True
        right = {"UP": "RIGHT", "RIGHT": "DOWN", "DOWN": "LEFT", "LEFT": "UP"}[facing]
        left = {"UP": "LEFT", "LEFT": "DOWN", "DOWN": "RIGHT", "RIGHT": "UP"}[facing]
        moved = False
        for d in [right, facing, left, BACK[facing]]:
            ng = explorer.move_one(d)
            if ng is None:
                continue
            if ng in visited:
                explorer.move_one(BACK[d])
                continue
            facing = d
            visited.add(ng)
            stack.append((g, d))
            g = ng
            moved = True
            break
        if moved:
            continue
        if not stack:
            return False
        prev, came = stack.pop()
        explorer.move_one(BACK[came])
        g = prev
    return False


def reset_to_144():
    """恢复到 (120,144) 对话态。"""
    emu.load_state((CK / "after_intro_fixed.state").read_bytes())
    emu.run_frames(30)
    nav_to((7, 8))
    emu.press(Key.DOWN, 4)
    emu.run_frames(10)
    emu.press(Key.A, 10)
    emu.run_frames(150)


OPS = [
    ("A", [(Key.A, 8)]),
    ("B", [(Key.B, 8)]),
    ("UP+A", [(Key.UP, 4), (Key.A, 8)]),
    ("DOWN+A", [(Key.DOWN, 4), (Key.A, 8)]),
    ("LEFT+A", [(Key.LEFT, 4), (Key.A, 8)]),
    ("RIGHT+A", [(Key.RIGHT, 4), (Key.A, 8)]),
    ("START", [(Key.START, 8)]),
    ("A×5连点", [(Key.A, 8)] * 5),
    ("B×3", [(Key.B, 8)] * 3),
    ("A+B", [(Key.A, 8), (Key.B, 8)]),
    ("UP长按20+A", [(Key.UP, 20), (Key.A, 8)]),
    ("DOWN长按20+A", [(Key.DOWN, 20), (Key.A, 8)]),
]

for name, seq in OPS:
    reset_to_144()
    for k, f in seq:
        emu.press(k, f)
        emu.run_frames(15)
    emu.run_frames(300)
    st = ex.extract(emu)
    d1 = ctrl.dialog_open()
    b = float(emu.screenshot().mean())
    moved = (st.player_x, st.player_y) != (120, 144)
    tag = ""
    if b > 130:
        tag = "🎉 出门！"
    elif not d1 and not moved:
        tag = "对话关闭"
    elif moved:
        tag = f"⚠ 移动 →({st.player_x},{st.player_y})"
    else:
        tag = f"对话仍在 dialog={d1}"
    print(f"  {name}: bright={b:.0f} {tag}")
    if b > 130:
        print("🎉🎉🎉 出门成功！")
        Path(CK / "outdoor_real.state").write_bytes(emu.save_state())
        print("已保存 outdoor_real.state")
        sys.exit(0)

print("\n完成")
