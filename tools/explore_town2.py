"""after_intro → 推进妈妈对话 → 玩家可控户外 (152,92) → 保存 → DFS 探索未白镇。"""
from __future__ import annotations

import hashlib
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


def stable_text(frames=30):
    tr = emu.screenshot()[96:158, 8:232]
    h1 = hashlib.sha256(tr.tobytes()).hexdigest()
    for _ in range(frames):
        emu.run_frames(5)
        if hashlib.sha256(emu.screenshot()[96:158, 8:232].tobytes()).hexdigest() == h1:
            return True
    return False


def push_dialog(max_pages=12):
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


def player_controllable():
    s0 = emu.screenshot()
    emu.run_frames(30)
    s1 = emu.screenshot()
    if float((s0 != s1).mean()) > 0.02:
        return False
    s0 = emu.screenshot()
    emu.press_hold(Key.RIGHT)
    emu.run_frames(30)
    emu.release()
    emu.run_frames(10)
    s1 = emu.screenshot()
    return float((s0 != s1).mean()) > 0.05


emu.load_state((CK / "after_intro.state").read_bytes())
rep("恢复")

# 等淡入 + 推进对话（最长 3 分钟）
t0 = time.time()
while time.time() - t0 < 180:
    if ctrl.dialog_open():
        p = push_dialog(4)
        print(f"  对话推进 {p} 页")
    if player_controllable():
        print(f"🎉 玩家可控（{time.time()-t0:.0f}s）")
        break
    emu.run_frames(120)
rep("可控后")

# 可动验证
moved_any = False
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
    print(f"  {d}: moved={moved} →({st.player_x},{st.player_y}) "
          f"bright={emu.screenshot().mean():.0f}")
    moved_any = moved_any or moved

if moved_any:
    Path(CK / "outdoor_real.state").write_bytes(emu.save_state())
    print("✅ 已保存 outdoor_real.state（未白镇户外可动）")
    # DFS 探索
    print("\nDFS 探索未白镇:")
    explorer = DfsExplorer(emu, ex, ctrl, outdoor_bright=130, unlock_dialog=False,
                           on_step=lambda t: print(f"  {t}"))
    result = explorer.run(max_steps=2000)
    print("RESULT:", result)
else:
    print("✗ 未可控")
