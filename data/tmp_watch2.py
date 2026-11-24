"""诊断 v2：枚举 mGBA 进程全部窗口（标题/类名/可见/前台），+ 主窗口 placement。

回答：62-90s 期间「脚本」窗口是否还活着（WM_CLOSE 是否生效）、焦点对象是谁。
"""
import sys, time
import numpy as np
import win32gui, win32process, win32con

sys.path.insert(0, r'c:\Users\Administrator\Desktop\projects\AIGBA')
from src.emulator import window_backend

DUR = float(sys.argv[1]) if len(sys.argv) > 1 else 100.0
OUT = r'c:\Users\Administrator\Desktop\projects\AIGBA\data\demos\replay\diag_wins2.tsv'

def find_mgba_pid():
    out = []
    def cb(h, _):
        if win32gui.IsWindowVisible(h):
            t = win32gui.GetWindowText(h)
            if t and 'mGBA' in t:
                out.append((h, t))
    win32gui.EnumWindows(cb, None)
    return out

t0 = time.time()
pid = None
main_h = None
print("等待 mGBA...", flush=True)
while time.time() - t0 < 60:
    w = find_mgba_pid()
    if w:
        main_h = w[0][0]
        pid = win32process.GetWindowThreadProcessId(main_h)[1]
        break
    time.sleep(0.5)
if not main_h:
    print("未找到"); sys.exit(1)
print(f"mGBA pid={pid} 主窗口 {main_h:#x}", flush=True)

def mgba_windows():
    out = []
    def cb(h, _):
        p = win32process.GetWindowThreadProcessId(h)[1]
        if p == pid and win32gui.IsWindow(h):
            out.append((h, win32gui.GetWindowText(h), win32gui.GetClassName(h),
                        win32gui.IsWindowVisible(h)))
    win32gui.EnumWindows(cb, None)
    return out

t0 = time.time()
with open(OUT, 'w', encoding='utf-8') as f:
    f.write("t\tfg\tmain_pos\tmain_icon\twins\n")
    while time.time() - t0 < DUR:
        fg = win32gui.GetForegroundWindow()
        try:
            r = win32gui.GetWindowRect(main_h)
        except Exception:
            r = None
        icon = 1 if win32gui.IsIconic(main_h) else 0
        wins = []
        for h, t, c, v in mgba_windows():
            if t or 'Qt' in c:  # 只记有标题的或 Qt 窗口
                wins.append(f"{h:#x}:{t[:24]}:{c[:20]}:{'v' if v else 'h'}")
        f.write(f"{time.time()-t0:.2f}\t{fg:#x}\t{r}\t{icon}\t{' | '.join(wins)}\n")
        time.sleep(0.4)
print("done", OUT)
