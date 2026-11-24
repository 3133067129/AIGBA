"""键盘屏 Lua 注入转场测试。

流程：启动 → 注入 demo 到 45.18s（键盘屏出现前）→ 开「脚本」→ print(socket) 测 socket →
Lua 逐事件注入 45.19-51.03s 的 18 个按键 → 每对键后抓游戏截图 → 验证转场成功（黑屏）。
"""
import sys, time, subprocess, shutil, ctypes, json
sys.path.insert(0, '.')
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path
import numpy as np, yaml
import win32con, win32gui, win32process, win32ui
from PIL import Image
from src.emulator import window_backend
from src.emulator.keys import Key

ROOT = Path('.').resolve()
cfg = yaml.safe_load(open('config/settings.yaml', encoding='utf-8'))
ROM_PATH = str((ROOT / cfg['rom']['path']).resolve())
MGBA_EXE = ROOT / 'mGBA.exe'
OUT = ROOT / 'data' / 'demos' / 'replay'
DEMO = ROOT / 'data/demos/demo_20260807_234704.jsonl'

sys.path.insert(0, str(ROOT / 'tools'))
from replay_demo_window import stretch_dir_taps

user32 = ctypes.windll.user32

def capture_game(hwnd):
    left, top, right, bottom = win32gui.GetClientRect(hwnd)
    w, d = right - left, bottom - top
    if w <= 0 or d <= 0: return None
    hwnd_dc = win32gui.GetWindowDC(hwnd)
    mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
    save_dc = mfc_dc.CreateCompatibleDC()
    bmp = win32ui.CreateBitmap()
    bmp.CreateCompatibleBitmap(mfc_dc, w, d)
    save_dc.SelectObject(bmp)
    user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), 2)
    bits = bmp.GetBitmapBits(True)
    im = Image.frombuffer("RGB", (w, d), bits, "raw", "BGRX", 0, 1)
    save_dc.DeleteDC(); mfc_dc.DeleteDC(); win32gui.ReleaseDC(hwnd, hwnd_dc)
    return np.asarray(im)

def click_client(h, x, y):
    lparam = ((y & 0xFFFF) << 16) | (x & 0xFFFF)
    win32gui.PostMessage(h, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lparam)
    time.sleep(0.08)
    win32gui.PostMessage(h, win32con.WM_LBUTTONUP, 0, lparam)
    time.sleep(0.5)

def pclick(x, y):
    user32.SetCursorPos(x, y); time.sleep(0.12)
    user32.mouse_event(0x0002, 0, 0, 0, 0); time.sleep(0.1)
    user32.mouse_event(0x0004, 0, 0, 0, 0); time.sleep(0.8)

def all_visible():
    out = set()
    def cb(h, _):
        if win32gui.IsWindowVisible(h): out.add(h)
    win32gui.EnumWindows(cb, None)
    return out

def all_mgba(pid):
    out = []
    def cb(h, _):
        if win32process.GetWindowThreadProcessId(h)[1] == pid:
            out.append((h, win32gui.GetWindowText(h), win32gui.GetClassName(h)))
    win32gui.EnumWindows(cb, None)
    return out

def lua_input(sv, code, wait=0.15):
    """WM_CHAR 输入一行并 Enter（快路径）"""
    for ch in code:
        win32gui.PostMessage(sv, win32con.WM_CHAR, ord(ch), 1)
        time.sleep(0.02)
    time.sleep(0.1)
    scan = ctypes.windll.user32.MapVirtualKeyW(0x0D, 0)
    win32gui.PostMessage(sv, win32con.WM_KEYDOWN, 0x0D, (scan << 16) | 1)
    time.sleep(0.03)
    win32gui.PostMessage(sv, win32con.WM_KEYUP, 0x0D, (scan << 16) | 0xC0000001)
    time.sleep(wait)

# ---- 启动 ----
sav_path = Path(ROM_PATH).with_suffix('.sav')
sav_bak = None
if sav_path.exists():
    sav_bak = sav_path.with_name(sav_path.name + '.bak-kblua')
    shutil.copy2(sav_path, sav_bak)
    sav_path.unlink()
proc = subprocess.Popen([str(MGBA_EXE.resolve()), ROM_PATH],
                        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
def mgba_hwnds():
    out = []
    def cb(h, _):
        if win32gui.IsWindowVisible(h) and 'mGBA' in win32gui.GetWindowText(h): out.append(h)
    win32gui.EnumWindows(cb, None)
    return out
existing = mgba_hwnds()
t0 = time.time(); hwnd = None
while time.time() - t0 < 20:
    for h in mgba_hwnds():
        if h not in existing: hwnd = h; break
    if hwnd: break
    time.sleep(0.5)
time.sleep(2.0)
print(f"主窗口 {hwnd:#x}")

# ---- 注入到 45180ms（键盘屏出现）----
evs = [json.loads(l) for l in open(DEMO, encoding='utf-8') if l.strip()]
keys = [e for e in evs if e['ev'] == 'key']
t_base = keys[0]['t']
events = []
for k in keys:
    t = k['t'] - t_base
    if t > 45180: break
    try: key = Key(k['name'])
    except ValueError: continue
    events.append({'t': t, 'name': k['name'], 'down': k['down']})
events, n = stretch_dir_taps(events)
t_start = time.monotonic()
i = 0
while True:
    game_ms = int((time.monotonic() - t_start) * 1000) + t_base
    if game_ms - t_base > 45180: break
    while i < len(events) and events[i]['t'] <= game_ms:
        e = events[i]
        window_backend.send_vk(window_backend.VK[Key(e['name'])], up=not e['down'], hwnd=hwnd)
        i += 1
    time.sleep(0.01)
time.sleep(1.0)
g_kb = capture_game(hwnd)
Image.fromarray(g_kb).save(OUT / "kb_before_lua.png")
print(f"键盘屏画面 mean={g_kb.mean():.1f}")

# ---- 开「脚本」----
click_client(hwnd, 230, 15)
time.sleep(0.4)
popup = None
for h in all_visible():
    if 'QWindowPopup' in win32gui.GetClassName(h): popup = h; break
pr = win32gui.GetWindowRect(popup)
pclick(pr[0] + 137, pr[1] + 31 + 81)
time.sleep(1.0)
sv = None
for h, t, c in all_mgba(proc.pid):
    if '脚本' in t: sv = h; break
if not sv:
    print("✗ 未找到「脚本」窗口"); proc.terminate(); sys.exit(1)
r = win32gui.GetWindowRect(sv)
# 移动脚本窗口避免挡游戏画面（游戏窗口 1147-2441）
user32.SetWindowPos(sv, 0, 1900, 550, 859, 676, 0x0040)
time.sleep(0.5)
# 聚焦 prompt
pclick(1900 + 500, 550 + 616)
time.sleep(0.3)
print(f"「脚本」窗口就绪")

# ---- 测 socket ----
lua_input(sv, 'print(socket)')
print("socket 测试已发（log 区输出稍后验证）")

# ---- Lua 逐事件注入 45.19-51.03s ----
seg = []
for k in keys:
    t = k['t'] - t_base
    if 45180 < t <= 62000:
        try: key = Key(k['name'])
        except ValueError: continue
        seg.append({'t': t, 'name': k['name'], 'down': k['down']})
seg, n = stretch_dir_taps(seg)
VK2LUA = {'A': 0, 'B': 1, 'S': 2, 's': 3, '<': 4, '>': 5, '^': 6, 'v': 7, 'R': 8, 'L': 9,
          'LEFT': 4, 'RIGHT': 5, 'UP': 6, 'DOWN': 7}
print(f"注入 {len(seg)} 个事件:")
shots = []
for e in seg:
    idx = VK2LUA.get(e['name'])
    if idx is None:
        print(f"  ✗ 无映射 {e['name']}")
        continue
    cmd = 'addKey' if e['down'] else 'clearKey'
    lua_input(sv, f'emu:{cmd}({idx})')
    shots.append((e['t'], capture_game(hwnd)))
    if e['down']:
        print(f"  {e['t']:6d} {e['name']:4s} {cmd}({idx})")

# ---- 验证转场 ----
time.sleep(1.0)
g_final = capture_game(hwnd)
Image.fromarray(g_final).save(OUT / "kb_after_lua_final.png")
print(f"最终画面 mean={g_final.mean():.1f}（转场后：黑屏<50 / 房间/对话）")
# 过程截图差异
prev = g_kb
for t, img in shots:
    if img is not None and prev is not None and img.shape == prev.shape:
        d = (np.abs(img.astype(int) - prev.astype(int)).sum(axis=2) > 60).sum()
        if d > 0:
            print(f"  t={t}: 画面变化 {d}px")
    prev = img
# 与键盘屏前画面比较（对话屏 94.3 → 键盘屏 150 → 转场后黑屏/新画面）
print(f"键盘屏前 mean=93.7（对话屏） → 键盘屏 {g_kb.mean():.1f} → 最终 {g_final.mean():.1f}")

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
