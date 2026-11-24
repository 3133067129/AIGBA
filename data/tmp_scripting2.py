"""ScriptingView 输入 v2：验证聚焦 + WM_CHAR 文本输入路径。

流程：开「脚本」→ 物理点击 prompt → 抓 3 帧找输入光标（验证聚焦）→
PostMessage WM_CHAR 输入 console:log("PROBE_OK") → Enter → 截图对比。
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

def hwnd_shot(h):
    left, top, right, bottom = win32gui.GetClientRect(h)
    w, d = right - left, bottom - top
    if w <= 0 or d <= 0: return None
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

def click_client(h, x, y):
    lparam = ((y & 0xFFFF) << 16) | (x & 0xFFFF)
    win32gui.PostMessage(h, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lparam)
    time.sleep(0.08)
    win32gui.PostMessage(h, win32con.WM_LBUTTONUP, 0, lparam)
    time.sleep(0.5)

def physical_click(x, y):
    user32.SetCursorPos(x, y)
    time.sleep(0.12)
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    time.sleep(0.1)
    user32.mouse_event(0x0004, 0, 0, 0, 0)
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

def diff_region(a, b, y0, y1, label):
    if a is None or b is None or a.shape != b.shape:
        print(f"  [{label}] 不可比"); return
    d = (np.abs(a[y0:y1].astype(int) - b[y0:y1].astype(int)).sum(axis=2) > 60)
    print(f"  [{label}] y{y0}-{y1} 差异像素 {d.sum()}")

# ---- 启动 ----
sav_path = Path(ROM_PATH).with_suffix('.sav')
sav_bak = None
if sav_path.exists():
    sav_bak = sav_path.with_name(sav_path.name + '.bak-scr2')
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

# ---- 打开「脚本」 ----
click_client(hwnd, 230, 15)
time.sleep(0.4)
popup = None
for h in all_visible():
    if 'QWindowPopup' in win32gui.GetClassName(h):
        popup = h; break
if not popup:
    print("✗ 菜单未打开"); proc.terminate(); sys.exit(1)
pr = win32gui.GetWindowRect(popup)
physical_click(pr[0] + 137, pr[1] + 31 + 81)
time.sleep(1.0)
sv = None
for h, t, c, v, r in all_mgba_windows(proc.pid):
    if '脚本' in t:
        sv = h; break
if not sv:
    print("✗ 未找到「脚本」窗口"); proc.terminate(); sys.exit(1)
r = win32gui.GetWindowRect(sv)
print(f"「脚本」窗口 {sv:#x} rect={r}")
img0 = hwnd_shot(sv)

# ---- 物理点击 prompt（客户区 500,610）----
client_off = (r[3] - r[1]) - img0.shape[0]
sx, sy = r[0] + 500, r[1] + client_off + 610
print(f"标题栏偏移 {client_off}，物理点击 ({sx},{sy})")
physical_click(sx, sy)
time.sleep(0.3)

# ---- 抓 3 帧找输入光标（prompt 区 y600-620 差异）----
frames = [hwnd_shot(sv) for _ in range(3)]
for i in range(1, 3):
    diff_region(frames[0], frames[i], 595, 625, f"光标帧{i}")
# 也检查是否有焦点高亮（边框）
print(f"  prompt 区 mean: {frames[0][600:620, 200:750].mean():.1f}")

# ---- PostMessage WM_CHAR 输入 ----
code = 'console:log("PROBE_OK")'
for ch in code:
    win32gui.PostMessage(sv, win32con.WM_CHAR, ord(ch), 1)
    time.sleep(0.03)
time.sleep(0.3)
img_chars = hwnd_shot(sv)
diff_region(img0, img_chars, 590, 630, "WM_CHAR 输入后 prompt")

# ---- Enter 执行 ----
scan = ctypes.windll.user32.MapVirtualKeyW(0x0D, 0)
win32gui.PostMessage(sv, win32con.WM_KEYDOWN, 0x0D, (scan << 16) | 1)
time.sleep(0.05)
win32gui.PostMessage(sv, win32con.WM_KEYUP, 0x0D, (scan << 16) | 0xC0000001)
time.sleep(1.5)
img_enter = hwnd_shot(sv)
Image.fromarray(img_enter).save(OUT / "scripting_wmchar_after.png")
print(f"WM_CHAR+Enter 后截图已存 mean={img_enter.mean():.1f}")
diff_region(img_chars, img_enter, 50, 590, "Enter 后 log 区")

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
