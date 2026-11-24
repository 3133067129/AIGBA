"""菜单点击 v4：QMenu 是 non-native popup（画在主窗口上）。

流程：点击 Tools(x=230,y=15) → 抓主窗口（PrintWindow 应含菜单内容）→
分析菜单栏下方亮像素行（菜单项）→ 点击第 3 项（Scripting）→ 找 ScriptingView →
测试 prompt 输入。
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
            ctypes.windll.user32.PrintWindow(h, save_dc.GetSafeHdc(), 2)
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

def all_visible():
    out = set()
    def cb(h, _):
        if win32gui.IsWindowVisible(h):
            out.add(h)
    win32gui.EnumWindows(cb, None)
    return out

def all_mgba_windows():
    """枚举 mGBA 进程所有顶层窗口（含不可见），返回 [(hwnd, title, class, visible)]"""
    my_pid = proc.pid
    out = []
    def cb(h, _):
        pid = win32process.GetWindowThreadProcessId(h)[1]
        if pid == my_pid:
            out.append((h, win32gui.GetWindowText(h), win32gui.GetClassName(h),
                        win32gui.IsWindowVisible(h), win32gui.GetWindowRect(h)))
    win32gui.EnumWindows(cb, None)
    return out

def dump_mgba(label):
    ws = all_mgba_windows()
    print(f"[{label}] mGBA 顶层窗口 {len(ws)}:")
    for h, t, c, v, r in ws:
        print(f"   {h:#x} vis={v} {repr(t)} {c} rect={r}")

def press_vk(h, vk, hold=0.05):
    scan = ctypes.windll.user32.MapVirtualKeyW(vk, 0)
    win32gui.PostMessage(h, win32con.WM_KEYDOWN, vk, (scan << 16) | 1)
    time.sleep(hold)
    win32gui.PostMessage(h, win32con.WM_KEYUP, vk, (scan << 16) | 0xC0000001)
    time.sleep(0.05)

# ---- 启动 ----
sav_path = Path(ROM_PATH).with_suffix('.sav')
sav_bak = None
if sav_path.exists():
    sav_bak = sav_path.with_name(sav_path.name + '.bak-menu5')
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

# ---- 点击 Tools 菜单 ----
click_client(hwnd, 230, 15)
time.sleep(0.5)
new_w = all_visible() - base - {hwnd}
print("新窗口:", [(f"{h:#x}", win32gui.GetWindowText(h), win32gui.GetClassName(h)) for h in new_w])
# 真正的 QMenu：类名含 QWindowPopup（排除 SysShadow 和主窗口）
popup = None
for h in new_w:
    if 'QWindowPopup' in win32gui.GetClassName(h):
        popup = h
        break
if not popup:
    print("✗ 无 QWindowPopup")
    proc.terminate(); sys.exit(1)
print(f"QMenu popup {popup:#x} rect={win32gui.GetWindowRect(popup)}")

# BitBlt 抓 popup（PrintWindow 对 popup 曾全黑，用 BitBlt）
pimg = hwnd_shot(popup, bitblt=True)
if pimg is None:
    print("✗ popup 抓图失败"); proc.terminate(); sys.exit(1)
Image.fromarray(pimg).save(OUT / "qmenu_x230.png")
print(f"QMenu 截图 {pimg.shape} mean={pimg.mean():.1f}")
# 分析菜单项行（亮像素行聚类）
lum = pimg.sum(axis=2)
rows = (lum > 400).sum(axis=1)
ys = []
prev = -10
for y in range(pimg.shape[0]):
    if rows[y] > 3:
        if y - prev > 8:
            ys.append(y)
        prev = y
print(f"菜单项行 y: {ys}")

if not ys:
    print("✗ QMenu 截图无内容（可能全黑）")
    proc.terminate(); sys.exit(1)

# 菜单项起始行：间隔 > 12 视为新项
items = []
prev = -20
for y in ys:
    if y - prev > 12:
        items.append(y)
    prev = y
print(f"菜单项起始行: {items}")

rc = win32gui.GetClientRect(popup)
p_w = rc[2]

def try_item(label, y, wait=0.8):
    print(f"-- 点击 [{label}] y={y}")
    click_client(popup, p_w // 2, y)
    time.sleep(wait)
    alive = win32gui.IsWindow(popup) and win32gui.IsWindowVisible(popup)
    print(f"   popup 存活: {alive}")
    if not alive:
        time.sleep(0.5)  # 菜单已关，重新打开
    return alive

# 点击第 1 项（View logs... y≈15）验证点击机制
dump_mgba("菜单开")
alive = try_item("View logs y=15", 15)
if not alive:
    print("第 1 项点击后 popup 关闭——点击有效（弹出 View logs 窗口？）")
    dump_mgba("点项1后")
else:
    print("第 1 项点击后 popup 仍开——点击机制无效？")
    # 尝试 SendMessage 同步点击
    lparam = ((15 & 0xFFFF) << 16) | (p_w // 2 & 0xFFFF)
    ctypes.windll.user32.SendMessageW(popup, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lparam)
    time.sleep(0.08)
    ctypes.windll.user32.SendMessageW(popup, win32con.WM_LBUTTONUP, 0, lparam)
    time.sleep(0.8)
    print("SendMessage 后 popup 存活:", win32gui.IsWindow(popup) and win32gui.IsWindowVisible(popup))
    dump_mgba("SendMessage后")
    proc.terminate(); sys.exit(0)

# 重新打开菜单点第 3 项
click_client(hwnd, 230, 15)
time.sleep(0.5)
popup = None
for h in all_visible() - base:
    if 'QWindowPopup' in win32gui.GetClassName(h):
        popup = h; break
print(f"重新打开 popup {popup:#x}" if popup else "✗ 重新打开失败")
if not popup:
    proc.terminate(); sys.exit(1)

target_y = 58  # 第 3 项 Scripting
print(f"点击第 3 项 y={target_y}")
click_client(popup, p_w // 2, target_y)
time.sleep(0.8)
print("点击后 popup 存活:", win32gui.IsWindow(popup) and win32gui.IsWindowVisible(popup))
dump_mgba("点项3后")

# ---- 找 ScriptingView ----
sv = None
for h in all_visible() - base:
    if 'Scripting' in win32gui.GetWindowText(h):
        sv = h; break
if not sv:
    print("✗ 未找到 ScriptingView")
    img2 = hwnd_shot(hwnd)
    if img2 is not None:
        Image.fromarray(img2).save(OUT / "main_after_item3.png")
        print("已存 main_after_item3.png（检查点击效果）")
    for h in all_visible() - base:
        print("  ", f"{h:#x}", repr(win32gui.GetWindowText(h)), win32gui.GetClassName(h))
    proc.terminate(); sys.exit(1)
print(f"✅ ScriptingView {sv:#x} rect={win32gui.GetWindowRect(sv)}")
sv_img = hwnd_shot(sv, bitblt=True)
if sv_img is not None:
    Image.fromarray(sv_img).save(OUT / "scripting_view.png")
    print(f"ScriptingView 截图 {sv_img.shape} mean={sv_img.mean():.1f}")

# ---- 测试 prompt 输入 ----
win32gui.ShowWindow(sv, win32con.SW_RESTORE)
win32gui.SetForegroundWindow(sv)
time.sleep(0.6)
h2, w2 = sv_img.shape[:2] if sv_img is not None else (600, 843)
click_client(sv, w2 // 2, h2 - 15)
time.sleep(0.3)
# 输入: console:log("PROBE_OK")
for ch in 'console:log("PROBE_OK")':
    if ch.isalpha():
        vk = ord(ch.upper())
    elif ch == '(': vk = 0x28
    elif ch == ')': vk = 0x29
    elif ch == '"': vk = 0xDE
    elif ch == '_': vk = 0xBD
    elif ch == ':': vk = 0xBA
    else: continue
    if ch.isupper() or ch in '("_:':
        sscan = ctypes.windll.user32.MapVirtualKeyW(0xA0, 0)
        win32gui.PostMessage(sv, win32con.WM_KEYDOWN, 0xA0, (sscan << 16) | 1)
        time.sleep(0.02)
        press_vk(sv, vk)
        win32gui.PostMessage(sv, win32con.WM_KEYUP, 0xA0, (sscan << 16) | 0xC0000001)
        time.sleep(0.02)
    else:
        press_vk(sv, vk)
    time.sleep(0.02)
time.sleep(0.2)
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
