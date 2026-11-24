"""菜单栏扫描点击 v2：逐步点击菜单栏 → 找 QMenu popup → 逐项点击 → 找 ScriptingView。

策略：客户区 y=15 处从左到右每 40px 点击一次；弹出 popup 后抓图分析菜单项行，
逐项点击（每次点击后枚举新窗口）；找到 ScriptingView（标题含 Scripting）即成功。
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

def hwnd_shot(h):
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
        pid = win32process.GetWindowThreadProcessId(h)[1]
        if win32gui.IsWindowVisible(h):
            out.append((h, pid, win32gui.GetWindowText(h), win32gui.GetClassName(h)))
    win32gui.EnumWindows(cb, None)
    return out

def menu_lines(img):
    """分析菜单 popup 的行位置（亮像素行聚类）。"""
    bright = (img.sum(axis=2) > 500)
    rows = bright.sum(axis=1)
    ys = []
    prev = -10
    for y in range(img.shape[0]):
        if rows[y] > 5:
            if y - prev > 8:
                ys.append(y)
            prev = y
    return ys

# ---- 启动 ----
sav_path = Path(ROM_PATH).with_suffix('.sav')
sav_bak = None
if sav_path.exists():
    sav_bak = sav_path.with_name(sav_path.name + '.bak-menu3')
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
base = set(h for h, *_ in all_visible())

# 扫描菜单栏（客户区 y=15，x 从 30 到 700 每 40px）
W = 1278
found_sv = None
popup = None
for x in range(30, min(W, 800), 40):
    click_client(hwnd, x, 15)
    new = [(h, pid, t, c) for h, pid, t, c in all_visible() if h not in base and h != hwnd]
    popups = [h for h, pid, t, c in new if win32gui.GetParent(h) == 0 and t == '']
    if popups:
        popup = popups[0]
        r = win32gui.GetWindowRect(popup)
        print(f"✅ x={x} 弹出 popup {popup:#x} rect={r}")
        pimg = hwnd_shot(popup)
        if pimg is None:
            print("  popup 截图失败，跳过")
            click_client(hwnd, x, 15)  # 再点一次关闭
            time.sleep(0.3)
            continue
        Image.fromarray(pimg).save(OUT / f"popup_x{x}.png")
        ys = menu_lines(pimg)
        print(f"  popup {pimg.shape} 菜单行 y: {ys}")
        # 逐项点击
        rc = win32gui.GetClientRect(popup)
        p_w = rc[2]
        sv_found = False
        for iy, yy in enumerate(ys):
            click_client(popup, p_w // 2, yy + 4)
            time.sleep(0.3)
            new2 = [(h, pid, t, c) for h, pid, t, c in all_visible() if h not in base and h != hwnd and h != popup]
            sv = [h for h, pid, t, c in new2 if 'Scripting' in t]
            if sv:
                print(f"  ✅ 菜单项 {iy} (y={yy}) → ScriptingView {sv}")
                found_sv = sv[0]
                sv_found = True
                sv_img = hwnd_shot(found_sv)
                if sv_img is not None:
                    Image.fromarray(sv_img).save(OUT / f"scripting_{found_sv:x}.png")
                    print(f"  ScriptingView 截图 {sv_img.shape} 已存")
                break
            else:
                # 关闭可能打开的对话框/子菜单
                for h2, pid2, t2, c2 in new2:
                    if h2 != found_sv:
                        win32gui.PostMessage(h2, win32con.WM_CLOSE, 0, 0)
                time.sleep(0.3)
        if sv_found:
            break
        # 关闭 popup（点击空白处）
        click_client(hwnd, 100, 100)
        time.sleep(0.3)
        base = set(h for h, *_ in all_visible()) if False else base
    else:
        print(f"  x={x}: 无 popup")

# 若找到 ScriptingView：输入 dofile 测试
if found_sv:
    print("\n=== 测试 ScriptingView prompt 输入 ===")
    win32gui.ShowWindow(found_sv, win32con.SW_RESTORE)
    win32gui.SetForegroundWindow(found_sv)
    time.sleep(0.5)
    # 点击 prompt（底部 QLineEdit 位置：截图分析或估算——底部 y≈0.9H）
    sv_img = hwnd_shot(found_sv)
    if sv_img is not None:
        h2, w2 = sv_img.shape[:2]
        click_client(found_sv, w2 // 2, h2 - 20)
        time.sleep(0.3)
        # 输入一行 Lua
        import string
        code = 'console:log("PROBE_OK")\n'
        for ch in code:
            vk = ord(ch.upper()) if ch.isalpha() else {
                '(': 0x28, ')': 0x29, '"': 0xDE, '_': 0xBD, ':': 0xBA}.get(ch)
            if vk:
                scan = ctypes.windll.user32.MapVirtualKeyW(vk, 0)
                win32gui.PostMessage(found_sv, win32con.WM_KEYDOWN, vk, (scan << 16) | 1)
                time.sleep(0.03)
                win32gui.PostMessage(found_sv, win32con.WM_KEYUP, vk, (scan << 16) | 0xC0000001)
                time.sleep(0.03)
        # Enter 执行
        scan = ctypes.windll.user32.MapVirtualKeyW(0x0D, 0)
        win32gui.PostMessage(found_sv, win32con.WM_KEYDOWN, 0x0D, (scan << 16) | 1)
        time.sleep(0.05)
        win32gui.PostMessage(found_sv, win32con.WM_KEYUP, 0x0D, (scan << 16) | 0xC0000001)
        time.sleep(1.0)
        sv_img2 = hwnd_shot(found_sv)
        if sv_img2 is not None:
            Image.fromarray(sv_img2).save(OUT / f"scripting_after_input_{found_sv:x}.png")
            print("输入后截图已存 scripting_after_input.png")
        print("（输入尝试完成——检查 scripting_after_input 截图确认）")
else:
    print("✗ 未找到 ScriptingView")

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
