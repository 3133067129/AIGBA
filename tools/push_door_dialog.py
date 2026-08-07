"""到 (120,144) 触发对话框 → 推进对话 → 检测出门。

流程：2F (152,96) → (120,128) 门洞格 → 面向 DOWN 按 A → (120,144) 对话框
→ push_dialog（等稳定→A）→ 检测可动/出门。
"""
from __future__ import annotations

import hashlib
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


def stable_text(frames=30):
    tr = emu.screenshot()[96:158, 8:232]
    h1 = hashlib.sha256(tr.tobytes()).hexdigest()
    for _ in range(frames):
        emu.run_frames(5)
        if hashlib.sha256(emu.screenshot()[96:158, 8:232].tobytes()).hexdigest() == h1:
            return True
    return False


def push_dialog(max_pages=10):
    pages = 0
    for _ in range(max_pages):
        if not ctrl.dialog_open():
            break
        if not stable_text():
            continue
        h = hashlib.sha256(emu.screenshot().tobytes()).hexdigest()[:6]
        emu.press(Key.A, 8)
        emu.run_frames(80)
        h2 = hashlib.sha256(emu.screenshot().tobytes()).hexdigest()[:6]
        pages += 1
        print(f"  A×{pages}（{'变化' if h2 != h else '不变'}）")
        if h2 == h:
            break
    return pages


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


emu.load_state((CK / "after_intro_fixed.state").read_bytes())
emu.run_frames(30)
nav_to((7, 8))
rep("门洞格")

# 面向 DOWN 按 A → (120,144) 对话框
emu.press(Key.DOWN, 4)
emu.run_frames(10)
emu.press(Key.A, 10)
emu.run_frames(150)
rep("(120,144)")
print(f"  dialog: {ctrl.dialog_open()}")

# LLM 读对话内容
from src.perception.llm_vision import make_provider
vision = make_provider(cfg["llm"])
desc = vision.describe([emu.screenshot()], "逐字列出画面中所有文字。")
print(f"  LLM: {desc[:300]}")

# 推进对话
pages = push_dialog(10)
print(f"  对话推进 {pages} 页")
rep("对话后")
print(f"  dialog: {ctrl.dialog_open()}")

# 四方向检测
for d in ["UP", "DOWN", "LEFT", "RIGHT"]:
    st0 = ex.extract(emu)
    p0 = (st0.player_x, st0.player_y)
    emu.press_hold(DIR_KEY[d])
    moved = False
    for _ in range(90):
        emu.run_frames(1)
        st = ex.extract(emu)
        if (st.player_x, st.player_y) != p0:
            moved = True
            break
    emu.release()
    emu.run_frames(20)
    st = ex.extract(emu)
    b = float(emu.screenshot().mean())
    print(f"  {d}: moved={moved} →({st.player_x},{st.player_y}) bright={b:.0f}")
    if b > 130:
        print(f"🎉🎉🎉 出门！！")
        Path(CK / "outdoor_real.state").write_bytes(emu.save_state())
        print("已保存 outdoor_real.state")
        sys.exit(0)
    if moved:
        # 继续走该方向
        for step in range(10):
            st0 = ex.extract(emu)
            p0 = (st0.player_x, st0.player_y)
            emu.press_hold(DIR_KEY[d])
            moved2 = False
            for _ in range(60):
                emu.run_frames(1)
                st = ex.extract(emu)
                if (st.player_x, st.player_y) != p0:
                    moved2 = True
                    break
            emu.release()
            emu.run_frames(15)
            st = ex.extract(emu)
            b2 = float(emu.screenshot().mean())
            print(f"    步{step+1}: →({st.player_x},{st.player_y}) bright={b2:.0f}")
            if b2 > 130:
                print(f"🎉🎉🎉 出门！！{d}方向")
                Path(CK / "outdoor_real.state").write_bytes(emu.save_state())
                print("已保存 outdoor_real.state")
                sys.exit(0)
            if not moved2:
                break

print("\n完成")
