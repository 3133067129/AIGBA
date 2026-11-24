"""键盘屏期间枚举 mGBA 窗口/线程焦点 + 测试激活后按键是否生效。

流程：冷启动 mGBA（无 .sav）→ 注入录制事件到 47.5s（键盘屏出现后停住）→
枚举全部顶层/子窗口（类名/标题/可见性）+ GetGUIThreadInfo 线程焦点 →
逐项测试：裸 PostMessage A / WM_SETFOCUS+WM_ACTIVATE 后 A / 消息发到渲染区子窗口。
红区变化 = 按键生效。
"""
import sys, json, time, subprocess, shutil, ctypes
sys.path.insert(0, '.')
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path
import numpy as np, yaml
import win32con, win32gui, win32process
from src.emulator import window_backend
from src.emulator.keys import Key

ROOT = Path('.').resolve()
cfg = yaml.safe_load(open('config/settings.yaml', encoding='utf-8'))
ROM_PATH = str((ROOT / cfg['rom']['path']).resolve())
MGBA_EXE = ROOT / 'mGBA.exe'
DEMO = ROOT / 'data/demos/demo_20260807_234704.jsonl'

sys.path.insert(0, str(ROOT / 'tools'))
from replay_demo_window import stretch_dir_taps

def redbox(img):
    r = img[:, :, 0].astype(int); g = img[:, :, 1].astype(int); b = img[:, :, 2].astype(int)
    red = (r > 150) & (g < 100) & (b < 100)
    if red.sum() == 0: return None
    ys, xs = np.where(red)
    return (int(ys.min()), int(ys.max()), int(xs.min()), int(xs.max()), int(red.sum()))

def mean_of(img): return float(img.mean())

# ---- 准备事件流（只发到 47.5s → 停在键盘屏出现前/黑屏段）----
evs = [json.loads(l) for l in open(DEMO, encoding='utf-8') if l.strip()]
keys = [e for e in evs if e['ev'] == 'key']
t_base = keys[0]['t']
events = []
for k in keys:
    t = k['t'] - t_base
    if t > 47500: break
    try: key = Key(k['name'])
    except ValueError: continue
    events.append({'t': t, 'name': k['name'], 'down': k['down']})
events, n = stretch_dir_taps(events)

# ---- 启动 mGBA（无存档冷启动）----
sav_path = Path(ROM_PATH).with_suffix('.sav')
sav_bak = None
if sav_path.exists():
    sav_bak = sav_path.with_name(sav_path.name + '.bak-diag')
    shutil.copy2(sav_path, sav_bak)
    sav_path.unlink()
proc = subprocess.Popen([str(MGBA_EXE.resolve()), ROM_PATH],
                        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)

def mgba_hwnds():
    out = []
    def cb(h, _):
        if win32gui.IsWindowVisible(h) and 'mGBA' in win32gui.GetWindowText(h):
            out.append(h)
    win32gui.EnumWindows(cb, None)
    return out

existing = mgba_hwnds()
t0 = time.time()
hwnd = None
while time.time() - t0 < 20:
    for h in mgba_hwnds():
        if h not in existing:
            hwnd = h; break
    if hwnd: break
    time.sleep(0.5)
if not hwnd:
    print("✗ 窗口未出现"); sys.exit(1)
time.sleep(1.0)
print(f"主窗口 hwnd={hwnd:#x} pid={win32process.GetWindowThreadProcessId(hwnd)[1]}")

# ---- 回放事件到 47.5s ----
t_start = time.monotonic()
i = 0
while True:
    game_ms = int((time.monotonic() - t_start) * 1000) + t_base
    if game_ms - t_base > 47500: break
    while i < len(events) and events[i]['t'] <= game_ms:
        e = events[i]
        window_backend.send_vk(window_backend.VK[Key(e['name'])], up=not e['down'], hwnd=hwnd)
        i += 1
    time.sleep(0.01)
print(f"注入完成 {i} 事件")

# ---- 等键盘屏稳定 + 枚举窗口 ----
time.sleep(1.5)
img = window_backend.capture_hwnd(hwnd)
print(f"[基准] mean={mean_of(img):.1f} 红区={redbox(img)}")

all_hwnds = []
def dump():
    lines = []
    def cb(h, _):
        pid = win32process.GetWindowThreadProcessId(h)[1]
        tid = win32process.GetWindowThreadProcessId(h)[0]
        info = None
        if tid:
            class GUIINFO(ctypes.Structure):
                _fields_ = [("cbSize", ctypes.c_uint), ("flags", ctypes.c_uint),
                            ("hwndActive", ctypes.c_void_p), ("hwndFocus", ctypes.c_void_p),
                            ("hwndCapture", ctypes.c_void_p), ("hwndMenuOwner", ctypes.c_void_p),
                            ("hwndMoveSize", ctypes.c_void_p), ("hwndCaret", ctypes.c_void_p),
                            ("rcCaret", ctypes.c_byte * 16)]
            gi = GUIINFO(); gi.cbSize = ctypes.sizeof(GUIINFO)
            if ctypes.windll.user32.GetGUIThreadInfo(tid, ctypes.byref(gi)):
                info = {"hwndActive": gi.hwndActive, "hwndFocus": gi.hwndFocus}
        all_hwnds.append(h)
        fg = win32gui.GetForegroundWindow()
        title = win32gui.GetWindowText(h)
        cls = win32gui.GetClassName(h)
        lines.append(f"hwnd={h:#x} pid={pid} cls={cls!r} vis={win32gui.IsWindowVisible(h)}"
                     f" rect={win32gui.GetWindowRect(h)} fg={h == fg}"
                     f" active={info and info.get('hwndActive') == h}"
                     f" focus={info and info.get('hwndFocus') == h}"
                     f" title={title!r}")
        def cb2(ch, _):
            all_hwnds.append(ch)
            lines.append(f"  子 {ch:#x} cls={win32gui.GetClassName(ch)!r}"
                         f" vis={win32gui.IsWindowVisible(ch)}"
                         f" rect={win32gui.GetWindowRect(ch)}"
                         f" title={win32gui.GetWindowText(ch)!r}")
        win32gui.EnumChildWindows(h, cb2, None)
    win32gui.EnumWindows(cb, None)
    print('\n'.join(lines))
    return lines

print("=== 窗口枚举（键盘屏停留）===")
dump()
fg = win32gui.GetForegroundWindow()
print(f"前台窗口: {fg:#x} (主窗口={hwnd:#x}, 相同={fg == hwnd})")

def try_send(label, h, activate_first=False):
    if activate_first:
        win32gui.PostMessage(h, win32con.WM_SETFOCUS, hwnd, 0)
        win32gui.PostMessage(h, win32con.WM_ACTIVATE, win32con.WA_ACTIVE, 0)
        time.sleep(0.2)
    window_backend.send_vk(window_backend.VK[Key('A')], up=False, hwnd=h)
    time.sleep(0.3)
    window_backend.send_vk(window_backend.VK[Key('A')], up=True, hwnd=h)
    time.sleep(0.4)
    img = window_backend.capture_hwnd(hwnd)
    rb = redbox(img)
    print(f"[{label}] A 后 mean={mean_of(img):.1f} 红区={rb}")
    return rb

try_send("裸PostMessage→主窗口", hwnd, activate_first=False)
try_send("SETFOCUS+ACTIVATE→主窗口", hwnd, activate_first=True)

# 对渲染区子窗口（非零尺寸、可见的子窗口）发键
subs = [h for h in all_hwnds if h != hwnd and win32gui.IsWindowVisible(h)]
for h in subs:
    r = win32gui.GetWindowRect(h)
    if r[2] - r[0] > 50 and r[3] - r[1] > 50:
        try_send(f"裸PostMessage→子窗口{h:#x}", h, activate_first=False)
        break

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
