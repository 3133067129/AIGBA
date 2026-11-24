"""对话屏 A 有效性决定性测试：停住不发键 vs 按 PostMessage A。

流程：冷启动 → 注入到 44.0s（对话屏）→ 停住观察 4s（对话自动推进？）→
PostMessage A 观察 2s → 连续 PostMessage A 观察 4s。
判定：画面变化 = 推进。区分「自动推进」vs「A 驱动推进」。
"""
import sys, json, time, subprocess, shutil
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

def snap(label):
    img = window_backend.capture_hwnd(hwnd)
    print(f"  [{label}] mean={img.mean():.1f} 红区={redbox(img)}")

# ---- 事件流（到 44.0s，对话屏）----
evs = [json.loads(l) for l in open(DEMO, encoding='utf-8') if l.strip()]
keys = [e for e in evs if e['ev'] == 'key']
t_base = keys[0]['t']
events = []
for k in keys:
    t = k['t'] - t_base
    if t > 44000: break
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
    if game_ms - t_base > 44000: break
    while i < len(events) and events[i]['t'] <= game_ms:
        e = events[i]
        window_backend.send_vk(window_backend.VK[Key(e['name'])], up=not e['down'], hwnd=hwnd)
        i += 1
    time.sleep(0.01)
print(f"注入完成 {i} 事件，停住观察（无输入）")
time.sleep(1.0)

# ---- 阶段1：停住 4s（不按键）----
for j in range(5):
    time.sleep(0.9)
    snap(f"停住 {j}")
# ---- 阶段2：单次 PostMessage A ----
window_backend.send_vk(window_backend.VK[Key('A')], up=False, hwnd=hwnd)
time.sleep(0.2)
window_backend.send_vk(window_backend.VK[Key('A')], up=True, hwnd=hwnd)
time.sleep(1.0)
snap("单次A后")
time.sleep(1.0)
snap("单次A后+1s")
# ---- 阶段3：连续 A（每秒 3 次）----
for j in range(6):
    window_backend.send_vk(window_backend.VK[Key('A')], up=False, hwnd=hwnd)
    time.sleep(0.15)
    window_backend.send_vk(window_backend.VK[Key('A')], up=True, hwnd=hwnd)
    time.sleep(0.25)
    if j % 2 == 0:
        snap(f"连按A {j}")

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
