"""脱困工具：蛇形栅格扫描找门/出口。

适用于小房间/走廊：按蛇形路径走遍当前区域（最多 max_rows 行），
每格对垂直方向的两面墙做穿越试探（move_dir 撞墙=墙，动=门/通道）。
找到门即脱困成功（玩家已到新区域）。

用法（agent 卡住时）:
    from src.control.exit import grid_scan_exit
    if grid_scan_exit(emu, extractor, controller):
        脱困成功
"""
from __future__ import annotations

from src.emulator.mgba_core import Emulator
from src.state.extractor import GameStateExtractor
from src.control.controller import Controller


def grid_scan_exit(emu: Emulator, extractor: GameStateExtractor,
                   controller: Controller, max_rows: int = 40,
                   on_move=None) -> bool:
    """蛇形扫描找出口。返回是否找到（穿越门/到达新区域）。

    扫描行方向 RIGHT/LEFT，每格对 UP/DOWN（墙面）做穿越试探；
    行末撞墙后尝试 DOWN 换行（也可能是门）。任何试探 moved=True
    = 玩家到了新区域 = 脱困。
    """
    st = extractor.extract(emu)
    start = (st.player_x, st.player_y)
    x_dir = "RIGHT"
    rows = 0
    while rows < max_rows:
        # 沿当前行扫
        for _ in range(60):
            st = extractor.extract(emu)
            gx, gy = st.player_x // 16, st.player_y // 16
            if on_move:
                on_move(f"栅格扫描 ({gx},{gy})")
            # 对垂直于行方向的墙做穿越试探
            for d in ("UP", "DOWN"):
                r = controller.move_dir(d, frames=20)
                if r["moved"]:
                    end = extractor.extract(emu)
                    if on_move:
                        on_move(f"🎯 出口 {d}: ({start[0]},{start[1]}) -> "
                                f"({end.player_x},{end.player_y})")
                    return True
            # 沿行走 1 格
            r = controller.move_dir(x_dir, frames=20)
            if not r["moved"]:
                break  # 行末
        # 换行（DOWN，也可能是门）
        r = controller.move_dir("DOWN", frames=20)
        if r["moved"]:
            if on_move:
                end = extractor.extract(emu)
                on_move(f"换行: ({end.player_x},{end.player_y})")
        else:
            break
        x_dir = "LEFT" if x_dir == "RIGHT" else "RIGHT"
        rows += 1
    if on_move:
        on_move("栅格扫描未找到出口（区域已扫完）")
    return False
