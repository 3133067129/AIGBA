"""门扫描 v5：写一次 0 → 纯 DFS 收集全图+墙 → 每候选门独立重载测试。

教训（2026-08-06）：MOVE_FLAG 写一次 0 = 可动；每帧写 0 = 与游戏逻辑竞争反而锁死。
瞬移也破坏可动。恢复后直接动。
"""
from __future__ import annotations

import hashlib
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

# ---- 1. 纯 DFS 收集（写一次 0）----
emu.load_state((CK / "outdoor_real.state").read_bytes())
emu.run_frames(30)
emu.write(F, b"\x00")
emu.run_frames(10)
st = ex.extract(emu)
print(f"起点: ({st.player_x},{st.player_y}) bright={emu.screenshot().mean():.0f}")

explorer = DfsExplorer(emu, ex, ctrl, outdoor_bright=999, unlock_dialog=False)
visited = {explorer._grid()}
stack = []
g = explorer._grid()
facing = "UP"
walls = {}
parent = {}  # grid -> (parent, dir)
for steps in range(3000):
    right = {"UP": "RIGHT", "RIGHT": "DOWN", "DOWN": "LEFT", "LEFT": "UP"}[facing]
    left = {"UP": "LEFT", "LEFT": "DOWN", "DOWN": "RIGHT", "RIGHT": "UP"}[facing]
    moved = False
    for d in [right, facing, left, BACK[facing]]:
        ng = explorer.move_one(d)
        if ng is None:
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

print(f"全图 {len(visited)} 格, 墙记录 {sum(len(v) for v in walls.values())}")
if len(visited) < 60:
    print("⚠ 全图太小")
    sys.exit(1)

# 保存地图数据
map_data = {"start": list(st.player_x, st.player_y),
            "visited": sorted(visited),
            "walls": {f"{k[0]},{k[1]}": sorted(v) for k, v in walls.items()},
            "parent": {f"{k[0]},{k[1]}": (list(v[0]), v[1]) for k, v in parent.items()}}
(ROOT / "data/tmp_dumps/town_map.json").write_text(json.dumps(map_data), encoding="utf-8")
print("已保存 town_map.json")

# ---- 2. 每候选门独立测试 ----
print("\n=== 候选门测试 ===")
SKIP = {((8, 7), "RIGHT")}
cands = [(g, d) for g, ws in walls.items() for d in ws if (g, d) not in SKIP]
print(f"候选 {len(cands)} 个")

# 路径函数：从 start 到目标格的移动序列（BFS on parent）
def path_to(tgt):
    p = []
    cur = tgt
    while cur in parent:
        pcur, d = parent[cur]
        p.append(d)
        cur = pcur
    return list(reversed(p))


def navigate(seq):
    explorer_n = DfsExplorer(emu, ex, ctrl, outdoor_bright=999, unlock_dialog=False)
    for d in seq:
        if explorer_n.move_one(d) is None:
            return False
    return True


FOUND = []
for i, (g0, d) in enumerate(cands):
    # 重载干净状态
    emu.load_state((CK / "outdoor_real.state").read_bytes())
    emu.run_frames(30)
    emu.write(F, b"\x00")
    emu.run_frames(10)
    seq = path_to(g0)
    if not navigate(seq):
        print(f"  ⚠ 导航失败 {g0}")
        continue
    # 面向 d 按 A
    emu.press(DIR_KEY[d], 3)
    emu.run_frames(5)
    p_pre = ex.extract(emu)
    if abs(p_pre.player_x - (g0[0] * 16 + 8)) > 3 or abs(p_pre.player_y - (g0[1] * 16 + 8)) > 3:
        continue  # 该方向可走（不是墙）
    emu.press(Key.A, 8)
    emu.run_frames(120)
    p1 = ex.extract(emu)
    b1 = float(emu.screenshot().mean())
    dlg = ctrl.dialog_open()
    moved = abs(p1.player_x - (g0[0] * 16 + 8)) > 8 or abs(p1.player_y - (g0[1] * 16 + 8)) > 8
    if moved or dlg:
        print(f"  🎯 格{g0} 面向{d}: →({p1.player_x},{p1.player_y}) "
              f"bright={b1:.0f} dialog={dlg}")
        FOUND.append((g0, d, (p1.player_x, p1.player_y), dlg))
        if dlg:
            # 对话：读内容 + 推进
            from src.perception.llm_vision import make_provider
            vision = make_provider(cfg["llm"])
            desc = vision.describe([emu.screenshot()],
                                   "逐字列出画面中对话框内所有文字。")
            print(f"    对话: {desc[:250]}")
            Path(CK / "outdoor_real.state").write_bytes(emu.save_state())
            sys.exit(0)
    if i % 30 == 0:
        print(f"  已测 {i}/{len(cands)}")

print(f"\n完成: 发现 {FOUND}")
