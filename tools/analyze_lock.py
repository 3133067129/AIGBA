"""锁触发点分析：从人工演示轨迹提取「最后可动 → 锁死」的转变点。

输入：data/demos/demo_*.jsonl（demo_recorder 格式：keys/snap 事件）
输出：锁点报告——锁触发前的最后按键、位置、地图 id（回放读取）、时间。

用途：纯视觉路线要避免触发锁的操作；本报告给出「什么操作后锁了」。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import yaml

from src.emulator.mgba_core import Emulator
from src.emulator.keys import Key

cfg = yaml.safe_load(open(ROOT / "config" / "settings.yaml", encoding="utf-8"))
DEMO_DIR = ROOT / "data" / "demos"


def main():
    if len(sys.argv) < 2:
        print("用法: analyze_lock.py <demo.jsonl>")
        sys.exit(1)
    demo_name = sys.argv[1]
    path = DEMO_DIR / demo_name if not Path(demo_name).exists() else Path(demo_name)
    events = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]

    snaps = [e for e in events if e["ev"] == "snap"]
    keys = [e for e in events if e["ev"] == "keys"]

    # 找锁点：从后往前找「最后一个坐标有变化」的 snap
    lock_t = None
    last_move = None
    prev = None
    for s in snaps:
        pos = (s["x"], s["y"])
        if prev is not None and pos != prev:
            last_move = s
        prev = pos
    # 锁点 = last_move 之后第一个「坐标不再变化」的时刻（取 last_move 后第 2 个 snap）
    moved_until = last_move["t"] if last_move else 0
    after = [s for s in snaps if s["t"] > moved_until]
    lock_t = after[0]["t"] if after else None

    print(f"=== 锁点分析: {path.name} ===")
    print(f"最后可动: t={moved_until} ({last_move['x']},{last_move['y']}) b={last_move['b']:.0f}")
    if lock_t:
        print(f"锁死判定点: t={lock_t}（其后坐标不再变化）")
    # 锁点前后 90 帧按键
    print(f"\n--- 锁前最后 90 帧按键（t={moved_until-90}~{moved_until+30}）---")
    for k in keys:
        if moved_until - 90 <= k["t"] <= moved_until + 30:
            print(f"  t={k['t']}: {k['down']}")
    # 锁前位置轨迹（最后 10 个移动点）
    moves = [s for s in snaps if s["t"] <= moved_until]
    last10 = moves[-10:]
    print(f"\n--- 锁前最后 10 个位置 ---")
    for s in last10:
        print(f"  t={s['t']}: ({s['x']},{s['y']}) b={s['b']:.0f}")

    # 回放读锁点的地图 id（确定性回放 0 偏差，可直接读）
    print(f"\n--- 回放读取锁点状态 ---")
    emu = Emulator(rom_path=ROOT / cfg["rom"]["path"])
    down: set[str] = set()
    idx = 1
    while idx < len(events):
        ev = events[idx]
        if emu.frame_counter >= moved_until:
            break
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
    emu.run_frames(30)
    print(f"锁点状态: ({emu.u16(0x02020650)},{emu.u16(0x02020652)}) "
          f"map={emu.u8(0x02025A0C)}:{emu.u8(0x02025A0E)} "
          f"MOVE_FLAG={emu.u8(0x03000F2C)}")

    # 报告写入 knowledge
    out = ROOT / "data" / "knowledge" / "lock_analysis.md"
    lines = [
        f"# 锁点分析: {path.name}",
        "",
        f"- 最后可动: t={moved_until} ({last_move['x']},{last_move['y']})",
        f"- 锁死判定: t={lock_t}",
        f"- 锁点状态: map={emu.u8(0x02025A0C)}:{emu.u8(0x02025A0E)}",
        f"- 锁前按键: {[k['down'] for k in keys if moved_until-90 <= k['t'] <= moved_until]}",
        "",
        "**结论**: 锁由上述操作触发（或该位置触发）。纯视觉路线应避免在锁点位置重复该操作。",
    ]
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n报告已写入: {out}")


if __name__ == "__main__":
    main()
