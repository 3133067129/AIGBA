"""混合回放集成测试：PostMessage(0-45.18s) + Lua(45.18-62s) + PostMessage(62-75s)。

验证：键盘屏转场成功 + 62s 后对话正常推进。
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
LUA_START, LUA_END = 45180, 62000
VK2LUA = {'A': 0, 'B': 1, 'S': 2, 's': 3, '<': 4, '>': 5, '^': 6, 'v': 7, 'R': 8, 'L': 9,
          'LEFT': 4, 'RIGHT': 5, 'UP': 6, 'DOWN': 7}

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

class LuaInjector:
    def __init__(self, hwnd, proc):
        self.hwnd = hwnd
        self.proc = proc
        self.sv = None
        self.ready = False

    def prepare(self):
        """打开「脚本」窗口并聚焦 prompt"""
        if self.ready: return True
        print("  [Lua] 打开「脚本」窗口...")
        click_client(self.hwnd, 230, 15)
        time.sleep(0.4)
        popup = None
        for h in all_visible():
            if 'QWindowPopup' in win32gui.GetClassName(h):
                popup = h; break
        if not popup:
            print("  ✗ 菜单未打开"); return False
        pr = win32gui.GetWindowRect(popup)
        pclick(pr[0] + 137, pr[1] + 31 + 81)
        time.sleep(1.0)
        for h, t, c in all_mgba(self.proc.pid):
            if '脚本' in t:
                self.sv = h; break
        if not self.sv:
            print("  ✗ 未找到「脚本」窗口"); return False
        user32.SetWindowPos(self.sv, 0, 1900, 550, 859, 676, 0x0040)
        time.sleep(0.5)
        pclick(1900 + 500, 550 + 616)
        time.sleep(0.3)
        self.ready = True
        print(f"  [Lua] 「脚本」窗口 {self.sv:#x} 就绪")
        return True

    def inject(self, code):
        for ch in code:
            win32gui.PostMessage(self.sv, win32con.WM_CHAR, ord(ch), 1)
            time.sleep(0.02)
        time.sleep(0.1)
        scan = ctypes.windll.user32.MapVirtualKeyW(0x0D, 0)
        win32gui.PostMessage(self.sv, win32con.WM_KEYDOWN, 0x0D, (scan << 16) | 1)
        time.sleep(0.03)
        win32gui.PostMessage(self.sv, win32con.WM_KEYUP, 0x0D, (scan << 16) | 0xC0000001)
        time.sleep(0.15)

    def send(self, e):
        idx = VK2LUA.get(e['name'])
        if idx is None:
            print(f"  ✗ 无映射 {e['name']}"); return
        cmd = 'addKey' if e['down'] else 'clearKey'
        self.inject(f'emu:{cmd}({idx})')

# ---- 启动 ----
sav_path = Path(ROM_PATH).with_suffix('.sav')
sav_bak = None
if sav_path.exists():
    sav_bak = sav_path.with_name(sav_path.name + '.bak-mixed')
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

# ---- 事件流（全段 0-75s，shorten 后）----
evs = [json.loads(l) for l in open(DEMO, encoding='utf-8') if l.strip()]
keys = [e for e in evs if e['ev'] == 'key']
t_base = keys[0]['t']
events = []
for k in keys:
    t = k['t'] - t_base
    if t > 75000: break
    try: key = Key(k['name'])
    except ValueError: continue
    events.append({'t': t, 'name': k['name'], 'down': k['down']})
events, n = stretch_dir_taps(events)

lua = LuaInjector(hwnd, proc)
t_start = time.monotonic()
i = 0
last_shot = 0
lua_mode = False
print(f"开始混合回放（{len(events)} 事件）")
while i < len(events):
    game_ms = int((time.monotonic() - t_start) * 1000) + t_base
    t_event = events[i]['t']

    # Lua 窗口准备（提前于 Lua 段 1.4s）
    if not lua.ready and t_event >= LUA_START - 1400:
        if not lua.prepare():
            print("✗ Lua 准备失败"); break

    if game_ms < t_event:
        time.sleep(0.01)
        continue

    # 发送
    if LUA_START <= t_event < LUA_END:
        if not lua_mode:
            print(f"  t={t_event}: 切换 Lua 注入模式")
            lua_mode = True
        lua.send(events[i])
    else:
        if lua_mode:
            print(f"  t={t_event}: 恢复 PostMessage")
            lua_mode = False
        e = events[i]
        window_backend.send_vk(window_backend.VK[Key(e['name'])], up=not e['down'], hwnd=hwnd)
    i += 1

    # 每 8s 抓屏验证
    if game_ms - last_shot > 8000:
        img = capture_game(hwnd)
        if img is not None:
            Image.fromarray(img).save(OUT / f"mixed_{game_ms:06d}.png")
            print(f"  t={game_ms}: mean={img.mean():.1f}")
        last_shot = game_ms

time.sleep(2.0)
g_final = capture_game(hwnd)
Image.fromarray(g_final).save(OUT / "mixed_final.png")
print(f"最终 t≈{int((time.monotonic()-t_start)*1000)} mean={g_final.mean():.1f}")

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
