"""锁点写-试-验扫描（savestate 加速版）：锁态下改写候选字节 → 测 UP 能否移动。

流程：回放锁态一次 → save_state → 每个候选：load_state（秒恢复）→ 写 → 测。
候选来自 unlock_probe/unlock_diff 的行为标定。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import yaml

from src.emulator.keys import Key
from src.emulator.mgba_core import Emulator

cfg = yaml.safe_load(open(ROOT / "config" / "settings.yaml", encoding="utf-8"))
evs = [json.loads(l) for l in open(
    ROOT / "data" / "demos" / "demo_20260806_233825.jsonl", encoding="utf-8")]

# (地址, 测试值列表)
CANDIDATES = [
    (0x020249C0, [107, 47, 0, 255, 100, 16]),
    (0x020249C1, [159, 107, 0]),
    (0x02021BC0, [0, 1, 252, 255]),
    (0x02021690, [0, 6, 2]),
    (0x03001380, [251, 252, 0, 255]),
    (0x03001590, [144, 16, 0, 255]),
    (0x03001394, [96, 56, 0, 255]),
    (0x030013A0, [59, 80, 0, 255]),
]

DIR_KEY = {"UP": Key.UP, "DOWN": Key.DOWN, "LEFT": Key.LEFT, "RIGHT": Key.RIGHT}


def replay_lock(emu):
    down: set[str] = set()
    idx = 1
    while idx < len(evs):
        ev = evs[idx]
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
    emu.run_frames(60)


def try_move(emu, d="UP", frames=30):
    p0 = (emu.u16(0x02020650), emu.u16(0x02020652))
    emu.press_hold(DIR_KEY[d])
    for _ in range(frames):
        emu.run_frames(1)
    emu.release()
    emu.run_frames(10)
    p1 = (emu.u16(0x02020650), emu.u16(0x02020652))
    return abs(p1[0] - p0[0]) > 8 or abs(p1[1] - p0[1]) > 8, p0, p1


def main():
    emu = Emulator(rom_path=ROOT / cfg["rom"]["path"])
    print("回放锁态...")
    replay_lock(emu)
    st0 = (emu.u16(0x02020650), emu.u16(0x02020652))
    print(f"锁态基线: pos={st0} bright={emu.screenshot().mean():.0f}")
    state_bytes = emu.save_state()

    # 先确认锁态本身移动失败
    ok, _, _ = try_move(emu)
    print(f"基线移动测试: {ok}（应为 False）")

    total = sum(len(v) for _, v in CANDIDATES)
    n = 0
    for addr, vals in CANDIDATES:
        for v in vals:
            n += 1
            emu.load_state(state_bytes)
            emu.run_frames(30)
            emu.write(addr, bytes([v]))
            emu.run_frames(5)
            ok, pa, pb = try_move(emu)
            cur = emu.u8(addr) if addr < 0x03000000 else emu.u8(addr)
            mark = "🎉" if ok else "  "
            print(f"{mark}[{n}/{total}] 0x{addr:08X}={v:3d} → 移动={ok} "
                  f"({pa}→{pb}) 写后值={cur}")
            if ok:
                print(f"*** 发现解锁值 0x{addr:08X}={v}！")
                emu.run_frames(120)
                Path(ROOT / "data" / "checkpoints" / "unlocked.state").write_bytes(
                    emu.save_state())
                print("已保存 unlocked.state")
                return
    print("全部候选未解锁")


if __name__ == "__main__":
    main()
