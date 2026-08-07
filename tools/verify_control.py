"""玩家位移检测实验：模板匹配找玩家 sprite，验证真实移动。

玩家 sprite 在屏幕中心偏下（Emerald 大地图）。模板匹配：
  1. 按方向键前截图 s0，裁剪中心区为模板
  2. 按方向键后截图 s1，在 s1 中滑窗搜索最佳匹配
  3. 位移 (dx, dy) = 16px 级 = 真移动；~0 = 没动
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

cfg = yaml.safe_load(open(ROOT / "config" / "settings.yaml", encoding="utf-8"))
emu = Emulator(rom_path=ROOT / cfg["rom"]["path"])
cp = ROOT / "data" / "checkpoints" / sys.argv[1] if len(sys.argv) > 1 else \
    ROOT / "data" / "checkpoints" / "after_intro.state"
emu.load_state(cp.read_bytes())
emu.run_frames(45)

# 玩家模板：屏幕中心偏下区域（含玩家 sprite + 少量背景）
TPLT = (slice(90, 130), slice(64, 96))
SEARCH = 40  # 搜索半径（像素）


def find_player(s0: np.ndarray, s1: np.ndarray) -> tuple:
    """在 s1 中找 s0 模板（中心区）的最佳匹配偏移。返回 (dx, dy, score)。"""
    tpl = s0[TPLT].astype(np.int16)
    th, tw = tpl.shape[:2]
    best_dx, best_dy, best_score = 0, 0, 1e18
    for dy in range(-SEARCH, SEARCH + 1, 4):
        for dx in range(-SEARCH, SEARCH + 1, 4):
            y0, y1 = 90 + dy, 90 + dy + th
            x0, x1 = 64 + dx, 64 + dx + tw
            if y0 < 0 or x0 < 0 or y1 > 160 or x1 > 240:
                continue
            region = s1[y0:y1, x0:x1].astype(np.int16)
            score = np.abs(region - tpl).mean()
            if score < best_score:
                best_score, best_dx, best_dy = score, dx, dy
    return best_dx, best_dy, best_score


DIRS = {"RIGHT": Key.RIGHT, "DOWN": Key.DOWN, "LEFT": Key.LEFT, "UP": Key.UP}
print(f"checkpoint: {cp.name}")
for name, key in DIRS.items():
    s0 = emu.screenshot()
    emu.press_hold(key)
    emu.run_frames(40)
    emu.release()
    emu.run_frames(30)
    s1 = emu.screenshot()
    dx, dy, score = find_player(s0, s1)
    print(f"{name}: 玩家位移=({dx:4d},{dy:4d}) 匹配分={score:.1f} "
          f"({'真移动' if max(abs(dx), abs(dy)) >= 12 else '未移动/动画'})")
