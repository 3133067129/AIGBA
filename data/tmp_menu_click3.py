"""菜单点击 v3：点击 Tools(客户区x≈230) → BitBlt 抓 popup → 分析菜单行 → 点击第 3 项(Scripting)。

成功后：ScriptingView 打开 → 点击 prompt → PostMessage 输入 dofile 一行 → Enter。
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
            ctypes.windll.gdi32.BitBlt(save_dc.GetSafeHdc(), 0, 0, w, d,
                                       hwnd_dc, 0, 0, win32con.SRCCOPY)
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
    out = []
    def cb(h, _):
        if win32gui.IsWindowVisible(h):
            out.append(h)
    win32gui.EnumWindows(cb, None)
    return set(out)

def press_vk(h, vk, hold=0.05):
    scan = ctypes.windll.user32.MapVirtualKeyW(vk, 0)
    win32gui.PostMessage(h, win32con.WM_KEYDOWN, vk, (scan << 16) | 1)
    time.sleep(hold)
    win32gui.PostMessage(h, win32con.WM_KEYUP, vk, (scan << 16) | 0xC0000001)
    time.sleep(0.05)

def type_text(h, text):
    """输入 ASCII 文本（简单映射，含特殊字符转义不做——先只支持普通字符）。"""
    shift_map = {'"': 0xDE, '(': 0x28, ')': 0x29, '_': 0xBD, ':': 0xBA, '/': 0xBF, '\\': 0xDC, '.': 0xBE, ',': 0xBC}
    for ch in text:
        if ch.isupper() or ch in '!"#$%&\'()*+,-./:;<=>?@[\\]^_`{|}~':
            shift = ch in '!@#$%^&*()_+{}|:"<>?~'
            # 简化：只处理字母数字和少量标点
            if ch.isalpha():
                vk = ord(ch.upper())
            elif ch.isdigit():
                vk = ord(ch)
            elif ch in shift_map:
                vk = shift_map[ch]
            else:
                continue
            if ch.isupper() or ch in '!"#$%&\'()*+,-./:;<=>?@[\\]^_`{|}~':
                # Shift 组合
                sscan = ctypes.windll.user32.MapVirtualKeyW(0xA0, 0)
                win32gui.PostMessage(h, win32con.WM_KEYDOWN, 0xA0, (sscan << 16) | 1)
                time.sleep(0.02)
                press_vk(h, vk)
                win32gui.PostMessage(h, win32con.WM_KEYUP, 0xA0, (sscan << 16) | 0xC0000001)
                time.sleep(0.02)
            else:
                press_vk(h, vk)
        else:
            press_vk(h, ord(ch.upper()))

# ---- 启动 ----
sav_path = Path(ROM_PATH).with_suffix('.sav')
sav_bak = None
if sav_path.exists():
    sav_bak = sav_path.with_name(sav_path.name + '.bak-menu4')
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

# ---- 点击 Tools 菜单（x=230, y=15）----
click_client(hwnd, 230, 15)
time.sleep(0.4)
new_w = all_visible() - base - {hwnd}
print("新窗口:", [(f"{h:#x}", win32gui.GetWindowText(h), win32gui.GetClassName(h)) for h in new_w])
popup = None
for h in new_w:
    if win32gui.GetWindowText(h) == '' and win32gui.GetParent(h) == 0:
        popup = h
        break
if not popup:
    print("✗ 无 popup"); proc.terminate(); sys.exit(1)
print(f"popup {popup:#x} rect={win32gui.GetWindowRect(popup)}")

# ---- BitBlt 抓 popup ----
pimg = hwnd_shot(popup, bitblt=True)
if pimg is None:
    print("✗ popup 抓图失败"); proc.terminate(); sys.exit(1)
Image.fromarray(pimg).save(OUT / "popup_x230_bitblt.png")
print(f"popup BitBlt 截图 {pimg.shape} mean={pimg.mean():.1f}")
lum = pimg.sum(axis=2)
rows = (lum > 400).sum(axis=1)
ys = []
prev = -10
for y in range(pimg.shape[0]):
    if rows[y] > 3:
        if y - prev > 8: ys.append(y)
        prev = y
print(f"菜单行 y: {ys}")

# ---- 点击第 3 项（Scripting...）----
rc = win32gui.GetClientRect(popup)
p_w = rc[2]
if len(ys) >= 3:
    target = ys[2] + 6
else:
    target = 70  # 估算
print(f"点击菜单第 3 项 y={target}")
click_client(popup, p_w // 2, target)
time.sleep(0.8)

# ---- 找 ScriptingView ----
sv = None
for h in all_visible() - base:
    if 'Scripting' in win32gui.GetWindowText(h):
        sv = h
        break
if not sv:
    print("✗ 未找到 ScriptingView（枚举新窗口）")
    for h in all_visible() - base:
        print("  ", f"{h:#x}", repr(win32gui.GetWindowText(h)), win32gui.GetClassName(h))
    proc.terminate(); sys.exit(1)
print(f"✅ ScriptingView {sv:#x} rect={win32gui.GetWindowRect(sv)}")
sv_img = hwnd_shot(sv, bitblt=True)
if sv_img is not None:
    Image.fromarray(sv_img).save(OUT / "scripting_view.png")
    print(f"ScriptingView 截图 {sv_img.shape} mean={sv_img.mean():.1f}")

# ---- 测试 prompt 输入（dofile 一行）----
win32gui.ShowWindow(sv, win32con.SW_RESTORE)
win32gui.SetForegroundWindow(sv)
time.sleep(0.5)
h2, w2 = sv_img.shape[:2] if sv_img is not None else (600, 800)
# 点击 prompt 区域（底部，右半部）
click_client(sv, w2 // 2, h2 - 15)
time.sleep(0.3)
# 输入: console:log("PROBE_OK")
code = 'console:log("PROBE_OK")'
type_text(sv, code)
time.sleep(0.3)
# Enter 执行
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
