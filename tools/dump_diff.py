"""内存 diff：家地图（可控）vs 未白镇（锁态）——找地图 id / 碰撞指针差异。"""
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
emu = Emulator(rom_path=ROOT / cfg["rom"]["path"])
CK = ROOT / "data" / "checkpoints"
DUMP = ROOT / "data" / "tmp_dumps"


def dump_state(name, fname):
    emu.load_state((CK / name).read_bytes())
    emu.run_frames(30)
    data = emu.read(0x02000000, 0x40000) + emu.read(0x03000000, 0x8000)
    (DUMP / fname).write_bytes(data)
    return data


print("dump 家地图(可控)...")
house = dump_state("after_intro_fixed.state", "mem_house.bin")
print("dump 未白镇(锁态)...")
town = dump_state("outdoor_real.state", "mem_town.bin")

# diff
diffs = [i for i in range(len(house)) if house[i] != town[i]]
print(f"总差异字节: {len(diffs)}")

# 找 u32 指针差异（ROM 指针 = 地图数据指针）
import struct

ptr_diffs = []
for i in range(0, len(house) - 4, 4):
    if house[i:i+4] != town[i:i+4]:
        h = struct.unpack_from("<I", house, i)[0]
        t = struct.unpack_from("<I", town, i)[0]
        if (0x08000000 <= h <= 0x0A000000) or (0x08000000 <= t <= 0x0A000000):
            ptr_diffs.append((i, hex(h), hex(t)))
print(f"ROM 指针差异: {len(ptr_diffs)}")
for i, h, t in ptr_diffs[:40]:
    print(f"  0x{i:08X}: 家={h} 未白镇={t}")

# 找值差异小的 u8（可能标志位）
small = [(i, house[i], town[i]) for i in diffs if house[i] < 30 and town[i] < 30]
print(f"\n小值差异 (0-29): {len(small)}")
for i, h, t in small[:60]:
    print(f"  0x{i:08X}: {h} → {t}")
