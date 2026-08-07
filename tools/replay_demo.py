"""演示回放器：确定性重放人工演示轨迹，验证可复现性。

用法：
    python tools/replay_demo.py <demo.jsonl>

原理：同一 ROM + 同一初始状态（boot 头记录）+ 同一按键序列
      → 无头核心状态序列完全一致（确定性模拟）。
      人工演示中成功的操作（如未白镇解锁），回放即稳定复现。

逐帧对照录制的状态快照：
- 坐标差 > 8px          → 偏差（回放异于演示，可能 savestate 起点漂移）
- bright 差 > 40        → 偏差
标签（note）到达时打印 ★，偏差点之后的所有标签视为未复现。

输出：偏差数 / 标签到达数 / 最终位置。0 偏差 = 完美复现。
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
from src.state.extractor import GameStateExtractor

cfg = yaml.safe_load(open(ROOT / "config" / "settings.yaml", encoding="utf-8"))
CK = ROOT / "data" / "checkpoints"
DEMO_DIR = ROOT / "data" / "demos"

TOL_XY = 8      # 坐标偏差容忍（像素）
TOL_BRIGHT = 40  # bright 偏差容忍


def load_events(path: Path):
    evs = []
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        ev = json.loads(line)
        evs.append(ev)
    return evs


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    demo_name = sys.argv[1]
    demo_path = DEMO_DIR / demo_name if not Path(demo_name).exists() else Path(demo_name)
    assert demo_path.exists(), f"demo 不存在: {demo_path}"

    events = load_events(demo_path)
    boot = events[0]
    assert boot["ev"] == "boot", "首个事件必须是 boot"

    print(f"=== 回放 {demo_path.name} ===")
    print(f"模式: {boot['mode']} | 创建: {boot.get('created', '?')}")
    if boot["mode"] == "state":
        print(f"起点: {boot['state']}（savestate 恢复有漂移风险，偏差>0 属正常）")
    else:
        print("起点: 帧 0 冷启动（确定性最强）")

    emu = Emulator(rom_path=ROOT / cfg["rom"]["path"])
    if boot["mode"] == "state":
        state_path = CK / boot["state"]
        assert state_path.exists(), f"savestate 不存在: {state_path}"
        emu.load_state(state_path.read_bytes())
        emu.run_frames(60)  # 与录制器起点对齐

    ex = GameStateExtractor()

    # ---- 回放主循环 ----
    idx = 1
    down: set[str] = set()
    mismatches = 0
    notes_hit = []
    notes_missed = []
    total_snap = 0
    first_mismatch_frame = None

    while idx < len(events):
        ev = events[idx]
        if ev["t"] > emu.frame_counter:
            emu.run_frames(1)
            continue
        # 到达该帧：处理事件
        if ev["ev"] == "keys":
            new_down = set(ev["down"])
            if new_down != down:
                keys = [Key[n] for n in new_down]
                if keys:
                    emu.press_hold(*keys)
                else:
                    emu.release()
                down = new_down
        elif ev["ev"] == "snap":
            total_snap += 1
            st = ex.extract(emu)
            dx, dy = st.player_x - ev["x"], st.player_y - ev["y"]
            b_now = float(emu.screenshot().mean())
            db = b_now - ev["b"]
            bad = abs(dx) > TOL_XY or abs(dy) > TOL_XY or abs(db) > TOL_BRIGHT
            if bad:
                mismatches += 1
                if first_mismatch_frame is None:
                    first_mismatch_frame = ev["t"]
                print(f"  ⚠ t={ev['t']}: 录({ev['x']},{ev['y']},b{ev['b']:.0f})"
                      f" 回放({st.player_x},{st.player_y},b{b_now:.0f})")
        elif ev["ev"] == "note":
            ok = first_mismatch_frame is None
            (notes_hit if ok else notes_missed).append(
                f"t={ev['t']} [{ev['tag']}]")
            mark = "★" if ok else "✗"
            print(f"  {mark} 节点 @ t={ev['t']}: {ev['tag']}"
                  + ("" if ok else "（此前已有偏差，未复现）"))
        elif ev["ev"] == "end":
            break
        idx += 1

    # ---- 汇总 ----
    st = ex.extract(emu)
    print(f"\n=== 结果 ===")
    print(f"总帧数: {emu.frame_counter} | 快照对照: {total_snap} | 偏差: {mismatches}")
    if notes_hit:
        print(f"✅ 复现标签 {len(notes_hit)} 个: {'; '.join(notes_hit)}")
    if notes_missed:
        print(f"❌ 未复现标签 {len(notes_missed)} 个: {'; '.join(notes_missed)}")
    print(f"最终: ({st.player_x},{st.player_y}) bright={emu.screenshot().mean():.0f}")
    if mismatches == 0:
        print("🎉 完美复现 —— 演示操作可稳定重放（AI 可学习此流程）")
    else:
        print(f"⚠ {mismatches} 处偏差 —— 起点非冷启动或 savestate 漂移。"
              f"若为人工解锁演示，请改用 --cold 录制。")


if __name__ == "__main__":
    main()
