"""锁点行为标定：可控态 vs 锁态的「按 UP 前后内存变化」对比。

思路：按 UP 30 帧，对比前后 IWRAM/EWRAM 差异字节集。
- 可控态：差异 = 完整移动链路（坐标/动画/任务状态）
- 锁态：差异 = 输入处理断点（若按键无效，差异应极小而集中在输入缓冲）
两集之差 = 锁点相关字节（可控有而锁态没有的 = 移动链路在锁态缺失/被阻断）。
"""
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

cfg = yaml.safe_load(open(ROOT / "config" / "settings.yaml", encoding="utf-8"))
DEMO_DIR = ROOT / "data" / "demos"
IWRAM = (0x03000000, 0x8000)
EWRAM = (0x02000000, 0x40000)


def load_demo(name):
    return [json.loads(l) for l in open(DEMO_DIR / name, encoding="utf-8")]


def replay_to(emu, events, stop_at=None):
    down: set[str] = set()
    idx = 1
    while idx < len(events):
        ev = events[idx]
        if stop_at is not None and emu.frame_counter >= stop_at:
            return
        if ev["t"] > emu.frame_counter:
            emu.run_frames(1)
            continue
        if ev["ev"] == "keys":
            nd = set(ev["down"])
            if nd != down:
                ks = [Key[n] for n in nd]
                if ks:
                    emu.press_hold(*ks)
                else:
                    emu.release()
                down = nd
        idx += 1


def dump_ewram(emu) -> np.ndarray:
    data = bytearray()
    for off in range(0, EWRAM[1], 0x40000):
        data += emu.read(EWRAM[0] + off, 0x40000)
    return np.frombuffer(bytes(data), dtype=np.uint8)


def probe(emu, tag, events, stop_at):
    """回放到 stop_at → dump → 按 UP 30 帧 → dump → 返回差异集。"""
    replay_to(emu, events, stop_at)
    emu.run_frames(60)  # 稳定帧
    base_i = np.frombuffer(emu.read(IWRAM[0], IWRAM[1]), dtype=np.uint8)
    base_e = dump_ewram(emu)
    emu.press_hold(Key.UP)
    emu.run_frames(30)
    emu.release()
    emu.run_frames(30)
    aft_i = np.frombuffer(emu.read(IWRAM[0], IWRAM[1]), dtype=np.uint8)
    aft_e = dump_ewram(emu)
    diff_i = set(np.nonzero(base_i != aft_i)[0])
    diff_e = set(np.nonzero(base_e != aft_e)[0])
    st = emu.u16(0x02020650), emu.u16(0x02020652)
    print(f"  [{tag}] pos=({st[0]},{st[1]}) 按键前后差异: "
          f"IWRAM {len(diff_i)} 字节, EWRAM {len(diff_e)} 字节")
    return diff_i, diff_e, base_i, aft_i


def show_region(reg_tag, addr, diffs, base, aft, limit=60):
    """打印一个区域内的差异字节。"""
    lo = addr
    hits = [(o, base[o], aft[o]) for o in diffs if lo <= o < lo + 0x400]
    if hits:
        print(f"    {reg_tag} 0x{lo:08X} 区域差异 {len(hits)} 个:")
        for o, v0, v1 in hits[:limit]:
            print(f"      0x{IWRAM[0] + o:08X}: {v0:3d} → {v1:3d}")


def main():
    ctrl_ev = load_demo("demo_20260806_232548.jsonl")
    lock_ev = load_demo("demo_20260806_233825.jsonl")

    print("=== 可控态探针 (2F (136,60), t=3000) ===")
    e1 = Emulator(rom_path=ROOT / cfg["rom"]["path"])
    di1, de1, b1, a1 = probe(e1, "可控", ctrl_ev, 3000)

    print("=== 锁态探针 (2F (120,112), t=终态) ===")
    e2 = Emulator(rom_path=ROOT / cfg["rom"]["path"])
    di2, de2, b2, a2 = probe(e2, "锁", lock_ev, None)

    print("\n=== 可控有而锁态无的 IWRAM 变化字节（锁点候选）===")
    only_ctrl = sorted(di1 - di2)
    print(f"  共 {len(only_ctrl)} 个")
    # 按区域分组展示
    for base in [0x0000, 0x0F00, 0x1000, 0x2000, 0x3000, 0x4000, 0x5000, 0x6000, 0x7000]:
        hits = [o for o in only_ctrl if base <= o < base + 0x1000]
        if hits:
            print(f"  0x{IWRAM[0] + base:08X}-0x{IWRAM[0] + base + 0xFFF:08X}: {len(hits)} 个")
            for o in hits[:40]:
                print(f"    {IWRAM[0] + o:08X}: 可控 {b1[o]}→{a1[o]} | 锁 {b2[o]}→{a2[o]}")

    print("\n=== 锁态按 UP 时仍变化的 IWRAM 字节（输入链路残余）===")
    both = sorted(di2)
    print(f"  共 {len(both)} 个")
    for o in both[:60]:
        print(f"    {IWRAM[0] + o:08X}: {b2[o]}→{a2[o]}")


if __name__ == "__main__":
    main()
