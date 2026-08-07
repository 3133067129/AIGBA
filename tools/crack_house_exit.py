"""破解玩家家一楼出口（第 2 轮）。

第 1 轮失败：warp 表定位失败（零售版 gMapHeader 地址 hack 中无效）；
方向键/A 键在 (104,208) 单点穷举无效。

本脚本策略：
  0. 门洞态破解：town.state (120,112) bright 114 —— 疑似「进门洞」半出门状态，
     若为门洞，补最后一步（UP/A/B/方向键）即可能完全出门
  1. 地图 id 标定：2F / 1F / 门洞态 三份内存快照 diff（值 1↔2 变化的字节）
  2. 1F 全格穷举：每格 4 朝向 × {方向键, A, B}，检测 bright/坐标/地图 id 变化
"""
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

CFG = yaml.safe_load(open(ROOT / "config" / "settings.yaml", encoding="utf-8"))
CK = ROOT / "data" / "checkpoints"
DUMP = ROOT / "data" / "tmp_dumps"

DIR_KEY = {"UP": Key.UP, "DOWN": Key.DOWN, "LEFT": Key.LEFT, "RIGHT": Key.RIGHT}
BACK = {"UP": "DOWN", "DOWN": "UP", "LEFT": "RIGHT", "RIGHT": "LEFT"}

OUTDOOR_BRIGHT = 130  # 已知：室内 44-74 / 门洞 114-120 / 户外 141


def make_emu():
    return Emulator(rom_path=ROOT / CFG["rom"]["path"])


def load(emu, name):
    emu.load_state((CK / name).read_bytes())
    emu.run_frames(30)
    return emu


def dump_mem(emu, name):
    DUMP.mkdir(parents=True, exist_ok=True)
    data = emu.read(0x02000000, 0x40000) + emu.read(0x03000000, 0x8000)
    (DUMP / name).write_bytes(data)
    return len(data)


def pos(emu, ex):
    st = ex.extract(emu)
    return (st.player_x, st.player_y)


def bright(emu):
    return float(emu.screenshot().mean())


# ================= 0. 门洞态破解 =================
print("=== 0. 门洞态破解 (town.state) ===")
emu = make_emu()
ex = GameStateExtractor()
load(emu, "town.state")
print(f"  起点: pos={pos(emu, ex)} bright={bright(emu):.0f}")

ACTIONS = [
    ("UP 长按 30 帧", [(Key.UP, 30)]),
    ("UP 4帧 + A", [(Key.UP, 4), (Key.A, 10)]),
    ("A 长按 30 帧", [(Key.A, 30)]),
    ("B", [(Key.B, 10)]),
    ("DOWN 30 帧", [(Key.DOWN, 30)]),
    ("LEFT 30 帧", [(Key.LEFT, 30)]),
    ("RIGHT 30 帧", [(Key.RIGHT, 30)]),
    ("UP 30帧 + A", [(Key.UP, 30), (Key.A, 10)]),
    ("A + UP 30帧", [(Key.A, 10), (Key.UP, 30)]),
]
solved = False
for name, keys in ACTIONS:
    load(emu, "town.state")  # 每次干净重置到门洞态
    p0 = pos(emu, ex)
    b0 = bright(emu)
    for k, f in keys:
        emu.press(k, f)
        emu.run_frames(10)
    emu.run_frames(150)
    p1 = pos(emu, ex)
    b1 = bright(emu)
    if b1 > OUTDOOR_BRIGHT:
        tag = "🎉 出门！"
        solved = True
    elif p1 != p0:
        tag = f"⚠ 移动 ({p1})"
    else:
        tag = "无变化"
    print(f"  {name}: pos {p0}→{p1} bright {b0:.0f}→{b1:.0f} {tag}")
    if solved:
        Path(CK / "outdoor_real.state").write_bytes(emu.save_state())
        print("🎉🎉 门洞态破解成功，已保存 outdoor_real.state")
        break

# ================= 1. 地图 id 标定 =================
print("\n=== 1. 地图 id 标定（2F / 1F / 门洞态 三份内存 diff）===")
f2 = (DUMP / "after_intro_fixed.state.bin") if (DUMP / "after_intro_fixed.state.bin").exists() else None
f1 = (DUMP / "outside_room.state.bin") if (DUMP / "outside_room.state.bin").exists() else None
ft = (DUMP / "town.state.bin") if (DUMP / "town.state.bin").exists() else None

if f2 is None or f1 is None or ft is None:
    # 先 dump 三份
    for name, tag in [("after_intro_fixed.state", "2F"),
                      ("outside_room.state", "1F"),
                      ("town.state", "门洞态")]:
        load(emu, name)
        n = dump_mem(emu, name + ".bin")
        print(f"  dump {tag} ({name}): {n} 字节 pos={pos(emu, ex)} bright={bright(emu):.0f}")
    f2 = (DUMP / "after_intro_fixed.state.bin").read_bytes()
    f1 = (DUMP / "outside_room.state.bin").read_bytes()
    ft = (DUMP / "town.state.bin").read_bytes()
else:
    f2, f1, ft = f2.read_bytes(), f1.read_bytes(), ft.read_bytes()
    print(f"  使用已有 dump: 2F={len(f2)} 1F={len(f1)} 门洞态={len(ft)}")

# 2F→1F：值 {1,2} 互变的字节 = 地图 num 候选
cands = [i for i in range(min(len(f2), len(f1))) if f2[i] != f1[i]]
mapid_cands = [i for i in cands if {f2[i], f1[i]} <= {1, 2}]
print(f"  2F→1F 总变化字节: {len(cands)}")
for i in mapid_cands[:30]:
    print(f"    addr=0x{i:08X} 2F={f2[i]} 1F={f1[i]} 门洞态={ft[i]}")
if not mapid_cands:
    print("  无 {1,2} 互变候选 → 地图 id 可能不在 num 字节，查看变化分布：")
    from collections import Counter
    pairs = Counter((f2[i], f1[i]) for i in cands)
    for (a, b), n in pairs.most_common(15):
        print(f"    2F={a}→1F={b} ×{n}")

# 门洞态的地图 num（对照：若门洞态=1F 则 num=1）
print(f"  门洞态在候选地址处的值: "
      f"{[(hex(i), ft[i]) for i in mapid_cands[:10]]}")

# ================= 2. 1F 全格穷举 =================
print("\n=== 2. 1F 全格穷举 ===")
emu = make_emu()
ex = GameStateExtractor()
ctrl = Controller(emu, ex)
load(emu, "outside_room.state")

# 2a. DFS 收集 1F 所有可达格
explorer = DfsExplorer(emu, ex, ctrl, outdoor_bright=999, unlock_dialog=False)
visited = {explorer._grid()}
stack = []
g = explorer._grid()
facing = "UP"
all_grids = {g}
print(f"  起点格: {g}")
for steps in range(200):
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
        all_grids.add(ng)
        stack.append((g, d))
        g = ng
        moved = True
        break
    if moved:
        continue
    if not stack:
        break
    prev_g, came = stack.pop()
    explorer.move_one(BACK[came])
    g = prev_g

grids = sorted(all_grids)
print(f"  1F 可达格 ({len(grids)}): {grids}")

# 2b. 每格 4 朝向 × {方向键, A, B} 穷举
# 走廊是一行：按 x 排序导航
grids_x = sorted(grids, key=lambda t: (t[1], t[0]))


def nav_to(tgt):
    """沿已知格序列移动（1F 简单走廊，直接横向 move_one）。"""
    cur = explorer._grid()
    if cur == tgt:
        return
    # 尝试横向移动
    for _ in range(20):
        cur = explorer._grid()
        if cur == tgt:
            return
        if tgt[0] > cur[0]:
            if explorer.move_one("RIGHT") is None:
                break
        elif tgt[0] < cur[0]:
            if explorer.move_one("LEFT") is None:
                break
        elif tgt[1] > cur[1]:
            if explorer.move_one("DOWN") is None:
                break
        elif tgt[1] < cur[1]:
            if explorer.move_one("UP") is None:
                break
        else:
            return


def face(d):
    """转身面向 d（若该方向可走则算移动，返回 moved 标志）。"""
    p0 = pos(emu, ex)
    emu.press(DIR_KEY[d], 4)
    emu.run_frames(8)
    p1 = pos(emu, ex)
    return p1 != p0


def probe(key, wait=130):
    """按 key 并等待，返回 (bright, pos, mapid)。"""
    emu.press(key, 8)
    emu.run_frames(wait)
    return bright(emu), pos(emu, ex), ex.extract(emu).map_key


solved = False
for g0 in grids_x:
    nav_to(g0)
    cur = explorer._grid()
    if cur != g0:
        print(f"  ⚠ 导航失败 {g0}（在 {cur}）")
        continue
    for d in ["UP", "DOWN", "LEFT", "RIGHT"]:
        for act in ["方向键", "A", "B"]:
            # 干净重置到该格？不——直接用当前位置，先转身
            load(emu, "outside_room.state")  # 重置
            nav_to(g0)
            if not face(d):
                pass  # 转身即移动（该方向可走）——方向键测试已隐式完成
            b0 = bright(emu)
            p0 = pos(emu, ex)
            if act == "方向键":
                key = DIR_KEY[d]
            elif act == "A":
                key = Key.A
            else:
                key = Key.B
            b1, p1, mk1 = probe(key)
            moved_px = abs(p1[0] - p0[0]) + abs(p1[1] - p0[1])
            if b1 > OUTDOOR_BRIGHT:
                print(f"  🎉 出口: 格{g0} 面向{d} 按{act} → bright={b1:.0f} pos={p1}")
                solved = True
                Path(CK / "outdoor_real.state").write_bytes(emu.save_state())
                break
            elif moved_px >= 16 or mk1 != "0:0":
                print(f"  ⚠ 移动/warp: 格{g0} 面向{d} 按{act} → pos={p1} "
                      f"bright={b0:.0f}→{b1:.0f} map={mk1}")
                break  # 有反应：换下一格
        if solved:
            break
    if solved:
        break
if not solved:
    print("  1F 全格穷举未找到出口")
    print(f"  最终位置: {pos(emu, ex)} bright={bright(emu):.0f}")
print("\n完成")
