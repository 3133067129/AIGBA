"""键盘屏输入实验 v4：消息到达性验证三连。

流程：冷启动 → 注入到 47.5s（键盘屏停留）→
  1. GetQueueStatus：PostMessage A 前后队列状态（消息是否被取出）
  2. repeat count = 0 的 PostMessage A（lParam bit0 清零）
  3. SendMessage 同步 A（跨线程直调窗口过程）
  4. PostMessage WM_SYSKEYDOWN Alt（键盘屏期间）
判定：每次后连续抓 3 帧看红区/名字槽（排除闪烁伪影）。
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

def snap3(label):
    out = []
    for _ in range(3):
        img = window_backend.capture_hwnd(hwnd)
        out.append((redbox(img), name_slot(img), round(float(img.mean()), 1)))
        time.sleep(0.18)
    print(f"  [{label}] " + " | ".join(f"红区{r[0]} 槽{s} mean{m}" for r, s, m in out))
    return out

def post_vk(vk, up, repeat=1):
    scan = ctypes.windll.user32.MapVirtualKeyW(vk, 0)
    ext = 0x01000000 if vk in (0x25, 0x26, 0x27, 0x28) else 0
    lparam = ext | (scan << 16) | ((0xC0000000 if up else 0) | repeat)
    win32gui.PostMessage(hwnd, win32con.WM_KEYUP if up else win32con.WM_KEYDOWN, vk, lparam)

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
    sav_bak = sav_path.with_name(sav_path.name + '.bak-diag4')
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
snap3("基准")

# ---- 1. GetQueueStatus ----
tid = ctypes.windll.user32.GetWindowThreadProcessId(hwnd, None)
print(f"mGBA 线程 {tid}")
QS_KEY = 0x0001
q1 = ctypes.windll.user32.GetQueueStatus(QS_KEY)
print(f"  PostMessage 前队列 QS_KEY={q1:#x}")
post_vk(0x58, False)  # A down
time.sleep(0.1)
q2 = ctypes.windll.user32.GetQueueStatus(QS_KEY)
print(f"  发 A down 后 100ms QS_KEY={q2:#x}（0x10001=有键盘消息待处理）")
time.sleep(0.5)
q3 = ctypes.windll.user32.GetQueueStatus(QS_KEY)
print(f"  600ms 后 QS_KEY={q3:#x}（0=已被取出处理）")
post_vk(0x58, True)
time.sleep(0.5)
snap3("PostMessage A (repeat=1)")

# ---- 2. repeat count = 0 ----
post_vk(0x58, False, repeat=0)
time.sleep(0.3)
post_vk(0x58, True, repeat=0)
time.sleep(0.5)
snap3("PostMessage A (repeat=0)")

# ---- 3. SendMessage 同步 ----
ctypes.windll.user32.SendMessageW(hwnd, win32con.WM_KEYDOWN, 0x58, 0x58000001)
time.sleep(0.3)
ctypes.windll.user32.SendMessageW(hwnd, win32con.WM_KEYUP, 0x58, 0xD8000001)
time.sleep(0.5)
snap3("SendMessage A")

# ---- 4. Alt（WM_SYSKEYDOWN）----
scan = ctypes.windll.user32.MapVirtualKeyW(0x12, 0)
ctypes.windll.user32.PostMessageW(hwnd, win32con.WM_SYSKEYDOWN, 0x12, (scan << 16) | 1)
time.sleep(0.2)
ctypes.windll.user32.PostMessageW(hwnd, win32con.WM_SYSKEYUP, 0x12, (scan << 16) | 0xC0000001)
time.sleep(0.5)
snap3("Alt 后")

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
