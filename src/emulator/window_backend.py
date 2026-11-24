"""mGBA 真实窗口后端 —— 纯视觉+键鼠方案的核心层。

替代 mgba_core.py 的 Emulator 接口面（screenshot/run_frames/press/press_hold/
release/save_state/load_state），实现同签名，使 controller/brain 层机械迁移。
完全不用内存读写：感知走窗口抓屏，输入走 SendInput 模拟键鼠。

接口语义（与无头版的关键差异）：
- run_frames(n) = sleep(n/60)（帧→时间换算，游戏 60fps）
- screenshot() = 抓 mGBA 窗口客户区 → 缩放回 240x160x3
- press/press_hold/release = SendInput 键盘（mGBA 默认绑定）
- save_state/load_state = mGBA savestate 快捷键（F1 存 / Shift+F1 载）

模块级工具（旁路录制/回放复用）：
- find_window(title_substr)：按标题找 mGBA 窗口
- capture_hwnd(hwnd)：抓客户区 → 240x160x3 uint8（PrintWindow 优先，BitBlt 兜底）
- send_vk(vk, up, hwnd)：PostMessage 直发目标窗口（无需前台/注入；本机火绒 HIPS 拦
  SendInput，2026-08-08 实测 0/87 全失败——所以窗口键鼠一律走 PostMessage）
"""
from __future__ import annotations

import ctypes
import subprocess
import time
from pathlib import Path

import numpy as np
from PIL import Image

import win32con
import win32gui
import win32ui

from .keys import Key

# ---------- SendInput 结构 ----------
# 注意：结构体打包必须用 MS 的 SIZE 布局（32 位字段对齐），ctypes 默认对齐在
# 64 位 Python 下是正确的（LONG=4，指针 8 —— KEYBDINPUT 全 32 位字段，无指针）。

ULONG_PTR = ctypes.POINTER(ctypes.c_ulong)  # 实际用 c_size_t
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ULONG_PTR),
    ]


class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_ulong),
        ("ki", KEYBDINPUT),
    ]


# ---------- mGBA 默认键盘绑定（Phase A 实测确认）----------
# mGBA 0.10 默认：方向键=方向键, A=Z, B=X, L=A, R=S,
#                Start=Enter, Select=Backspace, F1=存槽1, Shift+F1=载槽1
VK = {
    Key.UP: 0x26, Key.DOWN: 0x28, Key.LEFT: 0x25, Key.RIGHT: 0x27,
    # mGBA 默认键盘是 QZ 布局（A=X、B=Z、L=A、R=S），与 VBA（Z=A/X=B）相反——
    # 2026-08-08 对照 config.ini [gba.input.QT_K] 核实：keyA=88('X') keyB=90('Z')
    Key.A: ord('X'), Key.B: ord('Z'),
    Key.START: 0x0D, Key.SELECT: 0x08,   # Enter / Backspace
    Key.L: ord('A'), Key.R: ord('S'),
}
VK_F1 = 0x70
VK_LSHIFT = 0xA0

# 扩展键（lParam bit24 = 0x01000000）：方向键 0x25-0x28、右侧 Ctrl/Alt、小键盘等。
# 真实键盘事件中方向键带扩展位；PostMessage 若缺该位，Qt 的 Windows 键盘翻译
# 认不出 VK_UP/DOWN/LEFT/RIGHT → 按键静默无效（2026-08-08 实测：调钟界面里的
# LEFT/DOWN 不生效导致回放卡死在调钟界面 40s+，全段验证 55s 处发散）
EXTENDED_VK = {0x25, 0x26, 0x27, 0x28}
# 扩展键的扫描码（MapVirtualKey 对扩展 VK 返回的就是这些扩展扫描码）
# 0x48=UP 0x50=DOWN 0x4B=LEFT 0x4D=RIGHT


class WindowError(RuntimeError):
    pass


# ---------- 模块级窗口工具（旁路录制/回放复用）----------

def find_window(title_substr: str) -> int | None:
    """按标题找窗口（标题含 ROM 名或 'mGBA'）。返回 hwnd 或 None。"""
    found = []

    def cb(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd)
        if title and (title_substr[:20] in title or "mGBA" in title):
            found.append((hwnd, title))
    win32gui.EnumWindows(cb, None)
    return found[0][0] if found else None


def _capture(hwnd: int, print_window: bool):
    """抓窗口客户区。print_window=True 用 PrintWindow(PW_RENDERFULLCONTENT)。"""
    try:
        left, top, right, bottom = win32gui.GetClientRect(hwnd)
        w, h = right - left, bottom - top
        if w <= 0 or h <= 0:
            return None
        hwnd_dc = win32gui.GetWindowDC(hwnd)
        mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
        save_dc = mfc_dc.CreateCompatibleDC()
        bmp = win32ui.CreateBitmap()
        bmp.CreateCompatibleBitmap(mfc_dc, w, h)
        save_dc.SelectObject(bmp)
        flags = 2  # PW_RENDERFULLCONTENT
        if print_window:
            # pywin32 无 PrintWindow，直接 ctypes 调 user32
            result = ctypes.windll.user32.PrintWindow(
                hwnd, save_dc.GetSafeHdc(), flags)
        else:
            result = ctypes.windll.gdi32.BitBlt(
                save_dc.GetSafeHdc(), 0, 0, w, h,
                hwnd_dc, 0, 0, win32con.SRCCOPY)
        if not result:
            return None
        bits = bmp.GetBitmapBits(True)
        img = Image.frombuffer("RGB", (w, h), bits, "raw", "BGRX", 0, 1)
        save_dc.DeleteDC()
        mfc_dc.DeleteDC()
        win32gui.ReleaseDC(hwnd, hwnd_dc)
        return img
    except Exception:
        return None


def capture_hwnd(hwnd: int, retries: int = 3) -> np.ndarray | None:
    """抓窗口客户区 → 240x160x3 uint8 RGB；失败返回 None。

    PrintWindow 优先（不要求前台），全黑时回退 BitBlt（需窗口可见）。
    调用方负责在抓屏前 activate()（窗口无焦点时不重绘会拿到旧帧/黑帧）。
    """
    if not hwnd:
        return None
    for attempt in range(retries):
        img = _capture(hwnd, print_window=True)
        if img is None or float(np.asarray(img).mean()) < 1.0:
            img = _capture(hwnd, print_window=False)
        if img is not None and float(np.asarray(img).mean()) >= 1.0:
            break
        img = None
        time.sleep(0.3)
    if img is None:
        return None
    img = img.convert("RGB").resize((240, 160), Image.NEAREST)
    return np.asarray(img, dtype=np.uint8)


def send_vk(vk: int, up: bool, hwnd: int | None = None) -> None:
    """发送单个虚拟键。

    有 hwnd：PostMessage 直发目标窗口（不依赖前台/注入）。
    无 hwnd：退回 SendInput（兼容无窗口调用方）。

    注意：本机火绒 HIPS（hipsdaemon.exe）会拦截 SendInput —— 2026-08-08 实测
    全部返回 0/ERROR_INVALID_PARAMETER（连记事本都拦），导致三次回放验证的
    按键全部静默丢失（"开场 12s 对齐"只是自动播放的开场动画）。PostMessage
    是 WM_KEY* 消息直投，绕过注入拦截，对 mGBA(Qt) 实测有效。
    """
    if hwnd is not None:
        msg = win32con.WM_KEYUP if up else win32con.WM_KEYDOWN
        # lParam 按真实键事件构造：扫描码<<16 + 扩展键位(bit24) + repeat=1；
        # KEYUP 再带 transition 位（bit30/31）。扩展键缺位 = 方向键无效
        # （2026-08-08 实测，见 EXTENDED_VK 注释）
        scan = ctypes.windll.user32.MapVirtualKeyW(vk, 0)
        ext = 0x01000000 if vk in EXTENDED_VK else 0
        lparam = ext | (scan << 16) | (0xC0000001 if up else 0x00000001)
        win32gui.PostMessage(hwnd, msg, vk, lparam)
        return
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.ki.wVk = vk
    inp.ki.wScan = 0
    inp.ki.dwFlags = KEYEVENTF_KEYUP if up else 0
    inp.ki.time = 0
    inp.ki.dwExtraInfo = None
    ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


class WindowBackend:
    """mGBA 真实窗口后端。"""

    def __init__(self, mgba_exe: str | Path, rom_path: str | Path,
                 window_timeout: float = 20.0):
        # 注意：CreateProcess 对相对路径的解析在 bash 环境下不可靠，必须绝对路径
        self.mgba_exe = str(Path(mgba_exe).resolve())
        self.rom_path = str(Path(rom_path).resolve())
        self.hwnd = None
        self._frames = 0
        self._proc = None
        self._start_window(window_timeout)

    # ---------- 窗口生命周期 ----------

    def _start_window(self, timeout: float) -> None:
        """启动 mGBA + ROM，等待窗口出现。"""
        rom_name = Path(self.rom_path).name
        self._proc = subprocess.Popen(
            [self.mgba_exe, self.rom_path],
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
        t0 = time.time()
        while time.time() - t0 < timeout:
            self.hwnd = find_window(rom_name)
            if self.hwnd:
                time.sleep(1.0)  # 等窗口内容渲染
                return
            time.sleep(0.5)
        raise WindowError(f"mGBA 窗口未在 {timeout}s 内出现")

    @staticmethod
    def _find_window(rom_name: str):
        return find_window(rom_name)

    def activate(self) -> None:
        """置前台 + 聚焦（SendInput 需要窗口焦点）。"""
        if self.hwnd:
            try:
                win32gui.ShowWindow(self.hwnd, win32con.SW_RESTORE)
                win32gui.SetForegroundWindow(self.hwnd)
            except Exception:
                pass
            time.sleep(0.05)

    def close(self) -> None:
        """关闭 mGBA 窗口。"""
        if self.hwnd:
            try:
                win32gui.PostMessage(self.hwnd, win32con.WM_CLOSE, 0, 0)
            except Exception:
                pass
        if self._proc:
            try:
                self._proc.wait(timeout=5)
            except Exception:
                self._proc.kill()

    # ---------- 抓屏 ----------

    def screenshot(self) -> np.ndarray:
        """抓 mGBA 客户区 → 240x160x3 uint8 RGB。

        先置前台强制重绘（窗口无焦点时不重绘会拿到旧帧/黑帧），再 PrintWindow。
        """
        if not self.hwnd:
            raise WindowError("窗口未就绪")
        self.activate()
        img = capture_hwnd(self.hwnd)
        if img is None:
            raise WindowError("抓屏失败")
        return img

    # ---------- 键鼠（SendInput）----------

    def _send_key(self, vk: int, up: bool) -> None:
        self.activate()
        send_vk(vk, up, hwnd=self.hwnd)

    def _key_down(self, key: Key) -> None:
        self._send_key(VK[key], up=False)

    def _key_up(self, key: Key) -> None:
        self._send_key(VK[key], up=True)

    def press(self, key: Key, frames: int = 8) -> None:
        """按下→按住 frames 帧→松开（帧→时间换算，60fps）。"""
        self.press_hold(key)
        self.run_frames(frames)
        self.release()

    def press_hold(self, *keys: Key) -> None:
        for k in keys:
            self._key_down(k)

    def release(self) -> None:
        for k in list(VK):
            self._key_up(k)

    def release_all(self) -> None:
        self.release()

    def press_sequence(self, keys: list[Key], hold_frames: int = 8) -> None:
        for k in keys:
            self.press(k, hold_frames)

    # ---------- 时间驱动 ----------

    def run_frames(self, n: int = 1) -> None:
        """帧→时间：60fps，sleep(n/60)。"""
        self._frames += n
        time.sleep(n / 60.0)

    @property
    def frame_counter(self) -> int:
        return self._frames

    # ---------- savestate（mGBA 快捷键）----------

    def save_state(self) -> bool:
        """F1 保存到槽 1（返回 True 表示已发出）。"""
        self._send_key(VK_F1, up=False)
        self._send_key(VK_F1, up=True)
        time.sleep(0.3)
        return True

    def load_state(self, data=None) -> bool:
        """Shift+F1 加载槽 1。"""
        self._send_key(VK_LSHIFT, up=False)
        self._send_key(VK_F1, up=False)
        self._send_key(VK_F1, up=True)
        self._send_key(VK_LSHIFT, up=True)
        time.sleep(0.5)
        return True
