"""键盘屏 Lua 注入 A 键 hold 时长矩阵实验。

每个 hold 值：注入 8 次 A（addKey → sleep(hold) → clearKey），记录：
- 每次注入后画面是否变化（选字/名字框变化）
- 第几次 A 后转场（黑屏 mean<50 或大幅变化）
结论：Lua 路径 A 按住时长 → 确认次数关系（单次确认/连选/无效）。

用法：python data/tmp_hold_matrix.py [hold1 hold2 ...]（默认 100 300 500）
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
DEMO = ROOT / 'data/demos/demo_20260807_234704.jsonl'

sys.path.insert(0, str(ROOT / 'tools'))
from replay_demo_window import stretch_dir_taps

user32 = ctypes.windll.user32

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

def lua_inject(sv, code, char_sleep=0.02, enter_wait=0.15):
    for ch in code:
        win32gui.PostMessage(sv, win32con.WM_CHAR, ord(ch), 1)
        time.sleep(char_sleep)
    time.sleep(0.1)
    scan = ctypes.windll.user32.MapVirtualKeyW(0x0D, 0)
    win32gui.PostMessage(sv, win32con.WM_KEYDOWN, 0x0D, (scan << 16) | 1)
    time.sleep(0.03)
    win32gui.PostMessage(sv, win32con.WM_KEYUP, 0x0D, (scan << 16) | 0xC0000001)
    time.sleep(enter_wait)

def key_hold(sv, idx, hold_ms):
    lua_inject(sv, f'emu:addKey({idx})')
    time.sleep(hold_ms / 1000.0)
    lua_inject(sv, f'emu:clearKey({idx})')

def setup():
    """启动游戏 → 注入到 45180（键盘屏）→ 开脚本窗口 → 返回 (hwnd, sv)"""
    sav_path = Path(ROM_PATH).with_suffix('.sav')
    if sav_path.exists():
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
    # 注入到 45180
    evs = [json.loads(l) for l in open(DEMO, encoding='utf-8') if l.strip()]
    keys = [e for e in evs if e['ev'] == 'key']
    t_base = keys[0]['t']
    events = []
    for k in keys:
        t = k['t'] - t_base
        if t > 45180: break
        try: key = Key(k['name'])
        except ValueError: continue
        events.append({'t': t, 'name': k['name'], 'down': k['down']})
    events, n = stretch_dir_taps(events)
    t_start = time.monotonic()
    i = 0
    while True:
        game_ms = int((time.monotonic() - t_start) * 1000) + t_base
        if game_ms - t_base > 45180: break
        while i < len(events) and events[i]['t'] <= game_ms:
            e = events[i]
            window_backend.send_vk(window_backend.VK[Key(e['name'])], up=not e['down'], hwnd=hwnd)
            i += 1
        time.sleep(0.01)
    time.sleep(1.0)
    # 开脚本
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
    user32.SetWindowPos(sv, 0, 1900, 550, 859, 676, 0x0040)
    time.sleep(0.5)
    pclick(1900 + 500, 550 + 616)
    time.sleep(0.3)
    return hwnd, sv, proc

def main():
    holds = [int(x) for x in sys.argv[1:]] or [100, 300, 500]
    print(f"hold 矩阵: {holds} ms")
    for h in holds:
        print(f"\n===== hold={h}ms =====")
        hwnd, sv, proc = setup()
        kb = capture_game(hwnd)
        prev = kb
        print(f"键盘屏 mean={kb.mean():.1f}")
        result = []
        for n in range(1, 9):
            key_hold(sv, 0, h)   # A
            img = capture_game(hwnd)
            if img is not None and prev is not None and img.shape == prev.shape:
                d = (np.abs(img.astype(int) - prev.astype(int)).sum(axis=2) > 60).sum()
                result.append((n, d, img.mean()))
                print(f"  A#{n}: diff={d}px mean={img.mean():.1f}")
            prev = img
            if img is not None and img.mean() < 50:
                print(f"  → 转场（黑屏）发生在第 {n} 次 A")
                break
        time.sleep(0.5)
        img = capture_game(hwnd)
        if img is not None:
            print(f"  最终 mean={img.mean():.1f}")
        proc.terminate()
        try: proc.wait(timeout=5)
        except Exception: proc.kill()
        sav_path = Path(ROM_PATH).with_suffix('.sav')
        if sav_path.exists():
            sav_path.unlink()
        time.sleep(1.0)

if __name__ == '__main__':
    main()
