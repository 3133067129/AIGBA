"""修复 checkpoint：从旧 checkpoint 推进过场动画，直到真正玩家可控。

可靠判定（2026-08-06 修正）：
  1. 预检静止：不按键 30 帧，画面变化 < 2% = 无大动画（过场/字幕）进行中
  2. 按键测试：按 RIGHT 30 帧，画面变化 > 5% = 玩家真的动了
两者都过 = 可控。过场动画期间（画面自动变化大）→ advance_with_watchdog 推进。

用法: python tools/fix_checkpoint.py <输入.state> <输出.state> [最多秒数]
"""
from __future__ import annotations

import hashlib
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import yaml

from src.emulator.keys import Key
from src.emulator.mgba_core import Emulator
from src.brain.new_game import NewGameBootstrap
from src.state.extractor import GameStateExtractor
from src.perception.llm_vision import make_provider

cfg = yaml.safe_load(open(ROOT / "config" / "settings.yaml", encoding="utf-8"))


def diff_ratio(emu, frames: int = 30) -> float:
    s0 = emu.screenshot()
    emu.run_frames(frames)
    s1 = emu.screenshot()
    return float((s0 != s1).mean())


def controllable(emu) -> bool:
    """静止预检 + 按键测试。"""
    if diff_ratio(emu, 30) > 0.02:   # 大动画进行中
        return False
    s0 = emu.screenshot()
    emu.press_hold(Key.RIGHT)
    emu.run_frames(30)
    emu.release()
    emu.run_frames(10)
    s1 = emu.screenshot()
    return float((s0 != s1).mean()) > 0.05


def main() -> int:
    src = sys.argv[1] if len(sys.argv) > 1 else "after_intro.state"
    dst = sys.argv[2] if len(sys.argv) > 2 else "controllable.state"
    max_sec = float(sys.argv[3]) if len(sys.argv) > 3 else 420.0

    emu = Emulator(rom_path=ROOT / cfg["rom"]["path"])
    cp = ROOT / "data" / "checkpoints" / src
    emu.load_state(cp.read_bytes())
    emu.run_frames(45)
    print(f"恢复 {cp.name}")

    vision = make_provider(cfg["llm"])
    b = NewGameBootstrap(emu, GameStateExtractor(), vision)
    t0 = time.time()
    while time.time() - t0 < max_sec:
        if controllable(emu):
            print(f"玩家可控！({time.time()-t0:.0f}s)")
            (ROOT / "data" / "checkpoints" / dst).write_bytes(emu.save_state())
            print(f"已保存 {dst}")
            return 0
        # 推进过场（按 A 等对话框 + 等待动画）
        b.advance_with_watchdog(60, on_change=lambda d, t: print(f"  [{t:.0f}s] {d}"))
    print(f"{max_sec:.0f}s 内未达到可控状态")
    return 1


if __name__ == "__main__":
    sys.exit(main())
