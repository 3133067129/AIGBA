"""菜单点击 v5：物理鼠标（SetCursorPos + mouse_event）点击 QMenu 第 3 项。

假设：QMenu 客户区内容在窗口内垂直偏移 ~31px（337-275=62 阴影）。
先验证 SetCursorPos 生效，再点击屏幕坐标 (1486, 262+31=293)。
成功后：找 ScriptingView → 点击 prompt → 输入 PROBE_OK → 截图验证。
"""
import sys, time, subprocess, shutil, ctypes
sys.path.insert(0, '.')
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path
import numpy as np, yaml
import win32con, win32gui, win32process, win32ui
from PIL import Image
from src.emulator import window_backend

ROOT = Path('.').resolve()
cfg = yaml.safe_load(open('config/settings.yaml', encoding='utf-8'))
ROM_PATH = str((ROOT / cfg['rom']['path']).resolve())
MGBA_EXE = ROOT / 'mGBA.exe'
OUT = ROOT / 'data' / 'demos' / 'replay'

user32 = ctypes.windll.user32

def hwnd_shot(h, bitblt=False):
    try:
        left, top, right, bottom = win32gui.GetClientRect(h)
        w, d = right - left, bottom - top
        if w <= 0 or d <= 0: return None
        hwnd_dc = win32gui.GetWindowDC(h)
        mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
        save_dc = mfc_dc.CreateCompatibleDC()
        bmp = win32ui.CreateBitmap()
        bmp.CreateCompatibleBitmap(mfc_dc, w, d)
        save_dc.SelectObject(bmp)
        if bitblt:
            ctypes.windll.gdi32.BitBlt(save_dc.GetSafeHdc(), 0, 0, w, d, hwnd_dc, 0, 0, win32con.SRCCOPY)
        else:
            user32.PrintWindow(h, save_dc.GetSafeHdc(), 2)
        bits = bmp.GetBitmapBits(True)
        im = Image.frombuffer("RGB", (w, d), bits, "raw", "BGRX", 0, 1)
        save_dc.DeleteDC(); mfc_dc.DeleteDC(); win32gui.ReleaseDC(h, hwnd_dc)
        return np.asarray(im)
    except Exception:
        return None

def click_client(h, x, y):
    lparam = ((y & 0xFFFF) << 16) | (x & 0xFFFF)
    win32gui.PostMessage(h, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lparam)
    time.sleep(0.08)
    win32gui.PostMessage(h, win32con.WM_LBUTTONUP, 0, lparam)
    time.sleep(0.5)

def physical_click(x, y):
    r = user32.SetCursorPos(x, y)
    time.sleep(0.12)
    if not r:
        print(f"  SetCursorPos({x},{y}) 返回 {r}")
    cx = ctypes.c_long(); cy = ctypes.c_long()
    user32.GetCursorPos(ctypes.byref(cx), ctypes.byref(cy))
    print(f"  SetCursorPos → ({cx.value},{cy.value})")
    user32.mouse_event(0x0002, 0, 0, 0, 0)  # LEFTDOWN
    time.sleep(0.1)
    user32.mouse_event(0x0004, 0, 0, 0, 0)  # LEFTUP
    time.sleep(0.8)

def all_visible():
    out = set()
    def cb(h, _):
        if win32gui.IsWindowVisible(h):
            out.add(h)
    win32gui.EnumWindows(cb, None)
    return out

def all_mgba_windows(pid):
    out = []
    def cb(h, _):
        if win32process.GetWindowThreadProcessId(h)[1] == pid:
            out.append((h, win32gui.GetWindowText(h), win32gui.GetClassName(h),
                        win32gui.IsWindowVisible(h), win32gui.GetWindowRect(h)))
    win32gui.EnumWindows(cb, None)
    return out

def dump_mgba(pid, label):
    ws = all_mgba_windows(pid)
    print(f"[{label}] mGBA 顶层窗口 {len(ws)}:")
    for h, t, c, v, r in ws:
        print(f"   {h:#x} vis={v} {repr(t)} {c} rect={r}")

def press_vk(h, vk, hold=0.05):
    scan = ctypes.windll.user32.MapVirtualKeyW(vk, 0)
    win32gui.PostMessage(h, win32con.WM_KEYDOWN, vk, (scan << 16) | 1)
    time.sleep(hold)
    win32gui.PostMessage(h, win32con.WM_KEYUP, vk, (scan << 16) | 0xC0000001)
    time.sleep(0.05)

def type_text(h, text):
    """PostMessage 输入 ASCII 文本（带 Shift 处理）。"""
    shift_map = {'"': 0xDE, '(': 0x28, ')': 0x29, '_': 0xBD, ':': 0xBA, '/': 0xBF, '.': 0xBE, ',': 0xBC, ' ': 0x20}
    for ch in text:
        need_shift = ch.isupper() or ch in '!"#$%&\'()*+,-./:;<=>?@[\\]^_`{|}~'
        if ch.isalpha():
            vk = ord(ch.upper())
        elif ch.isdigit():
            vk = ord(ch)
        elif ch in shift_map:
            vk = shift_map[ch]
        else:
            continue
        if need_shift:
            sscan = ctypes.windll.user32.MapVirtualKeyW(0xA0, 0)
            win32gui.PostMessage(h, win32con.WM_KEYDOWN, 0xA0, (sscan << 16) | 1)
            time.sleep(0.02)
            press_vk(h, vk)
            win32gui.PostMessage(h, win32con.WM_KEYUP, 0xA0, (sscan << 16) | 0xC0000001)
            time.sleep(0.02)
        else:
            press_vk(h, vk)
        time.sleep(0.02)

# ---- 启动 ----
sav_path = Path(ROM_PATH).with_suffix('.sav')
sav_bak = None
if sav_path.exists():
    sav_bak = sav_path.with_name(sav_path.name + '.bak-menu6')
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
time.sleep(2.0)
print(f"主窗口 {hwnd:#x}")
base = all_visible()

# ---- 测 SetCursorPos / mouse_event 是否被拦 ----
r = user32.SetCursorPos(500, 500)
time.sleep(0.15)
cx = ctypes.c_long(); cy = ctypes.c_long()
user32.GetCursorPos(ctypes.byref(cx), ctypes.byref(cy))
print(f"SetCursorPos(500,500) → ({cx.value},{cy.value})  鼠标被拦={cx.value != 500}")
if cx.value != 500:
    print("✗ huǒróng 拦截了 SetCursorPos，物理鼠标路线不可用")
    proc.terminate(); sys.exit(1)

# ---- 点击 Tools 菜单（物理）----
click_client(hwnd, 230, 15)  # 菜单栏点击 PostMessage 有效（已证实）
time.sleep(0.5)
popup = None
for h in all_visible() - base:
    if 'QWindowPopup' in win32gui.GetClassName(h):
        popup = h; break
if not popup:
    print("✗ 无 popup"); proc.terminate(); sys.exit(1)
pr = win32gui.GetWindowRect(popup)
print(f"popup {popup:#x} rect={pr}")
dump_mgba(proc.pid, "菜单开")

# ---- 物理点击第 3 项（Scripting）----
# 内容偏移 31px 假设：客户区 y 53-63 → 窗口 y 84-94 → 屏幕 y = 204+84..94
# x: 1349+137=1486
sx = pr[0] + 137
sy_candidates = [pr[1] + 31 + 58, pr[1] + 58, pr[1] + 58 + 31 + 20]  # 偏移31 / 无偏移 / 再试
hit = False
for sy in sy_candidates:
    print(f"物理点击 ({sx},{sy})")
    physical_click(sx, sy)
    found = [w for w in all_mgba_windows(proc.pid) if 'Scripting' in w[1] and w[2] != 'Qt51516QWindowPopupDropShadowSaveBits']
    popup_alive = any(win32gui.IsWindowVisible(h) for h, t, c, v, r in all_mgba_windows(proc.pid) if 'QWindowPopup' in c)
    print(f"  ScriptingView 窗口: {found} popup可见: {popup_alive}")
    if found or not popup_alive:
        hit = True
        break
if not hit:
    print("✗ 物理点击均无效/未命中")
    proc.terminate(); sys.exit(1)
print("✅ 菜单项点击命中！")

# ---- 找 ScriptingView ----
sv = None
for h, t, c, v, r in all_mgba_windows(proc.pid):
    if 'Scripting' in t and c != 'Qt51516QWindowPopupDropShadowSaveBits':
        sv = h; break
if not sv:
    dump_mgba(proc.pid, "点击后")
    proc.terminate(); sys.exit(1)
print(f"✅ ScriptingView {sv:#x} rect={win32gui.GetWindowRect(sv)}")
sv_img = hwnd_shot(sv, bitblt=True)
if sv_img is not None:
    Image.fromarray(sv_img).save(OUT / "scripting_view.png")
    print(f"ScriptingView 截图 {sv_img.shape} mean={sv_img.mean():.1f}")

# ---- 测试 prompt 输入 ----
win32gui.ShowWindow(sv, win32con.SW_RESTORE)
time.sleep(0.5)
h2, w2 = sv_img.shape[:2] if sv_img is not None else (600, 800)
click_client(sv, w2 // 2, h2 - 15)   # 点击底部 prompt（QLineEdit 通常在最底）
time.sleep(0.3)
type_text(sv, 'console:log("PROBE_OK")')
time.sleep(0.3)
scan = ctypes.windll.user32.MapVirtualKeyW(0x0D, 0)
win32gui.PostMessage(sv, win32con.WM_KEYDOWN, 0x0D, (scan << 16) | 1)
time.sleep(0.05)
win32gui.PostMessage(sv, win32con.WM_KEYUP, 0x0D, (scan << 16) | 0xC0000001)
time.sleep(1.5)
sv_img2 = hwnd_shot(sv, bitblt=True)
if sv_img2 is not None:
    Image.fromarray(sv_img2).save(OUT / "scripting_view_after.png")
    print(f"输入后截图已存 scripting_view_after.png mean={sv_img2.mean():.1f}")

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
