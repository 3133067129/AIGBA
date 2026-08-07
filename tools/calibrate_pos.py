"""大地图状态下标定玩家坐标偏移（386 hack 与零售版不同，0x02025A08 读 0）。

方法：多轮正交移动迭代收敛。每轮：
  水平段（RIGHT/LEFT）：记录"持久变化"的 u16 地址集合
  垂直段（DOWN/UP）  ：同样记录
  x 候选 = 水平变 ∧ 垂直不变；y 候选 = 垂直变 ∧ 水平不变
轮间取交集 → 噪音字段（NPC 位置/动画状态/步数在部分轮次不变）
几轮后自然消失；坐标字段每轮都满足 → 收敛为唯一候选。
结果写入 config/offsets.json（player_x / player_y）。

用法: python tools/calibrate_pos.py [checkpoint.state]
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

EWRAM_BASE = 0x02000000
IWRAM_BASE = 0x03000000
MOVE_HOLD_FRAMES = 90   # 长按帧数（走 2-4 格）
SETTLE_FRAMES = 45      # 松键后静置帧数
MAX_STEP = 12           # 单次移动 u16 变化上限
N_ROUNDS = 3            # 迭代轮数


def load_cfg() -> dict:
    with open(ROOT / "config" / "settings.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def dump(emu: Emulator):
    """全量 dump EWRAM/IWRAM，返回 (ew_np, iw_np)。

    注意：cffi 切片 w[:]（省略参数）会少 1 字节，必须显式 [:len(w)]。
    """
    w, i = emu.gba.memory.wram.u8, emu.gba.memory.iwram.u8
    ew = np.frombuffer(bytes(w[:len(w)]), dtype=np.uint8)
    iw = np.frombuffer(bytes(i[:len(i)]), dtype=np.uint8)
    return ew.copy(), iw.copy()


def move(emu: Emulator, key, hold_frames=MOVE_HOLD_FRAMES,
         settle_frames=SETTLE_FRAMES) -> None:
    emu.press_hold(key)
    emu.run_frames(hold_frames)
    emu.release()
    emu.run_frames(settle_frames)


def u16_delta(before: tuple, after: tuple) -> tuple:
    """(ew, iw) 快照的 u16 视角差值（int32）。"""
    b_ew, b_iw = before
    a_ew, a_iw = after
    d_ew = a_ew.view("<u2").astype(np.int32) - b_ew.view("<u2").astype(np.int32)
    d_iw = a_iw.view("<u2").astype(np.int32) - b_iw.view("<u2").astype(np.int32)
    return d_ew, d_iw


def persistent_change(before: tuple, after: tuple, settle: tuple) -> tuple:
    """移动后持久变化的字段：after 与 before 不同，且静置后保持（settle == after）。"""
    d_ew, d_iw = u16_delta(before, after)
    s_ew, s_iw = settle
    a_ew, a_iw = after
    mask_ew = (d_ew != 0) & (a_ew.view("<u2") == s_ew.view("<u2"))
    mask_iw = (d_iw != 0) & (a_iw.view("<u2") == s_iw.view("<u2"))
    return mask_ew, mask_iw


def mask_addresses(mask_ew: np.ndarray, mask_iw: np.ndarray,
                   max_val: int = 40) -> set:
    """把 u16 mask 转成地址集合，附带值范围过滤（坐标是小正数）。"""
    hits = set()
    for mask, base in [(mask_ew, EWRAM_BASE), (mask_iw, IWRAM_BASE)]:
        for idx in np.nonzero(mask)[0]:
            v = mask[idx]  # 占位，值在调用方算
            hits.add((base + idx * 2, base + idx * 2))
    return hits


def abs_addrs(ew_mask: np.ndarray, iw_mask: np.ndarray,
              ew_vals: np.ndarray, iw_vals: np.ndarray) -> set:
    """mask 为真的 u16 索引 → {(绝对地址, 当前值)}，过滤值范围 0<v<=40。"""
    out = set()
    for mask, base, vals in [(ew_mask, EWRAM_BASE, ew_vals),
                             (iw_mask, IWRAM_BASE, iw_vals)]:
        for idx in np.nonzero(mask)[0]:
            v = int(vals[idx])
            if 0 < v <= 40:
                out.add((base + idx * 2, v))
    return out


def try_move_persistent(emu: Emulator, directions: list[str]) -> tuple:
    """依次尝试 directions 直到产生持久移动变化。

    返回 (方向名, (A,B,C) 快照, (dAB, dBC) delta) 或 (None, None, None)。
    """
    DIR_KEYS = {"RIGHT": Key.RIGHT, "DOWN": Key.DOWN,
                "LEFT": Key.LEFT, "UP": Key.UP}
    A = dump(emu)
    for name in directions:
        move(emu, DIR_KEYS[name])
        B = dump(emu)
        emu.run_frames(SETTLE_FRAMES)
        C = dump(emu)
        dAB, dBC = u16_delta(A, B), u16_delta(B, C)
        h_ew, h_iw = persistent_change(A, B, C)
        if np.any(h_ew) or np.any(h_iw):
            return name, (A, B, C), (dAB, dBC)
        A = B  # 没动（撞墙），换方向继续
    return None, None, None


def main() -> int:
    checkpoint = sys.argv[1] if len(sys.argv) > 1 else "after_intro.state"
    cfg = load_cfg()
    emu = Emulator(rom_path=ROOT / cfg["rom"]["path"])

    cp = ROOT / "data" / "checkpoints" / checkpoint
    if cp.exists():
        emu.load_state(cp.read_bytes())
        print(f"已恢复 {cp.name}")
    emu.run_frames(SETTLE_FRAMES)

    x_cand = None
    y_cand = None
    rounds_info = []
    for rnd in range(N_ROUNDS):
        # 水平段（优先与上一轮同方向，撞墙自动换）
        h_dirs = ["RIGHT", "LEFT"] if rnd % 2 == 0 else ["LEFT", "RIGHT"]
        v_dirs = ["DOWN", "UP"] if rnd % 2 == 0 else ["UP", "DOWN"]
        h_name, h_snaps, h_delta = try_move_persistent(emu, h_dirs)
        if h_name is None:
            print(f"轮{rnd}: 水平方向移动失败，跳过")
            continue
        v_name, v_snaps, v_delta = try_move_persistent(emu, v_dirs)
        if v_name is None:
            print(f"轮{rnd}: 垂直方向移动失败，跳过")
            continue

        (A, B, C), (dAB, dBC) = h_snaps, h_delta
        (D, E, F), (dDE, dEF) = v_snaps, v_delta
        # x 候选：水平持久变 ∧ 垂直段不变（E 相对 D，x 不动）
        h_mask_ew, h_mask_iw = persistent_change(A, B, C)
        x_no_v_ew = dDE[0] == 0
        x_no_v_iw = dDE[1] == 0
        x_ew = h_mask_ew & x_no_v_ew
        x_iw = h_mask_iw & x_no_v_iw
        # y 候选：垂直持久变 ∧ 水平段不变（B 相对 A，y 不动）
        v_mask_ew, v_mask_iw = persistent_change(D, E, F)
        y_no_h_ew = dAB[0] == 0
        y_no_h_iw = dAB[1] == 0
        y_ew = v_mask_ew & y_no_h_ew
        y_iw = v_mask_iw & y_no_h_iw

        x_set = abs_addrs(x_ew, x_iw, E[0].view("<u2"), E[1].view("<u2"))
        y_set = abs_addrs(y_ew, y_iw, E[0].view("<u2"), E[1].view("<u2"))
        rounds_info.append(
            f"轮{rnd} [{h_name}/{v_name}]: x候选{len(x_set)}={sorted(x_set)} "
            f"y候选{len(y_set)}={sorted(y_set)}")
        x_cand = x_set if x_cand is None else (x_cand & x_set)
        y_cand = y_set if y_cand is None else (y_cand & y_set)

    print("\n=== 标定过程 ===")
    for line in rounds_info:
        print(" ", line)
    print("\n=== 收敛结果 ===")
    print(f"x 候选: {sorted(x_cand) if x_cand else '空'}")
    print(f"y 候选: {sorted(y_cand) if y_cand else '空'}")

    if x_cand and y_cand and len(x_cand) == 1 and len(y_cand) == 1:
        x_addr, _ = next(iter(x_cand))
        y_addr, _ = next(iter(y_cand))
        table = OffsetTable.load()
        table.data["player_x"] = {"addr": x_addr, "type": "u16"}
        table.data["player_y"] = {"addr": y_addr, "type": "u16"}
        table.save()
        print(f"\n已写入 offsets.json: x=0x{x_addr:08X} y=0x{y_addr:08X}")
        return 0
    print("\n候选未唯一收敛，未写入 offsets.json。")
    return 2


if __name__ == "__main__":
    sys.exit(main())
