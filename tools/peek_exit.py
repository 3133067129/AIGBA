"""走到 (19,10) 门口格：截图看场景 + 4 朝向穷举 {方向键, A, B}。"""
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
emu.load_state((ROOT / "data/checkpoints/outside_room.state").read_bytes())
emu.run_frames(30)

explorer = DfsExplorer(emu, ex, ctrl, outdoor_bright=130, unlock_dialog=False)

# 已知路径到 (7,7)：(7,13)→R→(8,13)→U→(8,12)→U→(8,11)→U→(8,10)→U→(8,9)→U→(8,8)→L→(7,8)→U→(7,7)
PATH = [("RIGHT", (8, 13)), ("UP", (8, 12)), ("UP", (8, 11)), ("UP", (8, 10)),
        ("UP", (8, 9)), ("UP", (8, 8)), ("LEFT", (7, 8)), ("UP", (7, 7))]
for d, expect in PATH:
    ng = explorer.move_one(d)
    assert ng == expect, f"导航失败: {d} → {ng} != {expect}"
    print(f"  →({ng[0]},{ng[1]}) bright={emu.screenshot().mean():.0f}")

# warp 出门
ng = explorer.move_one("LEFT")
print(f"  →LEFT → ({ng[0]},{ng[1]}) bright={emu.screenshot().mean():.0f}")

st = ex.extract(emu)
print(f"门口格: pos=({st.player_x},{st.player_y}) bright={emu.screenshot().mean():.0f}")
img = emu.screenshot()
Path(ROOT / "data/tmp_dumps/exit_room.png").write_bytes(
    np.asarray(img, dtype=np.uint8).tobytes()
)
# 存 PNG（用 PIL）
from PIL import Image
Image.fromarray(img).save(ROOT / "data/tmp_dumps/exit_room.png")
print("已保存 exit_room.png")

# 4 朝向穷举
DIR_KEY = {"UP": Key.UP, "DOWN": Key.DOWN, "LEFT": Key.LEFT, "RIGHT": Key.RIGHT}
BACK = {"UP": "DOWN", "DOWN": "UP", "LEFT": "RIGHT", "RIGHT": "LEFT"}
OUTDOOR = 130

for d in ["UP", "DOWN", "LEFT", "RIGHT"]:
    for act in ["方向键", "A", "B"]:
        # 恢复门口格（重置干净）
        emu.load_state((ROOT / "data/checkpoints/outside_room.state").read_bytes())
        emu.run_frames(30)
        for dd, _ in PATH:
            explorer.move_one(dd)
        explorer.move_one("LEFT")  # 回门口格 (19,10)
        p0 = ex.extract(emu)
        b0 = float(emu.screenshot().mean())
        # 转身
        emu.press(DIR_KEY[d], 4)
        emu.run_frames(8)
        key = DIR_KEY[d] if act == "方向键" else (Key.A if act == "A" else Key.B)
        emu.press(key, 8)
        emu.run_frames(150)
        p1 = ex.extract(emu)
        b1 = float(emu.screenshot().mean())
        moved = (p1.player_x, p1.player_y) != (p0.player_x, p0.player_y)
        tag = ""
        if b1 > OUTDOOR:
            tag = "🎉 出门！"
        elif moved:
            tag = f"⚠ 移动 →({p1.player_x},{p1.player_y})"
        print(f"  门口格 面向{d} 按{act}: bright {b0:.0f}→{b1:.0f} {tag}")
        if b1 > OUTDOOR:
            Path(ROOT / "data/checkpoints/outdoor_real.state").write_bytes(emu.save_state())
            print("🎉🎉 已保存 outdoor_real.state")
            sys.exit(0)

print("\n完成（未出门）")
