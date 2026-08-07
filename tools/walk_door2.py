"""走路进门洞 → 等动画完成 → 出门！

流程：2F (152,96) → 走到 (120,112) → 面向 DOWN 走进门洞 (120,128)（bright 70→120）
→ 不按键等动画（最长 5000 帧）→ 检测出门。
"""
from __future__ import annotations

import sys
import time
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


emu.load_state((CK / "after_intro_fixed.state").read_bytes())
emu.run_frames(30)
rep("起点(2F)")

# 导航到 (7,7) = (120,112)
explorer = DfsExplorer(emu, ex, ctrl, outdoor_bright=130, unlock_dialog=False)
target = (7, 7)
visited = {explorer._grid()}
stack = []
g = explorer._grid()
facing = "UP"
BACK = {"UP": "DOWN", "DOWN": "UP", "LEFT": "RIGHT", "RIGHT": "LEFT"}
found = False
for steps in range(200):
    if g == target:
        found = True
        break
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
        break
    prev, came = stack.pop()
    explorer.move_one(BACK[came])
    g = prev

print(f"到 (7,7): {found}")
rep("门上方")

# 面向 DOWN 走进门洞
emu.press(Key.DOWN, 4)
emu.run_frames(10)
emu.press(Key.DOWN, 10)
emu.run_frames(100)
rep("进门洞")

# 等动画（不按键）
t0 = time.time()
for i in range(100):  # 100 × 50 = 5000 帧
    emu.run_frames(50)
    if i % 10 == 0:
        st = ex.extract(emu)
        b = float(emu.screenshot().mean())
        print(f"+{(i+1)*50}帧 ({time.time()-t0:.0f}s): ({st.player_x},{st.player_y}) "
              f"bright={b:.0f} dialog={ctrl.dialog_open()}")
        if b > 130:
            print(f"🎉🎉🎉 出门！！bright={b:.0f}")
            Path(CK / "outdoor_real.state").write_bytes(emu.save_state())
            print("已保存 outdoor_real.state")
            sys.exit(0)

rep("等待后")
# 锁死状态下穷举 A/B/方向键
for name, keys in [
    ("A 长按 40", [(Key.A, 40)]),
    ("B 长按 40", [(Key.B, 40)]),
    ("A×5 连点", [(Key.A, 8)] * 5),
    ("DOWN 长按 90", [(Key.DOWN, 90)]),
    ("UP 长按 90", [(Key.UP, 90)]),
]:
    for k in keys:
        emu.press(k, 8) if k is not None else None
        if isinstance(k, tuple):
            emu.press(k[0], k[1])
        emu.run_frames(15)
    emu.run_frames(250)
    st = ex.extract(emu)
    b = float(emu.screenshot().mean())
    print(f"  {name}: ({st.player_x},{st.player_y}) bright={b:.0f}")
    if b > 130:
        print(f"🎉🎉🎉 出门！！{name}")
        Path(CK / "outdoor_real.state").write_bytes(emu.save_state())
        sys.exit(0)
print("完成")
