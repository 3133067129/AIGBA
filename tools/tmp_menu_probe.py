"""诊断：Tools 菜单 popup 打开 + 菜单项点击 + 「脚本」窗口出现（2026-08-08）。

探针运行两次失败：一次「Tools 菜单未弹出」、一次「未找到脚本窗口」——而
fix14f 时代同一代码成功多次。本脚本把 prepare() 的每一步摊开打印：
1. PostMessage 点 Tools 菜单 → 逐窗打印 mGBA 进程所有可见顶层窗（类/矩形/标题）
2. 找到 QWindowPopup 后物理点击第 4 项 → 再逐窗打印，确认脚本窗口是否出现

用法：py -3.14 tools/tmp_menu_probe.py
"""
import ctypes
import subprocess
import sys
import time
from pathlib import Path

import win32con
import win32gui
import win32process

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from tools.replay_demo_window import MGBA_EXE, ROM_PATH, _all_mgba_hwnds, wait_new_hwnd  # noqa: E402

MENU_TOOLS_X = 230
MENU_SCRIPTING_Y = 81


def dump_windows(pid, tag):
    print(f"--- 窗口清单 {tag} ---", flush=True)
    def cb(h, _):
        if not win32gui.IsWindowVisible(h):
            return
        p = win32process.GetWindowThreadProcessId(h)[1]
        if p != pid:
            return
        r = win32gui.GetWindowRect(h)
        print(f"  {h:#x} {win32gui.GetClassName(h)} rect={r} "
              f"title='{win32gui.GetWindowText(h)}'", flush=True)
    win32gui.EnumWindows(cb, None)


def pclick(x, y):
    user32 = ctypes.windll.user32
    user32.SetCursorPos(x, y)
    time.sleep(0.12)
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    time.sleep(0.1)
    user32.mouse_event(0x0004, 0, 0, 0, 0)
    time.sleep(0.8)


def open_menu(hwnd, pid):
    """PostMessage 点 Tools 菜单，返回 popup hwnd（或 None）。"""
    lparam = ((15 & 0xFFFF) << 16) | (MENU_TOOLS_X & 0xFFFF)
    win32gui.PostMessage(hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lparam)
    time.sleep(0.08)
    win32gui.PostMessage(hwnd, win32con.WM_LBUTTONUP, 0, lparam)
    time.sleep(0.6)
    for h in _visible_popups(pid):
        if "QWindowPopup" in win32gui.GetClassName(h):
            return h
    return None


def main():
    existing = _all_mgba_hwnds()
    if existing:
        print(f"✗ 已有 {len(existing)} 个 mGBA 实例——先关闭再试")
        return 1
    proc = subprocess.Popen([str(MGBA_EXE.resolve()), ROM_PATH],
                            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
    hwnd = wait_new_hwnd(existing)
    if not hwnd:
        print("✗ mGBA 窗口未出现")
        return 1
    pid = proc.pid
    time.sleep(6)

    def titles():
        return {win32gui.GetWindowText(h) for h in _visible_popups(pid)}

    def close_menu_by_outside_click():
        """物理点击菜单外区域（主窗口游戏区），关闭可能残留的菜单 popup。"""
        ctypes.windll.user32.SetCursorPos(300, 500)
        time.sleep(0.12)
        ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)
        ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)
        time.sleep(0.7)

    # 逐项扫描：先确保菜单关闭 → 打开菜单 → 点某 y → 看开了什么窗口 → 关掉 → 下一个 y
    for y in (15, 37, 58, 81, 104, 125, 148, 171, 194):
        close_menu_by_outside_click()
        popup = open_menu(hwnd, pid)
        if not popup:
            print(f"y={y}: 菜单未弹出（跳过）", flush=True)
            continue
        pr = win32gui.GetWindowRect(popup)
        cls = win32gui.GetClassName(popup)
        print(f"y={y}: 菜单 popup {popup:#x} [{cls}] rect={pr}", flush=True)
        pclick(pr[0] + 137, pr[1] + 31 + y)
        time.sleep(0.6)
        print(f"y={y} 点击后全部窗口：", flush=True)
        dump_windows(pid, f"y={y}")
        new = None
        for h in _visible_popups(pid):
            if h == hwnd or "QWindowPopup" in win32gui.GetClassName(h):
                continue
            t = win32gui.GetWindowText(h)
            if t and t != win32gui.GetWindowText(hwnd):
                new = (h, t)
                break
        if new:
            print(f"  → 关掉 {new[1]}", flush=True)
            win32gui.PostMessage(new[0], win32con.WM_CLOSE, 0, 0)
            time.sleep(0.6)
        else:
            # 菜单可能还开着：点外部关闭，保证下次干净重开
            ctypes.windll.user32.SetCursorPos(100, 400)
            ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)
            ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)
            time.sleep(0.6)
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        pass
    return 0


def _visible_popups(pid):
    out = []
    def cb(h, _):
        if not win32gui.IsWindowVisible(h):
            return
        if win32process.GetWindowThreadProcessId(h)[1] != pid:
            return
        out.append(h)
    win32gui.EnumWindows(cb, None)
    return out


if __name__ == "__main__":
    sys.exit(main())
