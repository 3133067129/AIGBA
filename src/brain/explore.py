"""Phase 1 探索 Agent：LLM 视觉决策 + 控制器执行。

目标（DoD）：到达城镇中心 + 对话 2 个 NPC + 菜单开合验证。
每步：截图 → LLM 输出 JSON（界面类型/方向/NPC）→ 控制器执行。
界面处理：
  地图    → move_dir 朝目标方向走一段（撞墙自动回退）
  对话框  → 推进对话（NPC 对话计数）
  过场    → advance_with_watchdog 推进（复用新游戏推进器）
  主菜单  → B 关闭（菜单开合验证）
  战斗    → 记录（Phase 2 处理）
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from src.brain.knowledge import Knowledge
from src.brain.new_game import NewGameBootstrap
from src.control.controller import Controller
from src.emulator.mgba_core import Emulator
from src.emulator.preview import PreviewWindow
from src.perception.llm_vision import VisionProvider
from src.state.extractor import GameState, GameStateExtractor

EXPLORE_PROMPT = """你在用 GBA 模拟器玩《口袋妖怪绿宝石386》（中文汉化版）。
当前任务：{goal}
游戏进度：{progress}
最近操作：{recent}

这是当前游戏画面。请判断：
1. 界面类型。判定规则（重要）：
   - 地图/房间 = 能看到角色、地面、建筑，玩家可以走动。即使画面上有文字招牌
     （如"宝可梦中心"）或有 NPC，也属于地图，绝不属于对话框！
   - 对话框 = 画面底部有一个明显的深色对话文字框（框内有白色对话文字，
     通常两三行）。只有这种情况才是对话框。
   - 过场动画 = 画面自动在动，玩家不能操作
2. 画面中的文字（逐字列出，特别是对话框内容和招牌）
3. 如果是地图：画面里有没有可以对话的人物（NPC，非玩家自己）？在什么方向？
4. 如果是地图：朝哪个方向走能到达城镇中心/更多建筑？（只选一个方向）

地图状态下必须给出 direction（UP/DOWN/LEFT/RIGHT 之一），不许 none。
若实在无法判断，选一个看起来能走通的方向。

只输出 JSON（不要其他内容）：
{{"screen":"地图|对话框|过场动画|主菜单|子菜单|战斗|黑屏|其他",
  "text":"画面文字",
  "direction":"UP|DOWN|LEFT|RIGHT",
  "npc_direction":"UP|DOWN|LEFT|RIGHT|none",
  "town":"true|false|unknown",
  "note":"一句话"}}"""

DIR_KEY = {"UP": 0, "DOWN": 1, "LEFT": 2, "RIGHT": 3}


def parse_llm(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return {}
    try:
        data = json.loads(m.group(0))
        return {k: str(v) for k, v in data.items()}
    except (json.JSONDecodeError, AttributeError):
        return {}


class ExploreAgent:
    def __init__(self, emu: Emulator, extractor: GameStateExtractor,
                 vision: VisionProvider, controller: Controller,
                 knowledge: Knowledge, preview: PreviewWindow | None = None,
                 goal: str = "走到城镇中心，对话 2 个 NPC，测试菜单开合"):
        self.emu = emu
        self.extractor = extractor
        self.vision = vision
        self.controller = controller
        self.knowledge = knowledge
        self.preview = preview
        self.goal = goal
        self.memory: list[str] = []
        self.stats = {"steps": 0, "npc_talks": 0, "menu_tested": False,
                      "town": False, "actions": {}}

    # ---------- 工具 ----------

    def _status(self, text: str) -> None:
        print(text)
        if self.preview:
            self.preview.set_status(text)

    def _remember(self, text: str) -> None:
        self.memory.append(text)
        self.memory = self.memory[-8:]

    def _progress_text(self) -> str:
        parts = []
        if self.knowledge.goal_done("left_house"):
            parts.append("已走出家门")
        if self.knowledge.goal_done("reached_town"):
            parts.append("已到达城镇")
        parts.append(f"NPC对话×{self.knowledge.get_counter('npc_talks')}")
        if self.knowledge.goal_done("menu_tested"):
            parts.append("菜单开合已验证")
        return "，".join(parts) if parts else "刚开始探索"

    def _count_action(self, action: str) -> None:
        self.stats["actions"][action] = self.stats["actions"].get(action, 0) + 1

    def _scan_sweep(self) -> str:
        """扇扫探索：固定顺序轮转方向，远距离穿越（撞墙自动停）。

        frames=200（~12 格）保证一次扫过整个房间，避免室内打转。
        """
        self._scan_idx = getattr(self, "_scan_idx", 0)
        SCAN_ORDER = ["UP", "RIGHT", "DOWN", "LEFT"]
        for _ in range(4):
            d = SCAN_ORDER[self._scan_idx % 4]
            self._scan_idx += 1
            r = self.controller.move_dir(d, frames=200)
            if r["moved"]:
                result = f"扇扫{d}✓"
                self._count_action("scan_" + d)
                return result
        self._count_action("scan_stuck")
        return "四方向全撞墙"

    # ---------- 界面处理 ----------

    def _handle_dialog(self, desc: str) -> str:
        """推进对话框直到关闭。

        关键：Emerald 对话文字逐字打字（~1.5s/页），打字期间按 A 只加速
        显示不翻页 → 必须先等文字区域稳定（打字完成）再按 A。
        （2026-08-06 实测：按太快导致对话永远翻不了页；等稳定必须只看
        文字区域 hash——NPC 动画让全屏 hash 永不稳定。）
        """
        import hashlib
        handled = 0
        for _ in range(20):  # 最多推进 20 页（长剧情对话）
            if not self.controller.dialog_open():
                break
            # 等文字区域稳定：hash 连续 4 次采样不变
            stable = 0
            for _ in range(40):  # 最多 40 次采样（~3.3s/页）
                tr = self.emu.screenshot()[96:158, 8:232]
                h1 = hashlib.sha256(tr.tobytes()).hexdigest()
                self.emu.run_frames(5)
                tr2 = self.emu.screenshot()[96:158, 8:232]
                if hashlib.sha256(tr2.tobytes()).hexdigest() == h1:
                    stable += 1
                    if stable >= 4:
                        break
                else:
                    stable = 0
            from src.emulator.keys import Key
            self.emu.press(Key.A, 8)
            self.emu.run_frames(30)
            handled += 1
            if handled % 3 == 0 and self.controller.dialog_open():
                # 每 3 页 LLM 确认对话框状态（防像素误判空转）
                d = parse_llm(self.vision.describe(
                    [self.emu.screenshot()],
                    '判断：画面底部有对话框（含对话文字的框）吗？'
                    '只输出JSON {"dialog":"true|false"}'))
                if d.get("dialog") != "true":
                    print("[dialog] LLM 确认对话框已关，停止推进")
                    break
            if handled >= 20:
                # 对话 20 页未关：保存现场供诊断
                from PIL import Image
                import numpy as np
                shot = self.emu.screenshot()
                p = Path(__file__).resolve().parent.parent.parent / "data" \
                    / "screenshots" / "dialog_stuck.png"
                p.parent.mkdir(parents=True, exist_ok=True)
                Image.fromarray(shot).save(p)
                print(f"[dialog] 20页未关闭，现场已存 {p}: "
                      f"bright={float(shot.mean()):.0f} "
                      f"文字行={int((shot[118:158, 8:232].mean(axis=2).max(axis=1) > 180).sum())}")
                break
        if handled:
            self._count_action("dialog")
        return f"对话推进{handled}页" if handled else "对话框已关"

    def _talk_npc(self, direction: str) -> str:
        """朝 NPC 方向走一步然后按 A 对话。"""
        if direction in DIR_KEY:
            self.controller.move_dir(direction, frames=40)
            self.emu.run_frames(20)
        # 按 A 尝试对话
        from src.emulator.keys import Key
        self.emu.press(Key.A, 8)
        self.emu.run_frames(40)
        if self.controller.dialog_open():
            result = self._handle_dialog("")
            self.knowledge.bump_counter("npc_talks")
            self.stats["npc_talks"] = self.knowledge.get_counter("npc_talks")
            self._remember(f"与NPC对话(累计{self.stats['npc_talks']})")
            return f"NPC对话✓(累计{self.stats['npc_talks']}) {result}"
        return "附近没有可对话的NPC"

    def _test_menu(self) -> str:
        """菜单开合测试：START 开 → LLM 验证 → B 关 → LLM 验证。

        （2026-08-06 修正：此 hack 菜单打开后画面变亮，像素亮度判定方向
        相反且室内场景误判，改用 LLM 界面类型验证。）
        """
        from src.emulator.keys import Key
        self.emu.press(Key.START, 8)
        self.emu.run_frames(30)
        d1 = parse_llm(self.vision.describe(
            [self.emu.screenshot()],
            '判断界面类型。只输出JSON {"screen":"主菜单|其他","text":"文字"}'))
        if d1.get("screen") != "主菜单":
            return f"菜单未打开 (LLM: {d1.get('text', '')[:30]})"
        self.emu.press(Key.B, 8)
        self.emu.run_frames(30)
        d2 = parse_llm(self.vision.describe(
            [self.emu.screenshot()],
            '判断界面类型。只输出JSON {"screen":"主菜单|其他"}'))
        if d2.get("screen") == "主菜单":
            return "菜单开了但关闭失败"
        self.knowledge.mark_goal("menu_tested")
        self.stats["menu_tested"] = True
        self._count_action("menu")
        return "菜单开合✓"

    # ---------- 主循环 ----------

    def step(self) -> dict:
        self.stats["steps"] += 1
        screen = self.emu.screenshot()
        prompt = EXPLORE_PROMPT.format(
            goal=self.goal,
            progress=self._progress_text(),
            recent=" | ".join(self.memory[-4:]) or "无",
        )
        text = self.vision.describe([screen], prompt)
        d = parse_llm(text)
        stype = d.get("screen", "其他")
        # 中文方向兼容（qwen 7b 常输出"上/下/左/右"而非 UP）
        ZH = {"上": "UP", "下": "DOWN", "左": "LEFT", "右": "RIGHT"}
        direction = ZH.get(d.get("direction", ""), d.get("direction", "none")).upper()
        npc_dir = ZH.get(d.get("npc_direction", ""), d.get("npc_direction", "none")).upper()
        note = d.get("note", "")
        if self.stats["steps"] % 5 == 0:
            print(f"  [llm] screen={stype} dir={direction} npc={npc_dir} {note[:40]}")
        # 像素判定为 ground truth：LLM 界面分类可能被画面误导
        # （2026-08-06 实测：LLM 把室内大地图误判为对话框）
        pixel_dialog = self.controller.dialog_open()
        if stype == "对话框" and not pixel_dialog:
            stype = "地图"
            note = f"(LLM误判对话框→地图) {note}"
        elif pixel_dialog and stype != "对话框":
            stype = "对话框"
            note = f"(像素检测到对话框) {note}"
        self._remember(f"{stype}[{direction}] {note}")

        result = ""
        if stype == "对话框" or stype == "对话":
            result = self._handle_dialog(d.get("text", ""))
        elif stype in ("地图", "大地图", "野外"):
            # 有 NPC → 尝试对话（优先）
            if npc_dir in DIR_KEY:
                result = self._talk_npc(npc_dir)
            elif direction in DIR_KEY:
                r = self.controller.move_dir(direction, frames=70)
                if r["moved"]:
                    self._stuck_dir = None
                    self._stuck_count = 0
                    result = f"移动{direction}✓"
                    self._count_action("move_" + direction)
                else:
                    # 撞墙惩罚：连续 3 次同方向撞墙 → 扇扫打破僵局
                    # （LLM 看静止画面会重复同一错误方向，2026-08-06 实测）
                    if getattr(self, "_stuck_dir", None) == direction:
                        self._stuck_count = getattr(self, "_stuck_count", 0) + 1
                    else:
                        self._stuck_dir = direction
                        self._stuck_count = 1
                    if self._stuck_count >= 3:
                        result = self._scan_sweep()
                        self._stuck_dir = None
                        self._stuck_count = 0
                    else:
                        result = f"移动{direction}（撞墙{self._stuck_count}/3）"
            else:
                result = self._scan_sweep()
            if d.get("town") == "true" and not self.knowledge.goal_done("reached_town"):
                self.knowledge.mark_goal("reached_town")
                self.stats["town"] = True
                self._status("🎯 到达城镇中心！")
        elif stype in ("主菜单", "菜单"):
            result = self._test_menu()
        elif stype in ("过场动画", "过场", "字幕"):
            self._status(f"过场中: {note[:40]}")
            b = NewGameBootstrap(self.emu, self.extractor, self.vision)
            b.advance_with_watchdog(60, on_change=lambda x, t: None)
            result = "过场推进60s"
        elif stype in ("战斗", "战斗界面"):
            self._count_action("battle")
            result = "⚠️ 战斗（Phase 2 处理），暂按B尝试逃跑"
            from src.emulator.keys import Key
            for _ in range(3):
                self.emu.press(Key.B, 8)
                self.emu.run_frames(30)
        else:
            self.emu.run_frames(30)
            result = f"界面[{stype}]等待"

        return {"screen": stype, "result": result, "note": note,
                "step": self.stats["steps"]}

    def run(self, max_steps: int = 60, on_step=None) -> dict:
        t0 = time.time()
        for _ in range(max_steps):
            r = self.step()
            self._status(f"步{r['step']} [{r['screen']}] {r['result']}")
            if on_step:
                on_step(r)
            if self.preview and self.preview.abort_requested():
                self._status("用户中止")
                break
            # DoD 达成检查
            if (self.knowledge.goal_done("reached_town")
                    and self.knowledge.get_counter("npc_talks") >= 2
                    and self.knowledge.goal_done("menu_tested")):
                self._status("🎉 Phase 1 DoD 全部达成！")
                break
        self.stats["seconds"] = time.time() - t0
        return self.stats
