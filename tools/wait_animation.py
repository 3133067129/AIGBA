"""触发出门 warp 后不按键等待动画自然完成（最长 5 分钟），观察终点。

关键：中途绝不按键/保存（savestate 打断动画 = 状态不稳定陷阱）。
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

from src.emulator.mgba_core import Emulator
from src.state.extractor import GameStateExtractor
from src.control.controller import Controller
from src.control.dfs import DfsExplorer

cfg = yaml.safe_load(open(ROOT / "config" / "settings.yaml", encoding="utf-8"))
emu = Emulator(rom_path=ROOT / cfg["rom"]["path"])
ex = GameStateExtractor()
ctrl = Controller(emu, ex)
CK = ROOT / "data" / "checkpoints"
DIR_KEY = {"UP": "UP", "DOWN": "DOWN", "LEFT": "LEFT", "RIGHT": "RIGHT"}
from src.emulator.keys import Key

emu.load_state((CK / "outside_room.state").read_bytes())
emu.run_frames(30)

explorer = DfsExplorer(emu, ex, ctrl, outdoor_bright=130, unlock_dialog=False)

# 走到 (7,7)
PATH = [("RIGHT", (8, 13)), ("UP", (8, 12)), ("UP", (8, 11)), ("UP", (8, 10)),
        ("UP", (8, 9)), ("UP", (8, 8)), ("LEFT", (7, 8)), ("UP", (7, 7))]
for d, expect in PATH:
    ng = explorer.move_one(d)
    if ng != expect:
        print(f"⚠ 导航失败 {d} → {ng}")
        sys.exit(1)

st = ex.extract(emu)
print(f"门前: ({st.player_x},{st.player_y}) bright={emu.screenshot().mean():.0f}")

# 触发 RIGHT warp
ng = explorer.move_one("RIGHT")
print(f"RIGHT warp → {ng}")

# 等待动画自然完成（不按键）
t0 = time.time()
last = ""
for i in range(300):  # 300 × 60 帧 = 5 分钟
    emu.run_frames(60)
    st = ex.extract(emu)
    b = float(emu.screenshot().mean())
    line = f"+{(i+1)*60:>5}帧 ({time.time()-t0:.0f}s): pos=({st.player_x},{st.player_y}) " \
           f"grid=({st.player_x//16},{st.player_y//16}) bright={b:.0f} dialog={ctrl.dialog_open()}"
    if line != last or i % 10 == 0:
        print(line)
        last = line
    # 检测解锁（可动）
    if i > 5 and i % 5 == 0:
        moved = False
        for d in ["UP", "DOWN", "LEFT", "RIGHT"]:
            p0 = (st.player_x, st.player_y)
            emu.press_hold(getattr(Key, d))
            for _ in range(20):
                emu.run_frames(1)
                st2 = ex.extract(emu)
                if (st2.player_x, st2.player_y) != p0:
                    moved = True
                    break
            emu.release()
            if moved:
                break
        if moved:
            print(f"🎉🎉🎉 动画完成，玩家可动！({d} → ({st2.player_x},{st2.player_y}))")
            Path(CK / "outdoor_real.state").write_bytes(emu.save_state())
            print("已保存 outdoor_real.state")
            sys.exit(0)

print("\n5 分钟等待结束，仍未解锁")
st = ex.extract(emu)
print(f"最终: ({st.player_x},{st.player_y}) bright={emu.screenshot().mean():.0f}")
