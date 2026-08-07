"""到 (19,10) 枢纽格 → 等转场完成 → 检测位置/可动 → 完整探索。"""
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


def can_move(d, frames=60):
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
    emu.run_frames(15)
    st = ex.extract(emu)
    return moved, (st.player_x, st.player_y)


# 1. 从 (96,112) 可动点出发，DFS 到 (6,1)
emu.load_state((CK / "outdoor_real.state").read_bytes())
emu.run_frames(30)
explorer = DfsExplorer(emu, ex, ctrl, outdoor_bright=130, unlock_dialog=False)
# 已知路径：RIGHT(7,6)→DOWN(7,7)→LEFT(6,7)→LEFT(5,7)→UP(5,6)→UP(5,5)→RIGHT(6,5)→RIGHT(7,5)→UP(7,4)→UP(7,3)→UP(7,2)→LEFT(6,2)→UP(6,1)
PATH = [("RIGHT", (7, 6)), ("DOWN", (7, 7)), ("LEFT", (6, 7)), ("LEFT", (5, 7)),
        ("UP", (5, 6)), ("UP", (5, 5)), ("RIGHT", (6, 5)), ("RIGHT", (7, 5)),
        ("UP", (7, 4)), ("UP", (7, 3)), ("UP", (7, 2)), ("LEFT", (6, 2)),
        ("UP", (6, 1))]
for d, expect in PATH:
    ng = explorer.move_one(d)
    if ng != expect:
        print(f"⚠ 导航失败 {d} → {ng} != {expect}")
        sys.exit(1)
rep("(6,1) 门前")

# 2. RIGHT warp 到 (19,10)
ng = explorer.move_one("RIGHT")
print(f"RIGHT → {ng}")
rep("warp 后")

# 3. 等转场完成
for i in range(10):
    emu.run_frames(60)
    st = ex.extract(emu)
    print(f"+{(i+1)*60}帧: ({st.player_x},{st.player_y}) bright={emu.screenshot().mean():.0f} "
          f"dialog={ctrl.dialog_open()}")
rep("转场完")

# 4. 可动检测
for d in ["UP", "DOWN", "LEFT", "RIGHT"]:
    moved, end = can_move(d, 80)
    b = float(emu.screenshot().mean())
    print(f"  {d}: moved={moved} → {end} bright={b:.0f}")
    if moved:
        print(f"🎉 {d} 可动！")
        Path(CK / "outdoor_real.state").write_bytes(emu.save_state())
        print("已保存 outdoor_real.state")
        # 全图探索
        explorer2 = DfsExplorer(emu, ex, ctrl, outdoor_bright=130, unlock_dialog=False,
                                on_step=lambda t: print(f"  {t}"))
        r = explorer2.run(max_steps=3000)
        print("探索 RESULT:", r)
        sys.exit(0)
print("仍锁")
