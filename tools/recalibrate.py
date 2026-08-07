"""未白镇场景重新标定玩家坐标偏移（动作→内存 diff）。"""
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

cfg = yaml.safe_load(open(ROOT / "config" / "settings.yaml", encoding="utf-8"))
emu = Emulator(rom_path=ROOT / cfg["rom"]["path"])
ex = GameStateExtractor()
F = 0x03000F2C

emu.load_state((ROOT / "data/checkpoints/outdoor_real.state").read_bytes())
emu.run_frames(30)
emu.write(F, b"\x00")
emu.run_frames(10)
st = ex.extract(emu)
print(f"起点: ({st.player_x},{st.player_y}) bright={emu.screenshot().mean():.0f}")

# dump 玩家对象区域（EWRAM 全范围太大——先搜"坐标值"）
# 找当前 (x,y) 值出现的 u16 位置
x0, y0 = st.player_x, st.player_y


def find_u16_locs(lo, hi, region_start, region_size):
    data = emu.read(region_start, region_size)
    arr = np.frombuffer(data, dtype=np.uint16)
    idx = np.nonzero((arr >= lo) & (arr <= hi))[0]
    return [region_start + int(i) * 2 for i in idx]


# 玩家坐标区域：EWRAM 0x02000000-0x02040000 全扫找 (x0) 和 (y0)
cands_x = find_u16_locs(x0 - 40, x0 + 40, 0x02000000, 0x40000)
cands_y = find_u16_locs(y0 - 40, y0 + 40, 0x02000000, 0x40000)
print(f"x0={x0} 候选 {len(cands_x)} 处; y0={y0} 候选 {len(cands_y)} 处")

# 按 UP 移动（如果可动）→ 找坐标变化的位置
from src.control.controller import Controller
ctrl = Controller(emu, ex)
r = ctrl.move_dir("UP", frames=60)
print(f"UP: moved={r['moved']} →({r['end_pos'][0]},{r['end_pos'][1]})")

x1, y1 = r["end_pos"]
if r["moved"] and (x1 != x0 or y1 != y0):
    # 找 x 变化的位置
    data0 = emu.read(0x02000000, 0x40000)
    # 移动后再读
    # （注意：move_dir 后玩家已在新位置）
    arr0 = np.frombuffer(data0, dtype=np.uint16)
    x_changed = []
    for addr in cands_x:
        if x0 != x1 and arr0[(addr - 0x02000000) // 2] == x1:
            x_changed.append(addr)
    print(f"x 变化位置: {[hex(a) for a in x_changed[:20]]}")
    y_changed = []
    for addr in cands_y:
        if y0 != y1 and arr0[(addr - 0x02000000) // 2] == y1:
            y_changed.append(addr)
    print(f"y 变化位置: {[hex(a) for a in y_changed[:20]]}")
    # 交集（同一地址同时存 x 和 y）
    inter = set(x_changed) & set(y_changed)
    print(f"x&y 交集: {[hex(a) for a in sorted(inter)[:10]]}")
else:
    print("UP 未移动——标定失败")
