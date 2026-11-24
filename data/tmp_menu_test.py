"""概念验证：PostMessage Alt 激活菜单栏 → 方向键导航 → 打开 Scripting 视图。

流程：启动 mGBA（无 .sav）→ WM_SYSKEYDOWN/MENU → 截图看菜单栏状态 →
找 QMenu popup 窗口（枚举新 hwnd）→ 逐步导航并截图分析。
目的：确认 Qt 键盘消息在「主窗口菜单导航」场景有效（非键盘屏场景）。
"""
import sys, time, subprocess, shutil
sys.path.insert(0, '.')
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path
import numpy as np, yaml
import win32con, win32gui, win32process
from src.emulator import window_backend

ROOT = Path('.').resolve()
cfg = yaml.safe_load(open('config/settings.yaml', encoding='utf-8'))
ROM_PATH = str((ROOT / cfg['rom']['path']).resolve())
MGBA_EXE = ROOT / 'mGBA.exe'

# ---- 启动 ----
sav_path = Path(ROM_PATH).with_suffix('.sav')
sav_bak = None
if sav_path.exists():
    sav_bak = sav_path.with_name(sav_path.name + '.bak-menu')
    shutil.copy2(sav_path, sav_bak)
    sav_path.unlink()
proc = subprocess.Popen([str(MGBA_EXE.resolve()), ROM_PATH],
                        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
def all_windows():
    out = []
    def cb(h, _):
        pid = win32process.GetWindowThreadProcessId(h)[1]
        title = win32gui.GetWindowText(h)
        cls = win32gui.GetClassName(h)
        out.append((h, pid, title, cls, win32gui.IsWindowVisible(h)))
    win32gui.EnumWindows(cb, None)
    return out

before = {h for h, *_ in all_windows()}
t0 = time.time()
hwnd = None
while time.time() - t0 < 20:
    for h, pid, title, cls, vis in all_windows():
        if h not in before and vis and 'mGBA' in title:
            hwnd = h; break
    if hwnd: break
    time.sleep(0.5)
if not hwnd:
    print("✗ 窗口未出现"); sys.exit(1)
time.sleep(2.0)
print(f"主窗口 {hwnd:#x}")

def new_windows():
    """返回与启动时不同的可见窗口（排除 mGBA 主窗口）。"""
    out = []
    for h, pid, title, cls, vis in all_windows():
        if h not in before and h != hwnd and vis:
            out.append((h, pid, title, cls))
    return out

def send_vk(vk, up=False, hwnd=h, syskey=False):
    scan = ctypes.windll.user32.MapVirtualKeyW(vk, 0) if False else None
    msg = win32con.WM_SYSKEYUP if (syskey and up) else win32con.WM_SYSKEYDOWN if syskey else (win32con.WM_KEYUP if up else win32con.WM_KEYDOWN)
    lparam = (1 << 30) | (1 << 29) if up else 1
    win32gui.PostMessage(hwnd, msg, vk, lparam)

import ctypes

def press(vk, hold=0.2, syskey=False):
    scan = ctypes.windll.user32.MapVirtualKeyW(vk, 0)
    lparam = (scan << 16) | 1
    if syskey:
        win32gui.PostMessage(hwnd, win32con.WM_SYSKEYDOWN, vk, lparam | 0x20000000)
        time.sleep(hold)
        win32gui.PostMessage(hwnd, win32con.WM_SYSKEYUP, vk, lparam | 0xC0000001)
    else:
        win32gui.PostMessage(hwnd, win32con.WM_KEYDOWN, vk, lparam)
        time.sleep(hold)
        win32gui.PostMessage(hwnd, win32con.WM_KEYUP, vk, lparam | 0xC0000001)
    time.sleep(0.3)

def snap(tag):
    img = window_backend.capture_hwnd(hwnd)
    print(f"  [{tag}] mean={img.mean():.1f}")
    return img

# ---- Alt 激活菜单栏 ----
press(0x12, 0.2, syskey=True)
print("Alt 后新窗口:", new_windows())
snap("Alt后")
img = snap("Alt后2")
# 菜单栏区域（顶部 0-30px）分析
top = img[:30]
print(f"  菜单栏区 mean={top.mean():.1f}（对话画面 mean 参考 {img.mean():.1f}）")

# ---- 方向键导航菜单 ----
for i in range(3):  # Right × 3 → 到 Tools
    press(0x27)
    snap(f"Right{i+1}")
    print("  新窗口:", new_windows())
# Down 展开 Tools 菜单
press(0x28, 0.3)
print("Down 后新窗口:", new_windows())
time.sleep(0.5)

# 枚举新窗口（QMenu popup / ScriptingView）
for h, pid, title, cls in new_windows():
    r = win32gui.GetWindowRect(h)
    print(f"新窗口: {h:#x} pid={pid} cls={cls!r} rect={r} title={title!r}")
    try:
        import win32ui
        from PIL import Image
        left, top, right, bottom = win32gui.GetClientRect(h)
        w, d = right - left, bottom - top
        hwnd_dc = win32gui.GetWindowDC(h)
        mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
        save_dc = mfc_dc.CreateCompatibleDC()
        bmp = win32ui.CreateBitmap()
        bmp.CreateCompatibleBitmap(mfc_dc, w, d)
        save_dc.SelectObject(bmp)
        ctypes.windll.user32.PrintWindow(h, save_dc.GetSafeHdc(), 2)
        bits = bmp.GetBitmapBits(True)
        im = Image.frombuffer("RGB", (w, d), bits, "raw", "BGRX", 0, 1)
        im.save(ROOT / "data" / "demos" / "replay" / f"menu_popup_{h:x}.png")
        save_dc.DeleteDC(); mfc_dc.DeleteDC(); win32gui.ReleaseDC(h, hwnd_dc)
        print(f"  popup 截图已存 menu_popup_{h:x}.png ({w}x{d})")
    except Exception as e:
        print(f"  截图失败: {e}")

# ---- 清理 ----
proc.terminate()
try:
    proc.wait(timeout=5)
except Exception:
    proc.kill()
if sav_bak is not None:
    shutil.copy2(sav_bak, sav_path)
    sav_bak.unlink(missing_ok=True)
print("清理完成")
