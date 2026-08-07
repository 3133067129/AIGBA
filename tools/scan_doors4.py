"""未白镇门扫描 v4（不瞬移）：DFS 全图 + 每格墙向按 A 测门/对话。"""
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
BACK = {"UP": "DOWN", "DOWN": "UP", "LEFT": "RIGHT", "RIGHT": "LEFT"}
F = 0x03000F2C

# 每帧解锁（移动循环内每帧写）
def unlock(e):
    e.write(F, b"\x00")
emu.on_frame = unlock

emu.load_state((CK / "outdoor_real.state").read_bytes())
emu.run_frames(30)
st = ex.extract(emu)
print(f"起点: ({st.player_x},{st.player_y}) bright={emu.screenshot().mean():.0f}")

explorer = DfsExplorer(emu, ex, ctrl, outdoor_bright=999, unlock_dialog=False)
visited = {explorer._grid()}
stack = []
g = explorer._grid()
facing = "UP"
HITS = []

for steps in range(3000):
    # 当前格：测墙方向按 A
    for d in ["UP", "DOWN", "LEFT", "RIGHT"]:
        p_a = ex.extract(emu)
        pa = (p_a.player_x, p_a.player_y)
        emu.press(DIR_KEY[d], 3)
        emu.run_frames(5)
        p_b = ex.extract(emu)
        pb = (p_b.player_x, p_b.player_y)
        if abs(pb[0] - pa[0]) > 3 or abs(pb[1] - pa[1]) > 3:
            # 该方向可走（移动了）→ 走回再继续
            emu.press(DIR_KEY[BACK[d]], 3)
            emu.run_frames(5)
            emu.press(DIR_KEY[BACK[d]], 20)
            emu.run_frames(60)
            emu.write(F, b"\x00")
            continue
        # 面向墙：按 A
        emu.press(Key.A, 8)
        emu.run_frames(120)
        p1 = ex.extract(emu)
        b1 = float(emu.screenshot().mean())
        dlg = ctrl.dialog_open()
        moved = abs(p1.player_x - pa[0]) > 8 or abs(p1.player_y - pa[1]) > 8
        if moved or dlg:
            print(f"  🎯 格{g} 面向{d} 按A: →({p1.player_x},{p1.player_y}) "
                  f"bright={b1:.0f} dialog={dlg}")
            HITS.append((g, d, (p1.player_x, p1.player_y), dlg))
            # 重置回本格（走回或重载）
            if dlg:
                # 对话：推进关闭
                pages = 0
                for _ in range(12):
                    if not ctrl.dialog_open():
                        break
                    tr = emu.screenshot()[96:158, 8:232]
                    h1 = hashlib.sha256(tr.tobytes()).hexdigest()
                    for _ in range(30):
                        emu.run_frames(5)
                        if hashlib.sha256(
                                emu.screenshot()[96:158, 8:232].tobytes()
                        ).hexdigest() == h1:
                            break
                    emu.press(Key.A, 8)
                    emu.run_frames(80)
                    pages += 1
                print(f"    对话推进{pages}页")
                emu.write(F, b"\x00")
            else:
                # 进门了：尝试走回
                emu.press(DIR_KEY[BACK[d]], 4)
                emu.run_frames(6)
                emu.press(DIR_KEY[BACK[d]], 20)
                emu.run_frames(80)
                emu.write(F, b"\x00")
                p2 = ex.extract(emu)
                if abs(p2.player_x // 16 - g[0]) > 2 or abs(p2.player_y // 16 - g[1]) > 2:
                    print(f"    进新区域！({p2.player_x},{p2.player_y}) bright="
                          f"{emu.screenshot().mean():.0f}")
                    Path(CK / "outdoor_real.state").write_bytes(emu.save_state())
                    print("    已保存 outdoor_real.state")
                    sys.exit(0)
    # DFS 前进
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
    if len(visited) % 20 == 0:
        print(f"  visited={len(visited)} hits={len(HITS)}")

print(f"\n扫描完成: visited={len(visited)} hits={HITS}")
