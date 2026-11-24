"""菜单栏鼠标点击实验：分析菜单栏文本 x 位置 → 点击 Tools → 弹 QMenu → 分析并点击 Scripting...。

流程：启动 mGBA（无 .sav）→ 抓主窗口截图 → 顶部 0-35px 行暗像素 x 分布找菜单项文本 →
PostMessage 点击 Tools 菜单 → 枚举 QMenu popup → 抓 popup 截图 → 分析菜单项 y 位置 →
点击 Scripting... 项 → 枚举 ScriptingView 窗口 → 验证其存在与大小。
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
OUT.mkdir(parents=True, exist_ok=True)

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

def click_client(h, x, y, btn=win32con.MK_LBUTTON):
    lparam = ((y & 0xFFFF) << 16) | (x & 0xFFFF)
    win32gui.PostMessage(h, win32con.WM_LBUTTONDOWN, btn, lparam)
    time.sleep(0.1)
    win32gui.PostMessage(h, win32con.WM_LBUTTONUP, 0, lparam)
    time.sleep(0.4)

def find_new(before):
    out = []
    def cb(h, _):
        pid = win32process.GetWindowThreadProcessId(h)[1]
        if h not in before and win32gui.IsWindowVisible(h):
            out.append((h, pid, win32gui.GetWindowText(h), win32gui.GetClassName(h)))
    win32gui.EnumWindows(cb, None)
    return out

# ---- 启动 ----
sav_path = Path(ROM_PATH).with_suffix('.sav')
sav_bak = None
if sav_path.exists():
    sav_bak = sav_path.with_name(sav_path.name + '.bak-menu2')
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

# ---- 分析菜单栏文本位置 ----
img = hwnd_shot(hwnd)
print(f"主窗口尺寸 {img.shape}")
H, W = img.shape[:2]
bar = img[:40]
bright = (bar.sum(axis=2) > 500)  # 亮像素（文字）
col = bright.sum(axis=0)
# 找亮像素簇（连续列 >1 亮像素）
clusters, start = [], None
for x in range(W):
    if col[x] > 1:
        if start is None: start = x
    else:
        if start is not None:
            clusters.append((start, x - 1))
            start = None
if start is not None: clusters.append((start, W - 1))
print("菜单栏亮像素簇（x 范围）:")
for i, (a, b) in enumerate(clusters):
    if b - a > 10:  # 菜单项文本宽 >10px
        print(f"  [{i}] x {a}-{b} 中心 {(a+b)//2}")
Image.fromarray(img).save(OUT / "menu_bar_full.png")

# ---- 点击 Tools（第 4 个菜单项：File Emulation View Tools）----
# 文本簇按 x 排序，取第 4 个
menus = [(a, b) for a, b in clusters if b - a > 15]
if len(menus) < 4:
    print(f"✗ 菜单项不足: {len(menus)}")
else:
    a, b = menus[3]
    cx = (a + b) // 2
    cy = 15  # 菜单栏中间高度
    print(f"点击 Tools 菜单: 客户区 ({cx}, {cy})")
    before_set = {h for h, *_ in find_new([])}
    click_client(hwnd, cx, cy)
    new = find_new(before_set)
    print("点击后新窗口:", [(f"{h:#x}", pid, t, c) for h, pid, t, c in new])
    # 找 QMenu popup（新可见窗口）
    popup = None
    for h, pid, t, c in new:
        if pid == proc.pid or 'mGBA' in t:
            popup = h
            break
    if popup:
        time.sleep(0.3)
        pimg = hwnd_shot(popup)
        if pimg is not None:
            Image.fromarray(pimg).save(OUT / f"menu_popup_{popup:x}.png")
            print(f"popup 截图 {pimg.shape} 已存 menu_popup_{popup:x}.png")
            # 分析菜单项（左侧文本行）
            dark2 = (pimg.sum(axis=2) < 450)
            rows = dark2.sum(axis=1)
            line_y = []
            for y in range(pimg.shape[0]):
                if rows[y] > 10 and (not line_y or y - line_y[-1] > 5):
                    line_y.append(y)
            print(f"菜单行 y 位置: {line_y}")
            # 点击「Scripting...」（Tools 菜单项列表：Game Sensors... / Scripting... 等，取有 'S' 开头的行——数值分析难；先点第几个需要看 Tools 菜单结构）
            # mGBA 0.10.5 Tools 菜单顺序：Asset View / Battle Chip / Game Sensors / Scripting / Audio log / Logging / Scripting...
            # 逐个点击菜单项并枚举新窗口（找到 ScriptingView 即成功）
            r = win32gui.GetClientRect(popup)
            p_w, p_h = r[2], r[3]
            for idx, y in enumerate(line_y):
                click_client(popup, p_w // 2, y + 5)
                time.sleep(0.3)
                found = find_new(before_set)
                script_view = [h for h, pid, t, c in found if 'Scripting' in t]
                if script_view:
                    print(f"  ✅ 第 {idx} 项 (y={y}) 打开: {script_view}")
                    sv = script_view[0]
                    sv_img = hwnd_shot(sv)
                    if sv_img is not None:
                        Image.fromarray(sv_img).save(OUT / f"scripting_view_{sv:x}.png")
                        print(f"  ScriptingView 截图 {sv_img.shape} 已存")
                    # 关闭 ScriptingView（Esc 或点击关闭按钮）
                    win32gui.PostMessage(sv, win32con.WM_CLOSE, 0, 0)
                    break
                else:
                    print(f"  第 {idx} 项 (y={y}): 无新窗口（{[(f'{h:#x}',t) for h,pid,t,c in found]}）")
                    # 若弹出子菜单或对话框需关闭
                    for h, pid, t, c in found:
                        win32gui.PostMessage(h, win32con.WM_CLOSE, 0, 0)
                    time.sleep(0.3)
        else:
            print("popup 截图失败")

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
