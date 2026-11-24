"""视觉控制器：纯画面变化判定移动/撞墙/对话（无内存依赖）。

backend 协议（WindowBackend 或 Emulator 都满足）：
- screenshot() -> np.ndarray 240x160x3
- press_hold(Key) / release() / run_frames(n)（n 帧 = n/60 秒）
- press(Key, frames)

移动判定：按方向键后画面变化率 > 阈值 = 移动成功（背景滚动）；
< 阈值 = 撞墙/锁。阈值标定（2F 家内实测）：撞墙 0.00%，移动 14-19%。
户外（未白镇）有 NPC 动画，静止画面也会微变（~5%）——户外阈值需调高。
"""
from __future__ import annotations

import numpy as np

from src.emulator.keys import Key
from src.perception.screen import diff_ratio

DIR_KEY = {"UP": Key.UP, "DOWN": Key.DOWN, "LEFT": Key.LEFT, "RIGHT": Key.RIGHT}
BACK = {"UP": "DOWN", "DOWN": "UP", "LEFT": "RIGHT", "RIGHT": "LEFT"}

MOVE_DIFF_THRESHOLD = 0.02     # > 2% 变化 = 移动成功（室内标定）
OUTDOOR_THRESHOLD = 0.08       # 户外 NPC 动画干扰大，阈值调高
OUTDOOR_STILL_BASE = 0.05      # 户外静止画面自身变化 ~5%（用于判别）

HOLD_FRAMES = 25               # 按方向键时长（25 帧 ≈ 0.42s，走一格）
SETTLE_FRAMES = 10             # 松键后稳定帧


class VisualController:
    def __init__(self, backend, outdoor: bool = False):
        self.backend = backend
        self.outdoor = outdoor
        self.threshold = OUTDOOR_THRESHOLD if outdoor else MOVE_DIFF_THRESHOLD

    # ---------- 移动 ----------

    def move_dir(self, direction: str, hold_frames: int = HOLD_FRAMES,
                 retries: int = 2) -> dict:
        """按方向键 → 画面变化判定移动成功。

        返回 {'moved': bool, 'diff': float, 'dir': direction}
        """
        b0 = self.backend.screenshot()
        diff = 0.0
        for _ in range(retries):
            self.backend.press_hold(DIR_KEY[direction])
            self.backend.run_frames(hold_frames)
            self.backend.release()
            self.backend.run_frames(SETTLE_FRAMES)
            b1 = self.backend.screenshot()
            diff = diff_ratio(b0, b1)
            if diff > self.threshold:
                return {"moved": True, "diff": diff, "dir": direction}
        return {"moved": False, "diff": diff, "dir": direction}

    def move_back(self, direction: str) -> dict:
        """朝 direction 的反方向退一格（导航回退用）。"""
        return self.move_dir(BACK[direction])

    # ---------- 可动检测（视觉版 real_move_any）----------

    def detect_controllable(self, max_seconds: float = 900,
                            advance: callable = None) -> bool:
        """推进开场直到视觉可动：画面静止时按方向键产生大变化 = 可动。

        画面持续动画（开场推进中）→ 调 advance 推进对话。
        返回是否检测到可动。可动后立即返回（不再推进，避免触发剧情锁）。
        """
        import time
        from src.brain.new_game import NewGameBootstrap
        if advance is None:
            advance = NewGameBootstrap(self.backend, None, None).advance_with_watchdog
        t0 = time.time()
        while time.time() - t0 < max_seconds:
            if self.screen_still(samples=3, gap_frames=20):
                for d in ("UP", "DOWN", "LEFT", "RIGHT"):
                    r = self.move_dir(d, hold_frames=25)
                    if r["moved"]:
                        # 可动确认后回退一格并返回（不继续推进）
                        self.move_dir(BACK[d])
                        return True
            else:
                advance(60)
        return False

    # ---------- 状态判定（纯画面）----------

    def screen_still(self, samples: int = 3, gap_frames: int = 20) -> bool:
        """画面是否静止（无动画/无移动）。"""
        prev = self.backend.screenshot()
        for _ in range(samples):
            self.backend.run_frames(gap_frames)
            cur = self.backend.screenshot()
            d = diff_ratio(prev, cur)
            if d > self.threshold:
                return False
            prev = cur
        return True

    # ---------- 格级探索（DFS 思想的视觉版）----------

    def explore(self, max_steps: int = 400) -> dict:
        """右墙法则视觉探索：朝一个方向走，撞墙右转。

        返回 {'steps': int, 'visited': int}
        """
        facing = "UP"
        visited = 0
        steps = 0
        while steps < max_steps:
            # 尝试：右转 → 直行 → 左转 → 后退
            right = {"UP": "RIGHT", "RIGHT": "DOWN",
                     "DOWN": "LEFT", "LEFT": "UP"}[facing]
            left = {"UP": "LEFT", "LEFT": "DOWN",
                    "DOWN": "RIGHT", "RIGHT": "UP"}[facing]
            moved = False
            for d in (right, facing, left, BACK[facing]):
                r = self.move_dir(d)
                if r["moved"]:
                    facing = d
                    visited += 1
                    moved = True
                    break
            if not moved:
                break
            steps += 1
        return {"steps": steps, "visited": visited}
