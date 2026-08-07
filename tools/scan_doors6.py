"""门扫描 v6：写一次 0 + door_drop=50（防 warp 门打断 DFS）+ 纯 DFS 收集。"""
from __future__ import annotations

import json
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

emu.load_state((CK / "outdoor_real.state").read_bytes())
emu.run_frames(30)
emu.write(F, b"\x00")
emu.run_frames(10)
st = ex.extract(emu)
print(f"起点: ({st.player_x},{st.player_y}) bright={emu.screenshot().mean():.0f}")

# door_drop=50：移动后亮度骤降>50 = 进门（回家 warp）→ 走回视为撞墙
explorer = DfsExplorer(emu, ex, ctrl, outdoor_bright=999, unlock_dialog=False,
                       door_drop=50)
visited = {explorer._grid()}
stack = []
g = explorer._grid()
facing = "UP"
walls = {}
parent = {}
DOORS = []  # (grid, dir) = 亮度骤降的 warp 门
for steps in range(3000):
    right = {"UP": "RIGHT", "RIGHT": "DOWN", "DOWN": "LEFT", "LEFT": "UP"}[facing]
    left = {"UP": "LEFT", "LEFT": "DOWN", "DOWN": "RIGHT", "RIGHT": "UP"}[facing]
    moved = False
    for d in [right, facing, left, BACK[facing]]:
        ng = explorer.move_one(d)
        if ng is None:
            # 可能是真墙或 door_drop 触发（warp 门）
            if explorer.last_door_drop == d:
                print(f"  🚪 warp门: 格{g} 面向{d}")
                DOORS.append((g, d))
            walls.setdefault(g, set()).add(d)
            continue
        if ng in visited:
            explorer.move_one(BACK[d])
            continue
        facing = d
        visited.add(ng)
        parent[ng] = (g, d)
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

print(f"全图 {len(visited)} 格, warp门 {DOORS}")
if len(visited) < 60:
    print("⚠ 全图太小")
    sys.exit(1)

map_data = {
    "start": [st.player_x, st.player_y],
    "visited": sorted(visited),
    "walls": {f"{k[0]},{k[1]}": sorted(v) for k, v in walls.items()},
    "parent": {f"{k[0]},{k[1]}": (list(v[0]), v[1]) for k, v in parent.items()},
    "doors": [[list(g), d] for g, d in DOORS],
}
(ROOT / "data/tmp_dumps/town_map.json").write_text(json.dumps(map_data), encoding="utf-8")
print("已保存 town_map.json")

# 候选：墙方向（非 warp 门）+ warp 门本身（面向它按 A = 进门！）
cands = []
for g, ws in walls.items():
    for d in ws:
        cands.append((g, d))
print(f"候选（墙向）{len(cands)} 个（含 {len(DOORS)} 个 warp 门）")

# ---- 逐个独立测试 ----
print("\n=== 候选测试 ===")


def path_to(tgt):
    p = []
    cur = tgt
    while cur in parent:
        pcur, d = parent[cur]
        p.append(d)
        cur = pcur
    return list(reversed(p))


FOUND = []
for i, (g0, d) in enumerate(cands):
    emu.load_state((CK / "outdoor_real.state").read_bytes())
    emu.run_frames(30)
    emu.write(F, b"\x00")
    emu.run_frames(10)
    explorer_n = DfsExplorer(emu, ex, ctrl, outdoor_bright=999,
                             unlock_dialog=False, door_drop=50)
    seq = path_to(g0)
    ok = True
    for dd in seq:
        if explorer_n.move_one(dd) is None:
            ok = False
            break
    if not ok:
        continue
    # 面向 d 按 A（d 是墙或 warp 门方向）
    p_pre = ex.extract(emu)
    emu.press(DIR_KEY[d], 3)
    emu.run_frames(5)
    p_mid = ex.extract(emu)
    if abs(p_mid.player_x - p_pre.player_x) > 3 or abs(p_mid.player_y - p_pre.player_y) > 3:
        continue  # 可走（非墙）
    emu.press(Key.A, 8)
    emu.run_frames(130)
    p1 = ex.extract(emu)
    b1 = float(emu.screenshot().mean())
    dlg = ctrl.dialog_open()
    moved = abs(p1.player_x - p_pre.player_x) > 8 or abs(p1.player_y - p_pre.player_y) > 8
    if moved or dlg:
        print(f"  🎯 格{g0} 面向{d}: →({p1.player_x},{p1.player_y}) "
              f"bright={b1:.0f} dialog={dlg}")
        FOUND.append((g0, d, (p1.player_x, p1.player_y), dlg))
        if dlg:
            from src.perception.llm_vision import make_provider
            vision = make_provider(cfg["llm"])
            desc = vision.describe([emu.screenshot()],
                                   "逐字列出画面中对话框内所有文字。")
            print(f"    对话: {desc[:300]}")
            Path(CK / "outdoor_real.state").write_bytes(emu.save_state())
            print("    已保存状态")
            sys.exit(0)
    if i % 25 == 0:
        print(f"  已测 {i}/{len(cands)}")

print(f"\n完成: 发现 {FOUND}")
