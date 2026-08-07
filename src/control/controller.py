"""控制器：把高层 Action 翻译为帧级按键序列。

移动：hold 方向 + 每帧读玩家坐标；pos 变化 = 移动成功；
     连续 N 帧不变 = 撞墙（触发绕行回退）。
对话/菜单：通过屏幕区域特征检测界面状态（对话框=底部暗色框，
     菜单=整体亮度骤降），不依赖 LLM（快、确定性）。
"""
from __future__ import annotations

import numpy as np

from src.brain.actions import Action, ActionType
from src.emulator.keys import Key
from src.emulator.mgba_core import Emulator
from src.state.extractor import GameState, GameStateExtractor

DIR_KEY = {
    "UP": Key.UP, "DOWN": Key.DOWN, "LEFT": Key.LEFT, "RIGHT": Key.RIGHT,
}

SCREEN_H = 160
DIALOG_Y0 = 120  # 对话框区域起始行
MENU_BRIGHTNESS_DROP = 25  # 菜单打开时平均亮度降幅


class Controller:
    def __init__(self, emu: Emulator, extractor: GameStateExtractor,
                 move_timeout_frames: int = 40):
        self.emu = emu
        self.extractor = extractor
        self.move_timeout = move_timeout_frames
        self._last_screen = None

    # ---------- 界面状态检测（纯像素，无 LLM） ----------

    def _dialog_box_ratio(self, screen: np.ndarray) -> float:
        """底部对话框区域深色像素占比（Emerald 对话框为深蓝底）。"""
        region = screen[DIALOG_Y0:, :]
        dark = (region.mean(axis=2) < 70).mean()
        return float(dark)

    def dialog_open(self, screen: np.ndarray | None = None) -> bool:
        """真实对话框判定（2026-08-06 修正）：亮度 + 深色底 + 亮文字行。

        旧判定（仅深色占比）在户外大地图误报——草地/树影也深色。
        Emerald 对话框必有白色文字（>180 亮行 ≥3 行），大地图底部无文字。
        行数上限：对话框文字 3-8 行；菜单列表/亮色图案 20+ 行（排除）。
        """
        screen = screen if screen is not None else self.emu.screenshot()
        if float(screen.mean()) < 60:
            return False
        if self._dialog_box_ratio(screen) < 0.25:
            return False
        bottom = screen[118:158, 8:232]
        gb = bottom.mean(axis=2)
        text_rows = int((gb.max(axis=1) > 180).sum())
        return 3 <= text_rows <= 15

    def menu_open(self, screen: np.ndarray | None = None) -> bool:
        screen = screen if screen is not None else self.emu.screenshot()
        return float(screen.mean()) < 140  # 菜单覆盖时整体变暗

    # ---------- 移动 ----------

    def move_dir(self, direction: str, frames: int = 120,
                 stop_when_blocked: bool = True) -> dict:
        """朝 direction 移动至多 frames 帧。

        返回 {"moved": bool, "frames_used": int, "start_pos": (x,y), "end_pos": (x,y),
              "blocked": bool}
        """
        key = DIR_KEY[direction.upper()]
        start = self.extractor.extract(self.emu)
        start_pos = (start.player_x, start.player_y)

        moved_any = False
        frames_used = 0
        blocked = False
        unchanged = 0
        self.emu.press_hold(key)
        try:
            for f in range(frames):
                self.emu.run_frames(1)
                frames_used += 1
                st = self.extractor.extract(self.emu)
                pos = (st.player_x, st.player_y)
                if pos != start_pos:
                    moved_any = True
                    unchanged = 0
                    start_pos = pos
                else:
                    unchanged += 1
                    if stop_when_blocked and unchanged >= self.move_timeout:
                        blocked = True
                        break
        finally:
            self.emu.release()

        end = self.extractor.extract(self.emu)
        return {
            "moved": moved_any,
            "frames_used": frames_used,
            "start_pos": start_pos,
            "end_pos": (end.player_x, end.player_y),
            "blocked": blocked,
        }

    def explore(self, max_frames: int = 600) -> dict:
        """探索式移动：直走到撞墙/地图变化，然后右转（右手法则）。

        返回 {"maps_crossed": int, "moved": bool}
        """
        direction = "RIGHT"
        total = 0
        maps_before = self.extractor.extract(self.emu).map_key
        while total < max_frames:
            r = self.move_dir(direction, frames=120)
            total += r["frames_used"]
            if r.get("maps_crossed"):
                break
            now = self.extractor.extract(self.emu)
            if now.map_key != maps_before:
                return {"maps_crossed": 1, "moved": True}
            if r["blocked"] or not r["moved"]:
                # 右转绕行（右手法则）
                direction = {"UP": "RIGHT", "RIGHT": "DOWN",
                             "DOWN": "LEFT", "LEFT": "UP"}[direction]
                # 撞墙后先小步试探，避免原地转圈
                self.move_dir(direction, frames=16)
        return {"maps_crossed": 0, "moved": total > 0}

    # ---------- 对话 / 确认 ----------

    def press_a_until_change(self, max_frames: int = 300) -> dict:
        """按 A 并等待屏幕/界面状态变化（推进对话或菜单选择）。"""
        before = self.emu.screenshot()
        before_dialog = self.dialog_open(before)
        before_hash = _hash_screen(before)
        self.emu.press(Key.A, 8)
        changed = False
        for _ in range(max_frames):
            self.emu.run_frames(4)
            now = self.emu.screenshot()
            if _hash_screen(now) != before_hash or self.dialog_open(now) != before_dialog:
                changed = True
                break
        return {"changed": changed, "dialog": self.dialog_open()}

    def mash_a(self, frames: int) -> None:
        """连按 A（跳过剧情/对话流）。"""
        steps = frames // 40
        for _ in range(steps):
            self.emu.press(Key.A, 8)
            self.emu.run_frames(32)

    # ---------- 菜单 ----------

    def toggle_menu(self) -> dict:
        """START 开/关菜单。"""
        before = float(self.emu.screenshot().mean())
        self.emu.press(Key.START, 8)
        self.emu.run_frames(30)
        after = float(self.emu.screenshot().mean())
        return {"opened": after < before - MENU_BRIGHTNESS_DROP}

    def close_menu(self) -> dict:
        self.emu.press(Key.B, 8)
        self.emu.run_frames(30)
        return {"closed": not self.menu_open()}


def _hash_screen(screen: np.ndarray) -> str:
    import hashlib
    return hashlib.sha256(screen.tobytes()).hexdigest()[:12]
