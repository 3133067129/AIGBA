"""Lua 注入核心验证：emu:addKey 直注入 core。

流程：启动（无 sav）→ 注入 demo 按键流推进到对话屏 → 开「脚本」窗口 →
输入 print("LUA_OK") 验证 Lua 可用 → 输入 emu:addKey(0) 注入 A → 对比游戏截图。
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

def full_shot(h):
    left, top, right, bottom = win32gui.GetWindowRect(h)
    w, d = right - left, bottom - top
    hwnd_dc = win32gui.GetWindowDC(h)
    mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
    save_dc = mfc_dc.CreateCompatibleDC()
    bmp = win32ui.CreateBitmap()
    bmp.CreateCompatibleBitmap(mfc_dc, w, d)
    save_dc.SelectObject(bmp)
    ctypes.windll.gdi32.BitBlt(save_dc.GetSafeHdc(), 0, 0, w, d, hwnd_dc, 0, 0, win32con.SRCCOPY)
    bits = bmp.GetBitmapBits(True)
    im = Image.frombuffer("RGB", (w, d), bits, "raw", "BGRX", 0, 1)
    save_dc.DeleteDC(); mfc_dc.DeleteDC(); win32gui.ReleaseDC(h, hwnd_dc)
    return np.asarray(im)

def capture_game(hwnd):
    """抓游戏画面（游戏区在客户区中央）——用 PrintWindow 客户区"""
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

def lua_input(sv, code):
    """WM_CHAR 输入一行并 Enter"""
    for ch in code:
        win32gui.PostMessage(sv, win32con.WM_CHAR, ord(ch), 1)
        time.sleep(0.03)
    time.sleep(0.3)
    scan = ctypes.windll.user32.MapVirtualKeyW(0x0D, 0)
    win32gui.PostMessage(sv, win32con.WM_KEYDOWN, 0x0D, (scan << 16) | 1)
    time.sleep(0.05)
    win32gui.PostMessage(sv, win32con.WM_KEYUP, 0x0D, (scan << 16) | 0xC0000001)
    time.sleep(0.8)

# ---- 启动 ----
sav_path = Path(ROM_PATH).with_suffix('.sav')
sav_bak = None
if sav_path.exists():
    sav_bak = sav_path.with_name(sav_path.name + '.bak-lua')
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

# ---- 注入 demo 按键流到 44s（对话屏）----
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
time.sleep(1.5)
g0 = capture_game(hwnd)
print(f"注入后游戏画面 mean={g0.mean():.1f}（确认对话屏）")

# ---- 开「脚本」 ----
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
print(f"「脚本」窗口 {sv:#x} rect={r}")

# 聚焦 prompt
pclick(r[0] + 500, r[1] + 616)
time.sleep(0.3)

# ---- 1. 验证 Lua 可用 ----
lua_input(sv, 'print("LUA_OK")')
img_lua = full_shot(sv)
Image.fromarray(img_lua).save(OUT / "sv_lua_ok.png")
print("print(LUA_OK) 已执行，截图 sv_lua_ok.png")

# ---- 2. emu:addKey(0) 注入 A ----
# 先抓游戏基线（脚本窗口挡住游戏窗口？游戏窗口在 (1147,151)，脚本窗口 (850,350)——部分重叠！
# 移动脚本窗口到屏幕右侧避免遮挡
import win32gui as _g
# 用 SetWindowPos 移动脚本窗口（PostMessage 对 Qt 移动无效？直接 SetWindowPos）
ctypes.windll.user32.SetWindowPos(sv, 0, 1800, 400, 859, 676, 0x0040)  # SWP_NOZORDER|SWP_SHOWWINDOW? 0x0040=SHOWWINDOW
time.sleep(0.5)
g_before = capture_game(hwnd)
lua_input(sv, 'emu:addKey(0)')
time.sleep(0.3)
lua_input(sv, 'emu:clearKey(0)')
time.sleep(0.5)
g_after = capture_game(hwnd)
if g_before is not None and g_after is not None and g_before.shape == g_after.shape:
    d = (np.abs(g_before.astype(int) - g_after.astype(int)).sum(axis=2) > 60)
    print(f"addKey(0) 注入后游戏差异像素 {d.sum()}（>0 说明 A 键生效）")
    Image.fromarray(g_before).save(OUT / "game_before_addkey.png")
    Image.fromarray(g_after).save(OUT / "game_after_addkey.png")
else:
    print(f"游戏截图不可比 {None if g_before is None else g_before.shape} {None if g_after is None else g_after.shape}")

img_final = full_shot(sv)
Image.fromarray(img_final).save(OUT / "sv_after_addkey.png")
print("最终脚本窗口截图 sv_after_addkey.png（检查 log 区有无错误）")

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
