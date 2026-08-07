"""屏幕处理：裁剪/区域提取/哈希（卡死检测与模板匹配用）。"""
from __future__ import annotations

import hashlib

import numpy as np

SCREEN_W, SCREEN_H = 240, 160


def dialog_box(screen: np.ndarray) -> np.ndarray:
    """对话盒区域：屏幕下方 1/4。"""
    return screen[SCREEN_H * 3 // 4:, :]


def screen_hash(screen: np.ndarray) -> str:
    """整屏像素哈希（卡死检测：位置不变 + 屏幕不变 = 无进展）。"""
    return hashlib.sha256(screen.tobytes()).hexdigest()[:16]


def region_hash(screen: np.ndarray, y0: int, y1: int, x0: int, x1: int) -> str:
    return hashlib.sha256(screen[y0:y1, x0:x1].tobytes()).hexdigest()[:16]


def diff_ratio(a: np.ndarray, b: np.ndarray) -> float:
    """两张截图不同像素占比。"""
    if a.shape != b.shape:
        return 1.0
    return float(np.mean(a != b))
