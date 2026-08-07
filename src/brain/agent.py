"""Phase 1 Agent：LLM 视觉驱动的决策循环。

每步：截图 → LLM 识别界面类型+决定动作（JSON）→ 控制器执行 → 短期记忆。
LLM 是地面真值（该 hack 界面流程与零售版不同，像素启发式不可靠）；
像素检测用于卡死/对话检测等局部判定。
"""
from __future__ import annotations

import json
import re

from src.brain.actions import Action, ActionType
from src.brain.knowledge import Knowledge
from src.brain.new_game import NewGameBootstrap
from src.control.controller import Controller
from src.emulator.keys import Key
from src.emulator.mgba_core import Emulator
from src.perception.llm_vision import VisionProvider
from src.state.extractor import GameState, GameStateExtractor

ACTION_PROMPT = """你在用 GBA 模拟器玩《口袋妖怪绿宝石386》（中文汉化版）。
当前任务：{goal}
游戏进度：{progress}
最近操作：{recent}（空表示刚开始）

下面是当前游戏画面。请：
1. 判断当前界面类型
2. 识别画面中的文字（逐字，特别是菜单项和对话框）
3. 决定下一步操作

只输出 JSON（不要其他内容），格式：
{{"screen": "标题|主菜单|子菜单|对话框|地图|战斗|过场动画|黑屏|其他",
  "visible_text": "画面中的文字",
  "action": "A|B|START|UP|DOWN|LEFT|RIGHT|WAIT",
  "reason": "一句话说明"}}

行动规则：
- 标题/过场动画：按 A 跳过
- 主菜单：若看到「开始游戏」或「新的冒险」，直接按 A（光标默认在第一项）
- 对话框：按 A 推进
- 地图：按方向键向目标方向走（一次只走一小段）
- 有菜单项选择时先按方向键移动光标再按 A
- 不确定时按 WAIT"""

KEY_MAP = {
    "A": Key.A, "B": Key.B, "START": Key.START,
    "UP": Key.UP, "DOWN": Key.DOWN, "LEFT": Key.LEFT, "RIGHT": Key.RIGHT,
}


def parse_llm_action(text: str) -> tuple[str, str, str]:
    """解析 LLM 输出 JSON，返回 (screen, action, reason)。失败返回 ("其他","WAIT","")。"""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return "其他", "WAIT", ""
    try:
        data = json.loads(m.group(0))
        return (str(data.get("screen", "其他")),
                str(data.get("action", "WAIT")).upper(),
                str(data.get("reason", "")))
    except (json.JSONDecodeError, AttributeError):
        return "其他", "WAIT", ""


class Agent:
    def __init__(self, emu: Emulator, extractor: GameStateExtractor,
                 vision: VisionProvider, controller: Controller,
                 knowledge: Knowledge):
        self.emu = emu
        self.extractor = extractor
        self.vision = vision
        self.controller = controller
        self.knowledge = knowledge
        self.memory: list[str] = []  # 短期记忆
        self.goal = "开始新的游戏"
        self.step_count = 0

    # ---------- 记忆 ----------

    def _remember(self, text: str) -> None:
        self.memory.append(text)
        self.memory = self.memory[-12:]

    def _recent_text(self) -> str:
        return " | ".join(self.memory[-4:]) if self.memory else "无"

    def _progress_text(self) -> str:
        g = self.knowledge
        parts = []
        if g.goal_done("new_game_started"):
            parts.append("新游戏已开始")
        if g.goal_done("left_house"):
            parts.append("已走出家门")
        if g.goal_done("reached_town"):
            parts.append("已到达城镇")
        if g.goal_done("talked_npc"):
            parts.append(f"已对话NPC×{g.get_counter('npc_talks')}")
        parts.append(f"已知地图: {len(g.known_maps())}个")
        return "，".join(parts) if parts else "刚开始"

    # ---------- 主循环 ----------

    def step(self) -> dict:
        """单步：观察→决策→执行。返回本轮摘要。"""
        self.step_count += 1
        screen = self.emu.screenshot()

        prompt = ACTION_PROMPT.format(
            goal=self.goal,
            progress=self._progress_text(),
            recent=self._recent_text(),
        )
        text = self.vision.describe([screen], prompt)
        screen_type, action, reason = parse_llm_action(text)

        # 执行动作
        key = KEY_MAP.get(action)
        if key is None:
            self.emu.run_frames(30)
            acted = "WAIT"
        elif action == "WAIT":
            self.emu.run_frames(30)
            acted = "WAIT"
        else:
            # 方向键多按一会（移动需要连续输入）
            frames = 40 if key in (Key.UP, Key.DOWN, Key.LEFT, Key.RIGHT) else 8
            self.emu.press(key, frames)
            self.emu.run_frames(20)
            acted = action

        summary = f"{screen_type}[{acted}] {reason}"
        self._remember(summary)
        return {"screen": screen_type, "action": acted, "reason": reason,
                "step": self.step_count}

    def run(self, max_steps: int = 200, on_step=None) -> dict:
        """循环执行。on_step(stats) 每步回调（供 checkpoint/卡死检测）。"""
        stats = {"steps": 0, "actions": {}, "last_screen": "", "screens": {}}
        for _ in range(max_steps):
            r = self.step()
            stats["steps"] += 1
            stats["actions"][r["action"]] = stats["actions"].get(r["action"], 0) + 1
            stats["screens"][r["screen"]] = stats["screens"].get(r["screen"], 0) + 1
            if on_step:
                on_step(r)
        return stats
