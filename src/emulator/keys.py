"""GBA 按键常量与高层按键组合。"""
from enum import Enum


class Key(Enum):
    A = "A"
    B = "B"
    SELECT = "SELECT"
    START = "START"
    RIGHT = "RIGHT"
    LEFT = "LEFT"
    UP = "UP"
    DOWN = "DOWN"
    R = "R"
    L = "L"

    # 别名
    CONFIRM = "A"
    CANCEL = "B"


KEY_MAP = {
    Key.A: "KEY_A",
    Key.B: "KEY_B",
    Key.SELECT: "KEY_SELECT",
    Key.START: "KEY_START",
    Key.RIGHT: "KEY_RIGHT",
    Key.LEFT: "KEY_LEFT",
    Key.UP: "KEY_UP",
    Key.DOWN: "KEY_DOWN",
    Key.R: "KEY_R",
    Key.L: "KEY_L",
}


def to_mgba_keys(*keys: Key) -> tuple[str, ...]:
    """把 Key 枚举转为 mgba.gba.GBA 的按键常量名列表。"""
    return tuple(KEY_MAP[k] for k in keys)


# 常用组合
D_PAD = (Key.UP, Key.DOWN, Key.LEFT, Key.RIGHT)
