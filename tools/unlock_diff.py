"""未白镇/剧情锁内存逆向：确定性回放两态 → 完整内存 diff → 找剧情锁标志。

用法：
    python tools/unlock_diff.py

两态来源（均为确定性回放，同一进程内构造）：
- 可控态：回放 demo_20260806_232548.jsonl 到 t=3000（家 2F 可控 (136,60)）
- 锁态：回放 demo_20260806_233825.jsonl 到终态（锁在 (120,112)）

方法：EWRAM/IWRAM/SRAM 全量分段 hash 对比 → 差异区域细化 → 逐字节 diff。
再对锁态跑 10 个时间点，保留「稳定差异」（剧情锁标志稳定，NPC 动画波动被排除）。
"""
from __future__ import annotations

import json
import sys
from collections import Counter
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

EWRAM = (0x02000000, 0x40000)    # 256KB（GBA EWRAM 实际大小）
IWRAM = (0x03000000, 0x8000)     # 32KB
SRAM = (0x0E000000, 0x20000)     # 128KB（read 不支持，跳过）
SEG = 4096


def load_demo(name: str):
    return [json.loads(l) for l in open(DEMO_DIR / name, encoding="utf-8")]


def replay_to(emu, events, stop_at: int | None = None):
    """回放直到帧 stop_at（含）或事件结束。返回最终 frame_counter。"""
    down: set[str] = set()
    idx = 1
    while idx < len(events):
        ev = events[idx]
        if stop_at is not None and emu.frame_counter >= stop_at:
            return emu.frame_counter
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
    return emu.frame_counter


def dump(emu) -> dict[str, np.ndarray]:
    out = {}
    # EWRAM 4MB 单次切片失败（绑定限制）→ 分段 0x40000 读
    data = bytearray()
    for off in range(0, EWRAM[1], 0x40000):
        data += emu.read(EWRAM[0] + off, 0x40000)
    out["ewram"] = np.frombuffer(bytes(data), dtype=np.uint8)
    out["iwram"] = np.frombuffer(emu.read(IWRAM[0], IWRAM[1]), dtype=np.uint8)
    out["sram"] = None  # 0x0E000000 不在 read 支持范围，跳过
    return out


def seg_hashes(arr) -> list[int]:
    if arr is None:
        return []
    n = len(arr) // SEG
    return [int(hash(arr[i * SEG:(i + 1) * SEG].tobytes())) for i in range(n)]


def main():
    ctrl_events = load_demo("demo_20260806_232548.jsonl")
    lock_events = load_demo("demo_20260806_233825.jsonl")

    print("=== 回放可控态 (t=3000) ===")
    e1 = Emulator(rom_path=ROOT / cfg["rom"]["path"])
    replay_to(e1, ctrl_events, stop_at=3000)
    d1 = dump(e1)
    print(f"  可控: ({e1.u16(0x02020650)},{e1.u16(0x02020652)})")

    print("=== 回放锁态 (终态) ===")
    e2 = Emulator(rom_path=ROOT / cfg["rom"]["path"])
    replay_to(e2, lock_events)
    d2 = dump(e2)
    print(f"  锁: ({e2.u16(0x02020650)},{e2.u16(0x02020652)})")

    # 粗筛：分段 hash 差异
    print("=== 差异分段（第一轮）===")
    for name in ["ewram", "iwram", "sram"]:
        h1, h2 = seg_hashes(d1[name]), seg_hashes(d2[name])
        diff_segs = [i for i in range(min(len(h1), len(h2))) if h1[i] != h2[i]]
        print(f"  {name}: {len(diff_segs)}/{len(h1)} 段不同")
        if name == "iwram":
            for i in diff_segs[:30]:
                base = IWRAM[0] + i * SEG
                print(f"    IWRAM 段 {i}: 0x{base:08X}")

    # IWRAM 细 diff（32KB 全对比）
    print("=== IWRAM 逐字节差异（前 200 个）===")
    a, b = d1["iwram"], d2["iwram"]
    diff = np.nonzero(a != b)[0]
    print(f"  IWRAM 差异字节: {len(diff)} 个")
    for off in diff[:200]:
        print(f"    0x{IWRAM[0] + int(off):08X}: 可控={a[off]:3d} 锁={b[off]:3d}")

    # EWRAM 差异统计
    print("=== EWRAM 差异区域（前 30 个 4KB 段的范围）===")
    a, b = d1["ewram"], d2["ewram"]
    h1, h2 = seg_hashes(d1["ewram"]), seg_hashes(d2["ewram"])
    diff_segs = [i for i in range(len(h1)) if h1[i] != h2[i]]
    # 合并相邻段
    groups = []
    for i in diff_segs:
        if groups and i == groups[-1][-1] + 1:
            groups[-1].append(i)
        else:
            groups.append([i])
    for g in groups[:30]:
        print(f"    0x{EWRAM[0] + g[0]*SEG:08X} - 0x{EWRAM[0] + (g[-1]+1)*SEG:08X}"
              f" ({len(g)*SEG} 字节)")

    print("=== SRAM 差异 ===")
    if d1["sram"] is not None and d2["sram"] is not None:
        diff = np.nonzero(d1["sram"] != d2["sram"])[0]
        print(f"  SRAM 差异字节: {len(diff)} 个")
        for off in diff[:50]:
            print(f"    0x{SRAM[0] + int(off):08X}: 可控={d1['sram'][off]:3d} 锁={d2['sram'][off]:3d}")


if __name__ == "__main__":
    main()
