"""新游戏引导：标题 → 菜单（新游戏/设置）→ 开场对话 → 进入游戏。

经验证的流程（2026-08-06 实测，此 hack 标题无 PRESS START、菜单在变焦后
以特定按键序列打开）：
  1. 标题按 A（触发 logo 变焦动画）
  2. 等 ~200 帧（变焦1 完成，进入暗屏）
  3. 暗屏阶段按 DOWN+A 两次（第二次后菜单出现，bright~181）
  4. 菜单（新游戏/设置）按 A 直接选「新游戏」（光标默认第一项）
  5. 黑屏过渡 → 淡入 → 博士开场对话
"""
from __future__ import annotations

import hashlib

import numpy as np

from src.emulator.keys import Key
from src.emulator.mgba_core import Emulator
from src.perception.llm_vision import VisionProvider
from src.state.extractor import GameStateExtractor

MENU_BRIGHT_MIN, MENU_BRIGHT_MAX = 150, 200
DIALOG_DARK_RATIO = 0.25


class NewGameBootstrap:
    def __init__(self, emu: Emulator, extractor: GameStateExtractor,
                 vision: VisionProvider):
        self.emu = emu
        self.extractor = extractor
        self.vision = vision

    # ---------- 基础检测 ----------

    def _brightness(self) -> float:
        return float(self.emu.screenshot().mean())

    def _text_rows_in(self, y0: int, y1: int) -> int:
        g = self.emu.screenshot().mean(axis=2)
        return int(sum(1 for y in range(y0, y1) if g[y].min() < 60))

    def is_title(self) -> bool:
        """真实标题：暗底 + logo 文字行 + 长时间静止（>3s 不变）。"""
        if self._brightness() >= 70:
            return False
        if self._text_rows_in(30, 100) < 10:
            return False
        h1 = hashlib.sha256(self.emu.screenshot().tobytes()).hexdigest()[:16]
        self.emu.run_frames(190)
        h2 = hashlib.sha256(self.emu.screenshot().tobytes()).hexdigest()[:16]
        return h1 == h2

    def is_menu(self) -> bool:
        b = self._brightness()
        return MENU_BRIGHT_MIN < b < MENU_BRIGHT_MAX

    def is_black(self) -> bool:
        return self._brightness() < 30

    def dialog_open(self) -> bool:
        """真实对话框：画面较亮（>60）且底部有深色对话框框体。

        （剧情字幕是暗屏 bright~20 + 底部文字，误判会触发按键导致
        动画重放——必须用亮屏门槛区分。）
        """
        screen = self.emu.screenshot()
        if screen.mean() < 60:
            return False
        g = screen.mean(axis=2)
        dark = float((g[120:, :] < 70).mean())
        return dark > DIALOG_DARK_RATIO

    def _wait_until(self, cond, timeout_frames: int, step: int = 20) -> bool:
        waited = 0
        while waited < timeout_frames:
            if cond():
                return True
            self.emu.run_frames(step)
            waited += step
        return cond()

    def run_frames_quiet(self, frames: int) -> None:
        """静默跑帧（供外部等待动画播放）。"""
        self.emu.run_frames(frames)

    # ---------- 流程 ----------

    def boot_to_title(self, timeout_frames: int = 9000) -> bool:
        """跑帧直到标题出现。"""
        print("[newgame] booting to title...")
        return self._wait_until(self.is_title, timeout_frames, step=60)

    def _check_screen(self, tag: str) -> str:
        """纯像素判定当前界面：'menu'（有新游戏）/ 'other'。

        2026-08-06 修正：去掉 LLM（Ollama GPU 故障后 CPU 推理 96s/次太慢）。
        菜单判定 = 亮度窗口 150-200（真实菜单 bright~181，标题 logo 仅 ~106）
        + 底部有文字行（选项列表）。'settings' 不再区分（误入按 B 退出）。
        """
        bright = self._brightness()
        is_menu = self.is_menu()  # 亮度窗口 150-200
        text_rows = self._text_rows_in(100, 158)
        kind = "menu" if (is_menu and text_rows >= 3) else "other"
        print(f"[newgame] {tag}: bright={bright:.0f} textrows={text_rows} → {kind}")
        return kind

    def _exit_settings(self) -> None:
        """从设置界面退出（B 键）。"""
        for _ in range(3):
            self.emu.press(Key.B, 10)
            self.emu.run_frames(40)

    def start_new_game(self, max_attempts: int = 6) -> bool:
        """标题 → 变焦 → DOWN+A×2 → 菜单 → A 选新游戏。

        2026-08-06 确定性序列（debug_title/debug_menu 实证）：
          1. 标题按 A（触发 logo 变焦）
          2. 等 300 帧（变焦完，画面稳定 bright~111）
          3. DOWN+A ×2（第二次后菜单出现 bright~173，光标默认「新游戏」）
          4. 菜单上直接按 A = 选「新游戏」（黑屏过场开始）
        纯像素判定（LLM 曾把变焦画面幻觉成菜单导致误按）。
        """
        print("[newgame] title -> zoom -> DOWN+A x2 -> menu")
        for attempt in range(max_attempts):
            # 1. 按 A 触发变焦
            self.emu.press(Key.A, 10)
            self.emu.run_frames(300)  # 变焦完
            # 2. DOWN+A ×2 进菜单
            self.emu.press(Key.DOWN, 8)
            self.emu.press(Key.A, 10)
            self.emu.run_frames(60)
            self.emu.press(Key.DOWN, 8)
            self.emu.press(Key.A, 10)
            # 3. 等菜单（最长 90s）
            menu_found = False
            waited = 0
            while waited < 5400:
                self.emu.run_frames(90)
                waited += 90
                if self.is_menu():
                    menu_found = True
                    break
                if self._brightness() < 60:
                    break  # 黑屏 = 已进入游戏
            if not menu_found:
                print(f"[newgame] attempt{attempt}: 菜单未出现")
                continue
            # 4. 选「新游戏」（光标默认第一项）
            self.emu.press(Key.A, 10)
            self.emu.run_frames(300)
            if self._brightness() < 60:
                print(f"[newgame] 新游戏已开始 (attempt{attempt})")
                return True
            print(f"[newgame] attempt{attempt}: A 后未进入游戏")
        return False

    def advance_dialog(self, max_frames: int = 600) -> bool:
        """对话框驱动推进：对话框开着就按 A，等它消失再继续。
        返回是否处理了至少一个对话框。"""
        handled = False
        waited = 0
        while waited < max_frames:
            if self.dialog_open():
                self.emu.press(Key.A, 8)
                self.emu.run_frames(40)
                handled = True
                # 等对话框消失（文字逐字显示）
                for _ in range(30):
                    if not self.dialog_open():
                        break
                    self.emu.run_frames(10)
            else:
                self.emu.run_frames(30)
            waited += 30
        return handled

    def is_waiting_dialogue(self) -> bool:
        """等待输入的对话检测（2026-08-06 实证有效）。

        原理：等待对话的文字区域基本静止（仅 ▼ 箭头闪烁，众数判定容差）；
        过场字幕/叙述动画的文字区域持续变化。
        文字区域覆盖下半屏 (96:158)——等待点可能是底部对话框
        （y~128-152）或居中式字幕（y~100-107，如房间场景）。
        判据：6 次采样中任一 hash 出现 >= 3 次。
        """
        import hashlib
        from collections import Counter
        s = self.emu.screenshot()
        tr = s[96:158, 8:232]
        if (tr > 120).sum() < 100:  # 无文字（黑屏/纯字幕）
            return False
        hashes = []
        for _ in range(6):
            self.emu.run_frames(8)
            tr = self.emu.screenshot()[96:158, 8:232]
            hashes.append(hashlib.sha256(tr.tobytes()).hexdigest())
        return Counter(hashes).most_common(1)[0][1] >= 3

    def advance_with_watchdog(self, max_seconds: float, on_change=None) -> dict:
        """推进开场：等待对话检测 + 叙述重放看门狗。

        看门狗：按 A 后若画面持续动画 >15s（说明误按导致叙述重放），
        锁定按键 45s，让动画自然播放完。
        """
        import hashlib
        import time

        def _animating() -> bool:
            h1 = hashlib.sha256(self.emu.screenshot().tobytes()).hexdigest()
            self.emu.run_frames(10)
            h2 = hashlib.sha256(self.emu.screenshot().tobytes()).hexdigest()
            return h1 != h2

        t0 = time.time()
        last_a = 0.0
        lock_until = 0.0
        anim_since = None
        prev = ""
        a_presses = 0
        while time.time() - t0 < max_seconds:
            now = time.time()
            if now < lock_until:
                self.emu.run_frames(30)
                continue
            if self.is_waiting_dialogue():
                anim_since = None
                if now - last_a > 1.5:
                    self.emu.press(Key.A, 8)
                    self.emu.run_frames(40)
                    last_a = now
                    a_presses += 1
            else:
                if _animating():
                    if anim_since is None:
                        anim_since = now
                    elif now - anim_since > 15:
                        # 按 A 后持续动画 = 叙述被重放 → 锁定 45s
                        lock_until = now + 45
                        anim_since = None
                else:
                    anim_since = None
                self.emu.run_frames(30)
            if on_change and int(now - t0) % 30 == 0:
                desc = self.vision.describe(
                    [self.emu.screenshot()], "一句话+文字")[:100]
                if desc != prev:
                    prev = desc
                    on_change(desc, int(now - t0))
        return {"seconds": time.time() - t0, "a_presses": a_presses}

    def advance_policy(self, max_seconds: float, on_change=None) -> dict:
        """最终推进策略（2026-08-06 实测有效）：

        - 对话框开着 → 按 A（节流 ~0.8s/次，防太快）
        - 无对话框 + 画面动画中 → 等待（叙述动画期间按 A 会重启动画！）
        - 无对话框 + 静止 → 按 A（菜单/选择界面，默认第一项）
        - 动画超长（>5 分钟）→ 强制按 A 一次（防假死）

        on_change(desc, screen, elapsed) 在画面变化时回调。
        返回 {"seconds": ..., "a_presses": ...}
        """
        import hashlib
        import time

        def _is_animating() -> bool:
            h1 = hashlib.sha256(self.emu.screenshot().tobytes()).hexdigest()
            self.emu.run_frames(15)
            h2 = hashlib.sha256(self.emu.screenshot().tobytes()).hexdigest()
            return h1 != h2

        t0 = time.time()
        prev_desc = ""
        last_a = 0.0
        waits = 0
        a_presses = 0
        while time.time() - t0 < max_seconds:
            now = time.time()
            if self.dialog_open():
                if now - last_a > 0.8:
                    self.emu.press(Key.A, 8)
                    self.emu.run_frames(40)
                    last_a = now
                    a_presses += 1
                    waits = 0
            elif _is_animating():
                waits += 1
                self.emu.run_frames(45)
                if waits > 400:  # 动画超长，强制按键防假死
                    self.emu.press(Key.A, 8)
                    waits = 0
            else:
                self.emu.press(Key.A, 8)
                self.emu.run_frames(40)
                last_a = now
                a_presses += 1
            if on_change and int(now - t0) % 15 == 0:
                desc = self.vision.describe(
                    [self.emu.screenshot()], "一句话+关键文字")[:110]
                if desc != prev_desc:
                    prev_desc = desc
                    on_change(desc, int(now - t0))
        return {"seconds": time.time() - t0, "a_presses": a_presses}
