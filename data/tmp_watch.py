"""独立诊断进程：旁路观察 mGBA 窗口状态（不干扰回放）。

每 0.3s 记录：墙钟、前台窗口句柄、主窗口是否最小化/可见/标题、抓屏 mean、
画面是否与上次相同（同帧静止检测）。输出 TSV 到 replay/diag_winstate.tsv。

用法: py -3.14 -u data/tmp_watch.py [时长秒，默认130]
配合: tools/replay_demo_window.py --launch --verify --clean-sav --to 95 ...
"""
import sys, time
import numpy as np
import win32gui

sys.path.insert(0, r'c:\Users\Administrator\Desktop\projects\AIGBA')
from src.emulator import window_backend

DUR = float(sys.argv[1]) if len(sys.argv) > 1 else 130.0
OUT = r'c:\Users\Administrator\Desktop\projects\AIGBA\data\demos\replay\diag_winstate.tsv'

def find_mgba():
    out = []
    def cb(h, _):
        if win32gui.IsWindowVisible(h):
            t = win32gui.GetWindowText(h)
            if t and 'mGBA' in t:
                out.append((h, t))
    win32gui.EnumWindows(cb, None)
    return out

t0 = time.time()
hwnd, title = None, ''
print("等待 mGBA 窗口...", flush=True)
while time.time() - t0 < 60:
    w = find_mgba()
    if w:
        hwnd, title = w[0]
        break
    time.sleep(0.5)
if not hwnd:
    print("未找到 mGBA 窗口"); sys.exit(1)
print(f"mGBA 窗口 {hwnd:#x} '{title}'，开始观察 {DUR:.0f}s", flush=True)

last_img = None
t0 = time.time()
n = 0
with open(OUT, 'w', encoding='utf-8') as f:
    f.write("t\tfg\ticon\tvis\tmean\tstatic\ttitle\n")
    while time.time() - t0 < DUR:
        fg = win32gui.GetForegroundWindow()
        icon = 1 if win32gui.IsIconic(hwnd) else 0
        vis = 1 if win32gui.IsWindowVisible(hwnd) else 0
        img = window_backend.capture_hwnd(hwnd)
        m = float(np.asarray(img).mean()) if img is not None else -1.0
        st = ''
        if img is not None and last_img is not None:
            d = int(np.abs(img.astype(int) - last_img.astype(int)).sum())
            st = str(d)
        last_img = img
        f.write(f"{time.time()-t0:.2f}\t{fg:#x}\t{icon}\t{vis}\t{m:.1f}\t{st}\t{win32gui.GetWindowText(hwnd)}\n")
        n += 1
        time.sleep(0.3)
print(f"观察结束 {n} 行 → {OUT}")
