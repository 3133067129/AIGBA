"""出门第 4 轮：LEFT warp → 转场 → 妈妈对话（锁移动！）→ 推进对话 → 走出去。

关键认知（2026-08-06）：
- (7,7) 面 LEFT warp = 出门门洞转场，目的地门口格 (120,128)
- 转场后触发妈妈对话（对话中四方向全墙 = 被锁）
- 对话打字中按 A 不翻页 → 必须先等文字区域稳定再按 A
- 对话结束后走出门廊（bright > 130 = 户外未白镇）
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
emu.load_state((ROOT / "data/checkpoints/outside_room.state").read_bytes())
emu.run_frames(30)

explorer = DfsExplorer(emu, ex, ctrl, outdoor_bright=130, unlock_dialog=False)
DIR_KEY = {"UP": Key.UP, "DOWN": Key.DOWN, "LEFT": Key.LEFT, "RIGHT": Key.RIGHT}


def rep(tag):
    st = ex.extract(emu)
    print(f"{tag}: pos=({st.player_x},{st.player_y}) "
          f"grid=({st.player_x//16},{st.player_y//16}) bright={emu.screenshot().mean():.0f}")


def dialog_open():
    return ctrl.dialog_open()


def stable_text(frames=30):
    """文字区域是否稳定（打字完成）。"""
    tr = emu.screenshot()[96:158, 8:232]
    h1 = hashlib.sha256(tr.tobytes()).hexdigest()
    for _ in range(frames):
        emu.run_frames(5)
        tr2 = emu.screenshot()[96:158, 8:232]
        if hashlib.sha256(tr2.tobytes()).hexdigest() == h1:
            return True
    return False


def push_dialog(max_pages=8):
    """推进对话（等稳定→A）。返回推进页数。"""
    pages = 0
    for _ in range(max_pages):
        if not dialog_open():
            break
        if not stable_text():
            continue
        h = hashlib.sha256(emu.screenshot().tobytes()).hexdigest()[:6]
        emu.press(Key.A, 8)
        emu.run_frames(80)
        h2 = hashlib.sha256(emu.screenshot().tobytes()).hexdigest()[:6]
        pages += 1
        print(f"    A×{pages}（画面{'变化' if h2 != h else '不变'}）")
        if h2 == h:
            break
    return pages


def hold_dir(d, frames=90):
    st = ex.extract(emu)
    g0 = (st.player_x // 16, st.player_y // 16)
    emu.press_hold(DIR_KEY[d])
    changed = False
    for _ in range(frames):
        emu.run_frames(1)
        st = ex.extract(emu)
        if (st.player_x // 16, st.player_y // 16) != g0:
            changed = True
    emu.release()
    emu.run_frames(20)
    st = ex.extract(emu)
    return changed, (st.player_x, st.player_y)


# ---- 1. 走到门口 + warp ----
PATH = [("RIGHT", (8, 13)), ("UP", (8, 12)), ("UP", (8, 11)), ("UP", (8, 10)),
        ("UP", (8, 9)), ("UP", (8, 8)), ("LEFT", (7, 8)), ("UP", (7, 7))]
for d, expect in PATH:
    ng = explorer.move_one(d)
    if ng != expect:
        print(f"  ⚠ 导航失败: {d} → {ng} != {expect}")
        sys.exit(1)
rep("门口前")
explorer.move_one("LEFT")
print("  LEFT warp 触发")

# ---- 2. 转场完成（不按键）----
emu.run_frames(240)
rep("转场后")
print(f"  对话框: {dialog_open()}")

# ---- 3. 推进妈妈对话 ----
pages = push_dialog(8)
print(f"  对话推进 {pages} 页")
rep("对话后")

# ---- 4. 走出去 ----
solved = False
for d in ["DOWN", "UP", "LEFT", "RIGHT"]:
    moved, end = hold_dir(d)
    b = float(emu.screenshot().mean())
    print(f"  {d} 90帧: moved={moved} end={end} bright={b:.0f}")
    if moved:
        for step in range(12):
            moved2, end2 = hold_dir(d, 60)
            b2 = float(emu.screenshot().mean())
            if b2 > 130:
                print(f"🎉🎉🎉 出门成功！{d}方向 bright={b2:.0f} pos={end2}")
                Path(ROOT / "data/checkpoints/outdoor_real.state").write_bytes(
                    emu.save_state())
                print("已保存 outdoor_real.state")
                solved = True
                break
            if not moved2:
                break
        if solved:
            break
        # 换方向前重置
        emu.load_state((ROOT / "data/checkpoints/outside_room.state").read_bytes())
        emu.run_frames(30)
        for dd, _ in PATH:
            explorer.move_one(dd)
        explorer.move_one("LEFT")
        emu.run_frames(240)
        push_dialog(8)

if not solved:
    print("\n仍未出门")
    rep("end")
