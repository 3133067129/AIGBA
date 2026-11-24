"""菜单项 y→窗口映射：物理鼠标逐个点击菜单项，记录弹出的窗口标题。

目的：找到「脚本...」（Scripting）菜单项的确切 y。
流程：点 Tools → 对每个候选 y 物理点击 → 记录新窗口标题 → 关闭 → 重开菜单。
"""
import sys, time, subprocess, shutil, ctypes
sys.path.insert(0, '.')
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path
import yaml
import win32con, win32gui, win32process
from src.emulator import window_backend

ROOT = Path('.').resolve()
cfg = yaml.safe_load(open('config/settings.yaml', encoding='utf-8'))
ROM_PATH = str((ROOT / cfg['rom']['path']).resolve())
MGBA_EXE = ROOT / 'mGBA.exe'

user32 = ctypes.windll.user32

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

# ---- 启动 ----
sav_path = Path(ROM_PATH).with_suffix('.sav')
sav_bak = None
if sav_path.exists():
    sav_bak = sav_path.with_name(sav_path.name + '.bak-menu7')
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

# 候选 y（客户区，文字行中心）：7 个菜单项
# 项文字行: 9-20, 31-42, 53-63, 75-86, 97-107, 128-138, 150-160
cands = [15, 37, 58, 81, 102, 133, 155]
OFFSET = 31  # 客户区内容在窗口内偏移
results = {}
for idx, cy in enumerate(cands):
    # 点 Tools 开菜单
    click_client(hwnd, 230, 15)
    time.sleep(0.4)
    popup = None
    for h in all_visible():
        if 'QWindowPopup' in win32gui.GetClassName(h):
            popup = h; break
    if not popup:
        print(f"✗ [{idx}] 菜单未打开"); continue
    pr = win32gui.GetWindowRect(popup)
    before = {(h, t, c) for h, t, c, v, r in all_mgba_windows(proc.pid)}
    sy = pr[1] + OFFSET + cy
    sx = pr[0] + 137
    physical_click(sx, sy)
    new = [w for w in all_mgba_windows(proc.pid) if (w[0], w[1], w[2]) not in before and w[3]]
    titles = [w[1] for w in new if w[1]]
    classes = [w[2] for w in new if w[1]]
    results[cy] = titles
    print(f"[{idx}] 客户区y={cy} → 新窗口: {[(repr(t), c) for t, c in zip(titles, classes)] or '无'}")
    # 关闭弹出的窗口（非主窗口、非 popup）
    for h, t, c, v, r in new:
        if h != hwnd and 'QWindowPopup' not in c:
            win32gui.PostMessage(h, win32con.WM_CLOSE, 0, 0)
            time.sleep(0.3)
    time.sleep(0.3)

print("\n=== y→菜单项 映射 ===")
for cy, titles in results.items():
    print(f"  客户区 y={cy} → {titles}")

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
