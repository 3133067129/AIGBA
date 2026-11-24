"""视觉玩家定位：主角精灵模板匹配（纯 numpy，无内存依赖）。

原理：主角精灵在画面中唯一（16px 格精灵），用 SAD（绝对差和）模板匹配
在 240x160 截图中定位。模板来源：可动点截图时自动截取（玩家被游戏渲染在
屏幕中央区域）或手动提供。

局限：对话/菜单/转场中玩家隐藏 → 匹配失败返回 None；NPC 与玩家同模组时
可能误匹配（用最近位置约束）。
"""
from __future__ import annotations

import numpy as np

SPRITE = 16  # 玩家精灵像素尺寸（240x160 坐标下）


class PlayerTracker:
    def __init__(self, template_size: int = SPRITE):
        self.template: np.ndarray | None = None  # HxWx3
        self.pos: tuple[int, int] | None = None  # 精灵左上角 (x, y)
        self.template_size = template_size

    # ---------- 初始化 ----------

    def init_from_screen(self, screen: np.ndarray,
                         center: tuple[int, int] | None = None) -> bool:
        """从截图初始化模板。

        center: 玩家精灵中心（游戏画面坐标）。默认屏幕中心 (120, 80)
        —— 可动状态下玩家被渲染在屏幕中央附近。
        """
        cx, cy = center or (120, 80)
        s = self.template_size
        h, w = screen.shape[:2]
        x0 = max(0, cx - s // 2)
        y0 = max(0, cy - s // 2)
        if x0 + s > w or y0 + s > h:
            return False
        self.template = screen[y0:y0 + s, x0:x0 + s].copy()
        self.pos = (x0, y0)
        return True

    def set_template(self, template: np.ndarray) -> None:
        """手动设置模板（多场景模板库时用）。"""
        self.template = template.copy()
        self.template_size = template.shape[0]

    # ---------- 定位 ----------

    def locate(self, screen: np.ndarray,
               search_radius: int | None = None,
               max_shift: int = 48) -> tuple[int, int] | None:
        """SAD 模板匹配，返回精灵左上角 (x, y)；失败返回 None。

        search_radius: 只在前次位置附近搜索（默认 ±max_shift 像素，防 NPC 误匹配）。
        """
        if self.template is None:
            return None
        s = self.template_size
        h, w = screen.shape[:2]
        if self.pos is not None and search_radius is None:
            search_radius = max_shift
        if search_radius is not None and self.pos is not None:
            x0 = max(0, self.pos[0] - search_radius)
            y0 = max(0, self.pos[1] - search_radius)
            x1 = min(w - s, self.pos[0] + search_radius)
            y1 = min(h - s, self.pos[1] + search_radius)
        else:
            x0, y0, x1, y1 = 0, 0, w - s, h - s
        region = screen[y0:y1 + s, x0:x1 + s]
        # SAD 滑窗：对每个候选位置求模板与区域子块的绝对差和
        best = None
        best_score = float("inf")
        for dy in range(0, y1 - y0 + 1, 2):  # 步长 2 提速（16px 精灵足够）
            for dx in range(0, x1 - x0 + 1, 2):
                sub = region[dy:dy + s, dx:dx + s]
                if sub.shape != self.template.shape:
                    continue
                sad = float(np.abs(sub.astype(np.int16) -
                                   self.template.astype(np.int16)).sum())
                if sad < best_score:
                    best_score = sad
                    best = (x0 + dx, y0 + dy)
        if best is None:
            return None
        self.pos = best
        return best

    # ---------- 移动判定 ----------

    def moved_toward(self, screen: np.ndarray, direction: str) -> bool:
        """移动后判定：新位置相对旧位置是否朝 direction 位移 ≥4px。

        direction: UP/DOWN/LEFT/RIGHT（精灵左上角坐标系：UP=dy<0）
        """
        if self.pos is None:
            return False
        old = self.pos
        new = self.locate(screen)
        if new is None:
            return False
        dx, dy = new[0] - old[0], new[1] - old[1]
        if direction == "UP":
            return dy < -4
        if direction == "DOWN":
            return dy > 4
        if direction == "LEFT":
            return dx < -4
        if direction == "RIGHT":
            return dx > 4
        return False
