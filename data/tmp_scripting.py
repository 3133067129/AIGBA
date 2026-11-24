"""打开「脚本」窗口（ScriptingView）→ 截图分析 → 输入 console:log("PROBE_OK") → 验证。

菜单映射（已实测）：客户区 y=81 = 「脚本」。
流程：点 Tools → 物理点击 (1486, 204+31+81=316) → 找「脚本」窗口 → 截图 →
分析 QLineEdit（底部）→ PostMessage 输入 → Enter → 截图对比。
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

def press_vk(h, vk, hold=0.05):
    scan = ctypes.windll.user32.MapVirtualKeyW(vk, 0)
    win32gui.PostMessage(h, win32con.WM_KEYDOWN, vk, (scan << 16) | 1)
    time.sleep(hold)
    win32gui.PostMessage(h, win32con.WM_KEYUP, vk, (scan << 16) | 0xC0000001)
    time.sleep(0.05)

def type_text(h, text):
    shift_map = {'"': 0xDE, '(': 0x28, ')': 0x29, '_': 0xBD, ':': 0xBA, '/': 0xBF, '.': 0xBE, ',': 0xBC, ' ': 0x20, '=': 0xBB, ';': 0xBA}
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

def diff_regions(a, b, label):
    """找两图差异像素多的行区域（文本出现/变化位置）。"""
    if a is None or b is None or a.shape != b.shape:
        print(f"  [{label}] 图不可比 {None if a is None else a.shape} vs {None if b is None else b.shape}")
        return
    diff = (np.abs(a.astype(int) - b.astype(int)).sum(axis=2) > 60)
    rows = diff.sum(axis=1)
    ys = [y for y in range(len(rows)) if rows[y] > 2]
    # 聚类
    clusters = []
    prev = -10
    for y in ys:
        if y - prev > 8: clusters.append([y, y])
        else: clusters[-1][1] = y
        prev = y
    print(f"  [{label}] 差异行簇: {[(a, b) for a, b in clusters]} 总差异像素 {diff.sum()}")

# ---- 启动 ----
sav_path = Path(ROM_PATH).with_suffix('.sav')
sav_bak = None
if sav_path.exists():
    sav_bak = sav_path.with_name(sav_path.name + '.bak-scr')
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

# ---- 打开「脚本」窗口 ----
click_client(hwnd, 230, 15)
time.sleep(0.4)
popup = None
for h in all_visible():
    if 'QWindowPopup' in win32gui.GetClassName(h):
        popup = h; break
if not popup:
    print("✗ 菜单未打开"); proc.terminate(); sys.exit(1)
pr = win32gui.GetWindowRect(popup)
print(f"popup rect={pr}")
physical_click(pr[0] + 137, pr[1] + 31 + 81)   # 客户区 y=81 → 窗口 y=112 → 屏幕 y=316
time.sleep(1.0)

sv = None
for h, t, c, v, r in all_mgba_windows(proc.pid):
    if '脚本' in t:
        sv = h; break
if not sv:
    print("✗ 未找到「脚本」窗口")
    for h, t, c, v, r in all_mgba_windows(proc.pid):
        print("  ", f"{h:#x}", repr(t), c, v, r)
    proc.terminate(); sys.exit(1)
print(f"✅ 「脚本」窗口 {sv:#x} rect={win32gui.GetWindowRect(sv)}")

# ---- 截图分析 ----
time.sleep(0.5)
img1 = hwnd_shot(sv, bitblt=True)
if img1 is None:
    print("✗ 「脚本」窗口截图失败"); proc.terminate(); sys.exit(1)
Image.fromarray(img1).save(OUT / "scripting_view.png")
H, W = img1.shape[:2]
print(f"「脚本」窗口 {img1.shape} mean={img1.mean():.1f}")

# 分析结构：找底部 prompt 条（QLineEdit 白色背景行）与 log 区
gray = img1.mean(axis=2)
# 找白色/亮色行（输入框背景）
white_rows = (gray > 200).sum(axis=1)
print("白色行分布（找输入框）:")
prev = -10
for y in range(H):
    if white_rows[y] > W * 0.3:
        if y - prev > 5:
            print(f"  y={y} 宽 {white_rows[y]}")
        prev = y

# prompt 位置：客户区 y≈610（log 区 y50-590，底部 QLineEdit y600-620），x≈500（buffers 右侧）
# 窗口→屏幕：客户区 (0,0) = 窗口左上 + 标题栏偏移 39px（窗口 676 - 客户区 637）
r = win32gui.GetWindowRect(sv)
client_off = (r[3] - r[1]) - H  # 窗口高 - 客户区高 = 标题栏
print(f"标题栏偏移 {client_off}")
sx = r[0] + 500
sy = r[1] + client_off + 610
print(f"物理点击 prompt 屏幕坐标 ({sx}, {sy})")
physical_click(sx, sy)
time.sleep(0.3)

# ---- 输入测试 ----
type_text(sv, 'console:log("PROBE_OK")')
time.sleep(0.3)
scan = ctypes.windll.user32.MapVirtualKeyW(0x0D, 0)
win32gui.PostMessage(sv, win32con.WM_KEYDOWN, 0x0D, (scan << 16) | 1)
time.sleep(0.05)
win32gui.PostMessage(sv, win32con.WM_KEYUP, 0x0D, (scan << 16) | 0xC0000001)
time.sleep(1.5)
img2 = hwnd_shot(sv, bitblt=True)
if img2 is not None:
    Image.fromarray(img2).save(OUT / "scripting_view_after.png")
    print(f"输入后截图已存 mean={img2.mean():.1f}")
    diff_regions(img1, img2, "PROBE_OK 输入后")

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
