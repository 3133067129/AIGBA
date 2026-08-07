"""实时预览窗（pygame）：把模拟器画面放大显示 + 底部 HUD 状态条。

用法：
    preview = PreviewWindow()
    emu.on_frame = lambda e: preview.push(e.screenshot())
    ...
    preview.set_status("正在推进开场...")
    if preview.abort_requested():   # 用户按 ESC 可中止流程
        break
    preview.close()

窗口线程安全说明：push 只在本进程主线程调用（模拟器单线程），无锁。
"""
from __future__ import annotations

import pygame

# 中文字体候选（Windows），找不到则回退默认（中文会显示为方块）
_FONT_CANDIDATES = ["microsoftyahei", "simhei", "msyh", "dengxian", "simsun"]

HUD_HEIGHT = 44  # 底部状态条高度（放大后坐标）
HUD_LINES = 2    # 显示的状态行数


class PreviewWindow:
    """键位：方向键/A/B/回车/退格 = 人工接管（自动暂停 AI，直接操控模拟器）；
    +/- 调整倍速，p 暂停/继续，ESC 退出。"""

    # pygame 键 -> 模拟器键（人工接管用）
    _KEY_MAP = {
        pygame.K_UP: 0, pygame.K_DOWN: 1, pygame.K_LEFT: 2, pygame.K_RIGHT: 3,
        pygame.K_a: 4, pygame.K_x: 4,  # A
        pygame.K_b: 5, pygame.K_z: 5,  # B
        pygame.K_RETURN: 6, pygame.K_KP_ENTER: 6,  # START
        pygame.K_BACKSPACE: 7,  # SELECT
    }

    def __init__(self, scale: int = 4, title: str = "AI 玩宝可梦绿宝石386",
                 speed: float = 1.0, emu=None, on_key=None, auto_pause: bool = True):
        self.scale = scale
        self.closed = False
        # 倍速：1.0 = 60fps 实时；n = n 倍速（模拟器帧率 = 60*n）
        self.speed = max(0.5, min(30.0, float(speed)))
        self.paused = False
        self.emu = emu  # 人工接管：按键转发到模拟器（可为 None）
        self._on_key = on_key  # 可选回调 on_key(pygame_keycode)：所有 KEYDOWN 都通知
        self._auto_pause = auto_pause
        # True（默认）= 接管键按下时自动暂停 AI（演示接管场景）
        # False = 接管键不暂停，模拟器持续推进（人工实玩/录制场景）
        self._held: dict = {}  # pygame key -> 模拟器 Key 常量（按住中）
        pygame.init()
        info = pygame.display.Info()
        max_w, max_h = info.current_w, info.current_h
        # 高度 960 + HUD 可能超出小屏，按可用区域自动降档
        while (160 * scale > max_w or (240 + HUD_HEIGHT) * scale > max_h) and scale > 2:
            scale -= 1
        self.scale = scale
        self.screen = pygame.display.set_mode(
            (160 * scale, (240 + HUD_HEIGHT) * scale),
            pygame.RESIZABLE)
        pygame.display.set_caption(title)
        self._font = None
        for name in _FONT_CANDIDATES:
            f = pygame.font.SysFont(name, 16)
            if f is not None:
                self._font = f
                break
        if self._font is None:
            self._font = pygame.font.Font(None, 16)
        self._status_lines: list[str] = []
        self._clock = pygame.time.Clock()

    # ---------- 显示 ----------

    def push(self, frame, status: str | None = None) -> None:
        """推送一帧画面（numpy HxWx3 uint8 RGB）。

        注意：pygame tick 直接限制模拟器帧率——tick(60*speed) = 倍速。
        （2026-08-06 修正：旧 tick(60) 把模拟器锁死在 1x。）
        """
        if self.closed:
            return
        if self.paused:
            self._poll()
            import time
            time.sleep(0.15)  # 暂停：拖慢模拟器帧循环
            return
        if status is not None:
            self._status_lines.append(status)
            self._status_lines = self._status_lines[-HUD_LINES:]
        h, w = frame.shape[:2]
        surf = pygame.image.frombuffer(frame.tobytes(), (w, h), "RGB")
        surf = pygame.transform.scale(surf, (w * self.scale, h * self.scale))
        self.screen.blit(surf, (0, 0))
        self._draw_hud()
        pygame.display.flip()
        self._clock.tick(60 * self.speed)
        self._poll()

    def set_status(self, text: str) -> None:
        """设置 HUD 状态行（下一条帧推送时显示）。"""
        if self.closed:
            return
        self._status_lines.append(text)
        self._status_lines = self._status_lines[-HUD_LINES:]

    def _draw_hud(self) -> None:
        s = self.screen
        rect = pygame.Rect(0, 240 * self.scale, s.get_width(), HUD_HEIGHT * self.scale)
        pygame.draw.rect(s, (16, 16, 24), rect)
        y = rect.y + 4
        # 第一行：倍速状态
        state = f"⏸ {self.speed:.1f}x  (+/-调速 p暂停)" if self.paused \
            else f"{self.speed:.1f}x  (+/-调速 p暂停)"
        txt = self._font.render(state, True, (255, 220, 120))
        s.blit(txt, (8, y))
        y += 18
        for line in self._status_lines:
            txt = self._font.render(line[:80], True, (220, 220, 220))
            s.blit(txt, (8, y))
            y += 18

    # ---------- 交互 ----------

    def _poll(self) -> None:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                self.closed = True
            elif ev.type == pygame.KEYDOWN:
                if self._on_key is not None:
                    self._on_key(ev.key)  # 标签键等外部用途（在分支处理前通知）
                if ev.key == pygame.K_ESCAPE:
                    self.closed = True
                elif ev.key in (pygame.K_PLUS, pygame.K_KP_PLUS, pygame.K_EQUALS):
                    self.set_speed(self.speed * 1.5)
                elif ev.key in (pygame.K_MINUS, pygame.K_KP_MINUS):
                    self.set_speed(self.speed / 1.5)
                elif ev.key == pygame.K_p:
                    self.paused = not self.paused
                elif ev.key in self._KEY_MAP and self.emu is not None:
                    # 人工接管：按住键 = 按住模拟器按键（可自动暂停 AI）
                    if self._auto_pause:
                        self.paused = True
                    from src.emulator.keys import Key
                    emu_key = [Key.UP, Key.DOWN, Key.LEFT, Key.RIGHT,
                               Key.A, Key.B, Key.START, Key.SELECT][self._KEY_MAP[ev.key]]
                    self.emu.press_hold(emu_key)
                    self._held[ev.key] = emu_key
                    self._status_lines.append(f"👆 人工接管: {emu_key.name} 按住中")
            elif ev.type == pygame.KEYUP:
                if ev.key in self._held:
                    self.emu.release()
                    del self._held[ev.key]

    def set_speed(self, speed: float) -> None:
        """调整倍速（0.5x ~ 30x），实时生效。"""
        self.speed = max(0.5, min(30.0, float(speed)))

    def abort_requested(self) -> bool:
        """用户按了 ESC / 点了关闭 → 外部流程应中止。"""
        if not self.closed:
            self._poll()
        return self.closed

    def close(self) -> None:
        self.closed = True
        try:
            pygame.display.quit()
        except Exception:
            pass
