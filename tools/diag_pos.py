"""诊断：验证玩家真实移动，然后找坐标字段。

玩家区域 = 屏幕中央下方（角色 sprite 位置，Emerald 玩家居中偏下）。
比较玩家区域像素变化判定"真移动"；撞墙（原地踏步）则换方向。
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
from src.state.offsets import OffsetTable
from tools.calibrate_pos import dump, u16_delta, EWRAM_BASE, IWRAM_BASE

cfg = yaml.safe_load(open(ROOT / "config" / "settings.yaml", encoding="utf-8"))
emu = Emulator(rom_path=ROOT / cfg["rom"]["path"])
cp = ROOT / "data" / "checkpoints" / "after_intro.state"
emu.load_state(cp.read_bytes())
emu.run_frames(45)

PLAYER_ROI = (slice(70, 110), slice(60, 100))  # 玩家角色区域 (y, x)


def player_region_changed() -> bool:
    s0 = emu.screenshot()
    emu.run_frames(20)
    s1 = emu.screenshot()
    return float((s0[PLAYER_ROI] != s1[PLAYER_ROI]).mean()) > 0.02


DIRS = {"RIGHT": Key.RIGHT, "DOWN": Key.DOWN, "LEFT": Key.LEFT, "UP": Key.UP}
moved_dir = None
for name, key in DIRS.items():
    A_ew, A_iw = dump(emu)
    s0 = emu.screenshot()
    emu.press_hold(key)
    emu.run_frames(10)   # 1 格
    emu.release()
    emu.run_frames(60)   # 等格动画完成
    s1 = emu.screenshot()
    roi_diff = float((s0[PLAYER_ROI] != s1[PLAYER_ROI]).mean())
    if roi_diff > 0.02:
        moved_dir = name
        print(f"玩家真实移动: {name}（玩家区域变化 {roi_diff:.3f}）")
        B_ew, B_iw = dump(emu)
        d_ew, d_iw = u16_delta((A_ew, A_iw), (B_ew, B_iw))
        print(f"--- {name} 移动 1 格，u16 变化字段 ---")
        for d, base, tag in [(d_ew, EWRAM_BASE, "EWRAM"), (d_iw, IWRAM_BASE, "IWRAM")]:
            for idx in np.nonzero((d != 0) & (np.abs(d) <= 4))[0]:
                before = int(A_ew.view('<u2')[idx]) if base == EWRAM_BASE else int(A_iw.view('<u2')[idx])
                after = int(B_ew.view('<u2')[idx]) if base == EWRAM_BASE else int(B_iw.view('<u2')[idx])
                print(f"  0x{base + idx*2:08X} ({tag}): {before} -> {after} (Δ{d[idx]})")
        # 第二段：正交方向再移动一次，找"本方向变、正交方向不变"的字段
        ortho = {"RIGHT": "DOWN", "DOWN": "RIGHT", "LEFT": "DOWN", "UP": "RIGHT"}[name]
        C_ew, C_iw = dump(emu)
        s2 = emu.screenshot()
        emu.press_hold(DIRS[ortho])
        emu.run_frames(10)
        emu.release()
        emu.run_frames(60)
        s3 = emu.screenshot()
        roi2 = float((s2[PLAYER_ROI] != s3[PLAYER_ROI]).mean())
        if roi2 > 0.02:
            D_ew, D_iw = dump(emu)
            d2_ew, d2_iw = u16_delta((C_ew, C_iw), (D_ew, D_iw))
            print(f"--- 正交 {ortho} 移动 1 格确认 ---")
            # x 候选: 第一段变、第二段不变；y 反之
            for label, d1, d2, base, tag in [
                ("x 候选", d_ew, d2_ew, EWRAM_BASE, "EWRAM"),
                ("x 候选", d_iw, d2_iw, IWRAM_BASE, "IWRAM"),
                ("y 候选", d_ew, d2_ew, EWRAM_BASE, "EWRAM"),
                ("y 候选", d_iw, d2_iw, IWRAM_BASE, "IWRAM"),
            ]:
                pass
            x_cand = []
            y_cand = []
            for (d1, d2, base, tag) in [
                (d_ew, d2_ew, EWRAM_BASE, "EWRAM"), (d_iw, d2_iw, IWRAM_BASE, "IWRAM")]:
                for idx in np.nonzero((d1 != 0) & (np.abs(d1) <= 4) & (d2 == 0))[0]:
                    v = int((D_ew if base == EWRAM_BASE else D_iw).view('<u2')[idx])
                    x_cand.append((base + idx*2, v, tag))
                for idx in np.nonzero((d1 == 0) & (d2 != 0) & (np.abs(d2) <= 4))[0]:
                    v = int((D_ew if base == EWRAM_BASE else D_iw).view('<u2')[idx])
                    y_cand.append((base + idx*2, v, tag))
            print(f"x 候选: {x_cand}")
            print(f"y 候选: {y_cand}")
        else:
            print(f"正交 {ortho} 未移动（可能撞墙）")
        break
    else:
        print(f"{name}: 玩家区域未变化 (roi_diff={roi_diff:.3f})，跳过")

if moved_dir is None:
    print("所有方向玩家都没动——角色可能处于不可控状态")
