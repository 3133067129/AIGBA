"""扫描内存找 gMapHeader（当前地图 MapHeader 指针）并读出 warp 表。

零售版 gMapHeader=0x03003B28 在 hack 中无效 → 扫描全内存找
ROM 指针 (0x08xxxxxx)，验证 MapHeader 结构（layout/events 双 ROM 指针 +
width/height 合理 + warpCount<=16），打印 warp 表（出口格 + 目标）。

对三个状态分别执行：2F / 1F / 门口态 (120,128)。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import yaml

from src.emulator.mgba_core import Emulator

cfg = yaml.safe_load(open(ROOT / "config" / "settings.yaml", encoding="utf-8"))
CK = ROOT / "data" / "checkpoints"

ROM_MIN, ROM_MAX = 0x08000000, 0x0A000000


def scan_rom_ptrs(emu, addr_min, size):
    data = np.frombuffer(emu.read(addr_min, size), dtype=np.uint32)
    mask = (data >= ROM_MIN) & (data <= ROM_MAX)
    return [int(addr_min + i * 4) for i in np.nonzero(mask)[0]]


def u16(emu, a):
    return int.from_bytes(emu.read(a, 2), "little")


def is_mapheader(emu, ptr):
    """验证 ptr 指向 MapHeader：layout/events 是 ROM 指针且结构合理。"""
    try:
        layout = emu.u32(ptr + 0)
        events = emu.u32(ptr + 4)
        if not (ROM_MIN <= layout <= ROM_MAX):
            return None
        if not (ROM_MIN <= events <= ROM_MAX):
            return None
        w = u16(emu, layout + 4)
        h = u16(emu, layout + 6)
        if not (1 <= w <= 64) or not (1 <= h <= 64):
            return None
        mapdata = emu.u32(layout + 0)
        if not (ROM_MIN <= mapdata <= ROM_MAX):
            return None
        obj_count = emu.u8(events + 0)
        warp_count = emu.u8(events + 1)
        if not (0 <= obj_count <= 32) or not (0 <= warp_count <= 16):
            return None
        return {
            "layout": layout, "events": events,
            "width": w, "height": h,
            "mapdata": mapdata,
            "obj_count": obj_count, "warp_count": warp_count,
            "warps_ptr": emu.u32(events + 0x0C),
        }
    except Exception:
        return None


def analyze(emu, tag):
    print(f"\n===== {tag} =====")
    # 扫 IWRAM + EWRAM
    cands_iw = scan_rom_ptrs(emu, 0x03000000, 0x8000)
    cands_ew = scan_rom_ptrs(emu, 0x02000000, 0x40000)
    hits = []
    for p in cands_iw + cands_ew:
        info = is_mapheader(emu, p)
        if info:
            hits.append((p, info))
    print(f"ROM 指针候选: IWRAM={len(cands_iw)} EWRAM={len(cands_ew)} → MapHeader 命中 {len(hits)}")
    for p, info in hits[:6]:
        print(f"  gMapHeader 候选 @0x{p:08X}: {info['width']}x{info['height']} "
              f"obj={info['obj_count']} warp={info['warp_count']} "
              f"layout=0x{info['layout']:08X} events=0x{info['events']:08X}")
        # warp 表
        if info["warp_count"] > 0:
            wptr = info["warps_ptr"]
            for i in range(info["warp_count"]):
                x = emu.read(wptr + i * 8, 8)
                wx, wy = int.from_bytes(x[0:2], "little", signed=True), \
                         int.from_bytes(x[2:4], "little", signed=True)
                elev, wid, mg, mn = x[4], x[5], x[6], x[7]
                print(f"    warp[{i}]: ({wx},{wy}) elev={elev} id={wid} → 地图({mg},{mn})")
    return hits


emu = Emulator(rom_path=ROOT / cfg["rom"]["path"])

# 状态 1：2F
emu.load_state((CK / "after_intro_fixed.state").read_bytes())
emu.run_frames(30)
analyze(emu, "2F (after_intro_fixed)")

# 状态 2：1F
emu.load_state((CK / "outside_room.state").read_bytes())
emu.run_frames(30)
analyze(emu, "1F (outside_room)")

# 状态 3：门口态 (120,128)——需要走 PATH + LEFT warp
from src.state.extractor import GameStateExtractor
from src.control.controller import Controller
from src.control.dfs import DfsExplorer
ex = GameStateExtractor()
ctrl = Controller(emu, ex)
explorer = DfsExplorer(emu, ex, ctrl, outdoor_bright=130, unlock_dialog=False)
PATH = [("RIGHT", (8, 13)), ("UP", (8, 12)), ("UP", (8, 11)), ("UP", (8, 10)),
        ("UP", (8, 9)), ("UP", (8, 8)), ("LEFT", (7, 8)), ("UP", (7, 7))]
for d, _ in PATH:
    if explorer.move_one(d) is None:
        print("  ⚠ 导航失败")
        break
explorer.move_one("LEFT")
emu.run_frames(240)
st = ex.extract(emu)
print(f"\n门口态: pos=({st.player_x},{st.player_y}) bright={emu.screenshot().mean():.0f}")
analyze(emu, "门口态 (120,128)")
