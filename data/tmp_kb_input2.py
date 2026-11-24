"""键盘屏输入通道决定性实验。

流程：冷启动 mGBA（无 .sav）→ 注入录制事件到 47.5s（键盘屏停留）→ 依次测试：
  1. SendInput 真实 A（若火绒已放行）
  2. 鼠标点击渲染区（WM_LBUTTONDOWN/UP PostMessage）后 PostMessage A
  3. 鼠标点击后 SendInput A
判定：每次测试后连续抓 3 帧看红区/名字槽变化（排除闪烁相位伪影）。
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

def name_slot(img):
    return int((img[26:46, 28:90].sum(axis=2) < 300).sum())

def snap3(label):
    """连续 3 帧抓屏，返回红区/名字槽序列（区分闪烁相位 vs 状态变化）。"""
    out = []
    for _ in range(3):
        img = window_backend.capture_hwnd(hwnd)
        out.append((redbox(img), name_slot(img), round(float(img.mean()), 1)))
        time.sleep(0.18)
    print(f"  [{label}] 3帧: " + " | ".join(f"红区{r[0]} 槽{r[1]} mean{r[2]}" for r in out))
    return out

# ---- 事件流（到 47.5s）----
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
    sav_bak = sav_path.with_name(sav_path.name + '.bak-diag2')
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

# ---- 注入到 47.5s ----
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
snap3("基准键盘屏")

# ---- 测试 1：SendInput 真实 A ----
win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
win32gui.SetForegroundWindow(hwnd)
time.sleep(0.3)
window_backend.send_vk(window_backend.VK[Key('A')], up=False)   # 无 hwnd → SendInput
time.sleep(0.3)
window_backend.send_vk(window_backend.VK[Key('A')], up=True)
time.sleep(0.4)
snap3("SendInput A")

# ---- 测试 2：鼠标点击渲染区 → PostMessage A ----
rect = win32gui.GetClientRect(hwnd)   # 客户区
print(f"客户区: {rect}")
# 画面区上部（键盘屏键盘可能在底部；点 y=100 应在名字槽/预览区附近）
cx, cy = rect[2] // 2, 100
lparam = (cy << 16) | (cx & 0xFFFF)
win32gui.PostMessage(hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lparam)
time.sleep(0.15)
win32gui.PostMessage(hwnd, win32con.WM_LBUTTONUP, 0, lparam)
time.sleep(0.5)
snap3("点击后")
window_backend.send_vk(window_backend.VK[Key('A')], up=False, hwnd=hwnd)
time.sleep(0.3)
window_backend.send_vk(window_backend.VK[Key('A')], up=True, hwnd=hwnd)
time.sleep(0.4)
snap3("点击+PostMessage A")

# ---- 测试 3：鼠标点击渲染区 → SendInput A ----
lparam = (cy << 16) | (cx & 0xFFFF)
win32gui.PostMessage(hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lparam)
time.sleep(0.15)
win32gui.PostMessage(hwnd, win32con.WM_LBUTTONUP, 0, lparam)
time.sleep(0.3)
win32gui.SetForegroundWindow(hwnd)
time.sleep(0.2)
window_backend.send_vk(window_backend.VK[Key('A')], up=False)
time.sleep(0.3)
window_backend.send_vk(window_backend.VK[Key('A')], up=True)
time.sleep(0.4)
snap3("点击+SendInput A")

# ---- 测试 4：多点多找键盘（底部键盘区扫描点击）----
# 若键盘屏是 mGBA virtual keyboard overlay，键盘按键在画面下部
win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
win32gui.SetForegroundWindow(hwnd)
for gy in (40, 60, 80, 100, 120):
    lparam = ((rect[2] // 2) & 0xFFFF) | (gy << 16)
    win32gui.PostMessage(hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lparam)
    time.sleep(0.08)
    win32gui.PostMessage(hwnd, win32con.WM_LBUTTONUP, 0, lparam)
    time.sleep(0.2)
snap3("底部扫描点击后")

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
