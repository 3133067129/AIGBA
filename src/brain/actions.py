"""高层动作空间：LLM/策略输出意图，控制器翻译为按键序列。"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ActionType(Enum):
    # 移动（方向为场景方向，非屏幕方向）
    MOVE_UP = "MOVE_UP"
    MOVE_DOWN = "MOVE_DOWN"
    MOVE_LEFT = "MOVE_LEFT"
    MOVE_RIGHT = "MOVE_RIGHT"
    # 互动
    TALK = "TALK"                 # 面向目标按 A（对话/开门/调查）
    CONFIRM = "CONFIRM"           # 按 A
    CANCEL = "CANCEL"             # 按 B
    MENU = "MENU"                 # START 菜单
    # 菜单导航
    MENU_SELECT = "MENU_SELECT"   # 方向+确认（params: item 文字，由感知层定位）
    # 战斗（Phase 2 展开）
    BATTLE_MOVE = "BATTLE_MOVE"
    # 其他
    WAIT = "WAIT"                 # 等 N 帧
    EXPLORE = "EXPLORE"           # 探索性移动（撞墙换向）


@dataclass
class Action:
    type: ActionType
    params: dict = None  # 如 {"frames": 60}、{"direction": "UP"}

    def __post_init__(self):
        if self.params is None:
            self.params = {}

    def __repr__(self):
        return f"Action({self.type.name}{(' ' + str(self.params)) if self.params else ''})"


# 便捷构造
def move(direction: str, frames: int = 60) -> Action:
    return Action(ActionType[f"MOVE_{direction.upper()}"], {"frames": frames})


def wait(frames: int = 60) -> Action:
    return Action(ActionType.WAIT, {"frames": frames})
