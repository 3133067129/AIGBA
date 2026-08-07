"""攻略驱动 Agent：按 walkthrough.json 逐步行动（PokeLLMon 式任务清单驱动）。

进度持久化在 data/knowledge/progress.json（步骤索引 + 徽章计数），
断点续跑。每步行动由 LLM 视觉确认场景 + 坐标驱动移动。

用法（main.py guide 命令）：
    从 after_intro.state 冷启动流程，或从最近进度续跑。
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from src.brain.new_game import NewGameBootstrap
from src.control.controller import Controller
from src.control.dfs import DfsExplorer
from src.emulator.keys import Key
from src.emulator.mgba_core import Emulator
from src.emulator.preview import PreviewWindow
from src.perception.llm_vision import VisionProvider
from src.state.extractor import GameStateExtractor

ROOT = Path(__file__).resolve().parent.parent.parent
PROGRESS_FILE = ROOT / "data" / "knowledge" / "progress.json"
WALKTHROUGH_FILE = ROOT / "data" / "knowledge" / "walkthrough.json"

ZH_DIR = {"上": "UP", "下": "DOWN", "左": "LEFT", "右": "RIGHT"}


def load_walkthrough() -> list[dict]:
    with open(WALKTHROUGH_FILE, encoding="utf-8") as f:
        return json.load(f)["steps"]


def load_progress() -> dict:
    if PROGRESS_FILE.exists():
        with open(PROGRESS_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"idx": 0, "badges": 0, "notes": {}}


def save_progress(p: dict) -> None:
    PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(p, f, ensure_ascii=False, indent=2)


class GuideAgent:
    def __init__(self, emu: Emulator, extractor: GameStateExtractor,
                 vision: VisionProvider, controller: Controller,
                 preview: PreviewWindow | None = None):
        self.emu = emu
        self.ex = extractor
        self.vision = vision
        self.ctrl = controller
        self.preview = preview
        self.steps = load_walkthrough()
        self.progress = load_progress()
        self.dfs = DfsExplorer(emu, extractor, controller,
                               outdoor_bright=999, unlock_dialog=True)

    # ---------- 工具 ----------

    def _status(self, text: str) -> None:
        print(text)
        if self.preview:
            self.preview.set_status(text)

    def _aborted(self) -> bool:
        return self.preview is not None and self.preview.abort_requested()

    def _stable_text(self, frames: int = 30) -> bool:
        """文字区域稳定（打字完成/等待输入）。"""
        tr = self.emu.screenshot()[96:158, 8:232]
        h1 = hashlib.sha256(tr.tobytes()).hexdigest()
        for _ in range(frames):
            self.emu.run_frames(5)
            tr2 = self.emu.screenshot()[96:158, 8:232]
            if hashlib.sha256(tr2.tobytes()).hexdigest() == h1:
                return True
        return False

    def push_dialog(self, max_pages: int = 8) -> int:
        """推进对话（等文字稳定→A）。返回推进页数。"""
        pages = 0
        for _ in range(max_pages):
            if self._aborted():
                break
            if not self._stable_text():
                continue
            h = hashlib.sha256(self.emu.screenshot().tobytes()).hexdigest()[:6]
            self.emu.press(Key.A, 8)
            self.emu.run_frames(80)
            h2 = hashlib.sha256(self.emu.screenshot().tobytes()).hexdigest()[:6]
            pages += 1
            if h2 == h:
                break
        return pages

    def ask_llm(self, question: str) -> str:
        return self.vision.describe([self.emu.screenshot()], question)

    # ---------- 步骤执行 ----------

    def execute_step(self, step: dict) -> str:
        """执行一步。返回执行摘要。"""
        sid = step["id"]
        title = step["title"]
        self._status(f"▶ 步骤: {title}")
        action = step.get("action", "")
        if sid == "home_clock":
            return self._find_and_set_clock()
        if sid in ("neighbor",):
            return f"需要导航到 {step['location']}（LLM 引导）"
        if sid == "choose_starter":
            return self._choose_starter(step)
        if "GYM" in title or "道馆" in title:
            return f"道馆战（Phase 2 战斗系统接入）: {action}"
        # 默认：对话推进 + LLM 描述
        desc = self.ask_llm(f"当前画面：{action}。描述场景并逐字列出对话/文字。")
        self._status(f"  LLM: {desc[:120]}")
        pages = self.push_dialog(8)
        return f"对话推进{pages}页 | {desc[:80]}"

    def _find_and_set_clock(self) -> str:
        """找电子钟（DFS 遍历 + LLM 确认）→ 面向钟按 A 调钟。"""
        visited = {self.dfs._grid()}
        stack = []
        g = self.dfs._grid()
        facing = "UP"
        DIRS = ["UP", "RIGHT", "DOWN", "LEFT"]
        BACKD = {"UP": "DOWN", "DOWN": "UP", "LEFT": "RIGHT", "RIGHT": "LEFT"}
        for step in range(80):
            if self._aborted():
                return "中止"
            if step % 2 == 0:
                desc = self.ask_llm(
                    "画面里有没有电子钟（墙上钟表/显示数字）？有的话在哪个方向？"
                    "只回答：没有/上/下/左/右")
                ans = desc.strip()[:3]
                if "没有" not in ans and ans:
                    cd = ZH_DIR.get(ans[0])
                    if cd:
                        self.emu.press(getattr(Key, cd), 4)
                        self.emu.run_frames(10)
                        self.emu.press(Key.A, 8)
                        self.emu.run_frames(150)
                        desc2 = self.ask_llm("这是什么界面？有时间设置吗？")
                        self._status(f"  调钟界面: {desc2[:100]}")
                        # 完整调钟序列：调小时→确认→调分钟→确认
                        for _ in range(3):
                            self.emu.press(Key.UP, 8)
                            self.emu.run_frames(20)
                        self.emu.press(Key.A, 8)
                        self.emu.run_frames(60)
                        for _ in range(3):
                            self.emu.press(Key.UP, 8)
                            self.emu.run_frames(20)
                        self.emu.press(Key.A, 8)
                        self.emu.run_frames(60)
                        self.emu.press(Key.A, 8)
                        self.emu.run_frames(100)
                        return f"找到钟({cd}方向)，完成调钟"
            right = {"UP": "RIGHT", "RIGHT": "DOWN", "DOWN": "LEFT", "LEFT": "UP"}[facing]
            left = {"UP": "LEFT", "LEFT": "DOWN", "DOWN": "RIGHT", "RIGHT": "UP"}[facing]
            moved = False
            for d in [right, facing, left, BACKD[facing]]:
                ng = self.dfs.move_one(d)
                if ng is None:
                    continue
                if ng in visited:
                    self.dfs.move_one(BACKD[d])
                    continue
                facing = d
                visited.add(ng)
                stack.append((g, d))
                g = ng
                moved = True
                break
            if moved:
                continue
            if not stack:
                break
            prev, came = stack.pop()
            self.dfs.move_one(BACKD[came])
            g = prev
        return f"未找到钟（遍历{len(visited)}格）"

    def _choose_starter(self, step: dict) -> str:
        """选御三家：LLM 看背包选项 → 方向键选择 → A。"""
        desc = self.ask_llm(
            f"这是选御三家界面吗？选项有哪些（{step.get('options', [])}）？"
            "选一个推荐（水跃鱼克岩石道馆）并用方向键指向它。逐字列出选项。")
        self._status(f"  选项: {desc[:120]}")
        # 默认选第一个（通常光标默认在水跃鱼/第一个）
        self.emu.press(Key.A, 8)
        self.emu.run_frames(120)
        return f"选择御三家: {desc[:80]}"

    # ---------- 主循环 ----------

    def run(self, max_steps_per_step: int = 30) -> dict:
        while self.progress["idx"] < len(self.steps):
            if self._aborted():
                break
            step = self.steps[self.progress["idx"]]
            result = self.execute_step(step)
            self.progress["notes"][step["id"]] = result[:80]
            save_progress(self.progress)
            # 步进（默认认为已执行；完成判定后续细化）
            self.progress["idx"] += 1
            save_progress(self.progress)
        return self.progress
