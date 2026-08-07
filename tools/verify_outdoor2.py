"""户外验证第 2 轮：检测对话框（妈妈）→ 推进 → 若仍锁死则多点瞬移找可动格。"""
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

cfg = yaml.safe_load(open(ROOT / "config" / "settings.yaml", encoding="utf-8"))
emu = Emulator(rom_path=ROOT / cfg["rom"]["path"])
ex = GameStateExtractor()
ctrl = Controller(emu, ex)
PX, PY = 0x02020650, 0x02020652
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
        if h2 == h:
            break
    return pages


def can_move(d, frames=90):
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
    emu.run_frames(20)
    st = ex.extract(emu)
    return moved, (st.player_x, st.player_y)


def test_point(tx, ty, tag):
    emu.write(PX, (tx).to_bytes(2, "little"))
    emu.write(PY, (ty).to_bytes(2, "little"))
    emu.run_frames(30)
    st = ex.extract(emu)
    b = float(emu.screenshot().mean())
    dlg = ctrl.dialog_open()
    result = f"  {tag} ({tx},{ty}): pos=({st.player_x},{st.player_y}) bright={b:.0f} dialog={dlg}"
    print(result, flush=True)
    if dlg:
        p = push_dialog(10)
        print(f"    对话推进{p}页")
        emu.run_frames(60)
        dlg2 = ctrl.dialog_open()
        b2 = float(emu.screenshot().mean())
        print(f"    推进后: dialog={dlg2} bright={b2:.0f}")
    for d in ["DOWN", "LEFT", "RIGHT", "UP"]:
        moved, end = can_move(d)
        if moved:
            print(f"    🎉 可动！{d} → {end} bright={emu.screenshot().mean():.0f}")
            return True, (tx, ty), end
    return False, (tx, ty), None


# 1. 恢复 + 对话框检测
emu.load_state((ROOT / "data/checkpoints/outdoor_real.state").read_bytes())
emu.run_frames(30)
rep("恢复")
print(f"  对话框: {ctrl.dialog_open()}")
dlg = ctrl.dialog_open()
if dlg:
    p = push_dialog(10)
    print(f"  推进对话 {p} 页")
    emu.run_frames(60)
    rep("推进后")
    for d in ["DOWN", "UP", "LEFT", "RIGHT"]:
        moved, end = can_move(d)
        print(f"  {d}: moved={moved} end={end} bright={emu.screenshot().mean():.0f}")
        if moved:
            Path(ROOT / "data/checkpoints/outdoor_real.state").write_bytes(emu.save_state())
            print("🎉 可动！已重存 outdoor_real.state")
            sys.exit(0)

# 2. 多点瞬移探测（门口外扩散）
print("\n=== 多点瞬移探测 ===")
POINTS = [
    (120, 176), (120, 192), (120, 208), (120, 224),
    (136, 176), (152, 176), (168, 176),
    (104, 176), (88, 176),
    (120, 160),  # 原位
    (136, 160), (152, 160), (168, 160), (184, 160), (200, 160),
    (104, 160), (88, 160), (72, 160),
    (120, 144), (136, 144), (152, 144), (104, 144), (88, 144),
]
for i, (tx, ty) in enumerate(POINTS):
    ok, _, end = test_point(tx, ty, f"[{i}]")
    if ok:
        print(f"\n🎉🎉 找到可动格 ({tx},{ty}) → 移动后 {end}")
        Path(ROOT / "data/checkpoints/outdoor_real.state").write_bytes(emu.save_state())
        print("已重存 outdoor_real.state")
        break
else:
    print("\n全部点都锁死！")
