"""键盘屏输入实验 v3：验证 SendInput 是否真被火绒拦截 + START/SELECT 是否有效。

流程：冷启动 → 注入到 47.5s（键盘屏停留）→
  1. SendInput A：检查返回值（火绒拦截会返回 0）+ GetForegroundWindow 检查
  2. PostMessage START(Enter)/SELECT(Backspace)（键盘屏语义：START=确认名字，SELECT=退格）
  3. 真实键盘测试：SetForegroundWindow + SendInput + 验证
判定：红区/名字槽/画面切换变化。
"""
import sys, json, time, subprocess, shutil, ctypes
sys.path.insert(0, '.')
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path
import numpy as np, yaml
import win32con, win32gui
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

def name_slot(img):
    return int((img[26:46, 28:90].sum(axis=2) < 300).sum())

def snap(label):
    img = window_backend.capture_hwnd(hwnd)
    print(f"  [{label}] mean={img.mean():.1f} 红区={redbox(img)} 槽={name_slot(img)}")

def sendinput_vk(vk, up):
    """SendInput 单键，返回 SendInput 返回值。"""
    ULONG_PTR = ctypes.c_size_t
    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort),
                    ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong),
                    ("dwExtraInfo", ULONG_PTR)]
    class INPUT(ctypes.Structure):
        _fields_ = [("type", ctypes.c_ulong), ("ki", KEYBDINPUT)]
    inp = INPUT()
    inp.type = 1
    inp.ki.wVk = vk
    inp.ki.dwFlags = 0x0002 if up else 0
    return ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))

# ---- 事件流 ----
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

# ---- 启动 ----
sav_path = Path(ROM_PATH).with_suffix('.sav')
sav_bak = None
if sav_path.exists():
    sav_bak = sav_path.with_name(sav_path.name + '.bak-diag3')
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
time.sleep(1.0)
print(f"主窗口 {hwnd:#x}")

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
time.sleep(1.5)
snap("基准")

# ---- 1. SendInput A 返回值检查 ----
win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
win32gui.SetForegroundWindow(hwnd)
time.sleep(0.3)
print(f"前台={win32gui.GetForegroundWindow():#x} (主={hwnd:#x})")
r1 = sendinput_vk(0x58, False); time.sleep(0.3)
r2 = sendinput_vk(0x58, True);  time.sleep(0.4)
print(f"SendInput A down={r1} up={r2}（0=被火绒拦截）")
snap("SendInput A 后")

# ---- 2. PostMessage START(Enter) ----
window_backend.send_vk(0x0D, up=False, hwnd=hwnd)
time.sleep(0.3)
window_backend.send_vk(0x0D, up=True, hwnd=hwnd)
time.sleep(0.6)
snap("PostMessage START 后")

# ---- 3. PostMessage SELECT(Backspace) ----
window_backend.send_vk(0x08, up=False, hwnd=hwnd)
time.sleep(0.3)
window_backend.send_vk(0x08, up=True, hwnd=hwnd)
time.sleep(0.6)
snap("PostMessage SELECT 后")

# ---- 4. SendInput START（若 SendInput 可用）----
if r1 and r2:
    r3 = sendinput_vk(0x0D, False); time.sleep(0.3)
    r4 = sendinput_vk(0x0D, True);  time.sleep(0.6)
    print(f"SendInput START down={r3} up={r4}")
    snap("SendInput START 后")

# ---- 5. 消息钩子验证：WM_KEYDOWN 是否真的到达 mGBA ----
# 用 GetQueueStatus 或安装钩子太重；改为检查 mGBA 是否处理了消息（
# PostMessage 后等待 200ms 再抓屏——已覆盖）。

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
