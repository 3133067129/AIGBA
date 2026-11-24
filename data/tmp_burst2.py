"""键盘屏 A×8 连发转场后的名字验证：保存转场后截图，与录制转场后对话屏对比。

tmp_burst 已验证 A×8 连发转场（检测后 3.71s 黑屏）。但 A×8 可能是「7 字符名字
填满 + 自动确认 OK」→ 名字=AAAAAAA（用户规则要求名字=A 单字符）。本实验抓取
转场后对话屏截图，与录制快照 t0051047.png（51.047s 对话屏，名字=A 真相）逐像素
diff——diff 小 = 名字正确。

用法：python data/tmp_burst2.py
"""
import sys, time, subprocess, ctypes, json
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
SHOTS = ROOT / 'data/demos/img'

sys.path.insert(0, str(ROOT / 'tools'))
from replay_demo_window import stretch_dir_taps

user32 = ctypes.windll.user32
VK2LUA = {'A': 0, 'B': 1, 'S': 2, 's': 3, '<': 5, '>': 4, '^': 6, 'v': 7,
          'LEFT': 5, 'RIGHT': 4, 'UP': 6, 'DOWN': 7}

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

def lua_inject(sv, code, char_sleep=0.008, enter_wait=0.05):
    for ch in code:
        win32gui.PostMessage(sv, win32con.WM_CHAR, ord(ch), 1)
        time.sleep(char_sleep)
    time.sleep(0.05)
    scan = ctypes.windll.user32.MapVirtualKeyW(0x0D, 0)
    win32gui.PostMessage(sv, win32con.WM_KEYDOWN, 0x0D, (scan << 16) | 1)
    time.sleep(0.01)
    win32gui.PostMessage(sv, win32con.WM_KEYUP, 0x0D, (scan << 16) | 0xC0000001)
    time.sleep(enter_wait)

def setup():
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

def diff_against_record(img):
    """与录制转场后对话屏（名字=A 真相）对比——找最小 diff 的那张"""
    best = (1e9, None)
    # 录制转场黑屏 50.25-50.75s，对话屏 51.0s 起；对比 51.0-55.5s 全部快照
    for f in sorted(SHOTS.glob('demo_20260807_234704_t005*.png')) + \
             sorted(SHOTS.glob('demo_20260807_234704_t005[1-9]*.png')):
        try:
            ts = int(f.stem.split('_t')[1]) / 1000.0
        except ValueError:
            continue
        if not (50.8 <= ts <= 55.0):
            continue
        ref = np.asarray(Image.open(f).convert('RGB'))
        if ref.shape != img.shape:
            continue
        d = (np.abs(img.astype(int) - ref.astype(int)).sum(axis=2) > 60).sum()
        if d < best[0]:
            best = (d, f.name)
    return best

def main():
    hwnd, sv, proc = setup()
    print(f"setup 完成（~{time.monotonic() - 0:.1f}s）")
    # A×2 推进对话 → 检测键盘屏
    for _ in range(2):
        lua_inject(sv, 'emu:addKey(0)', char_sleep=0.02, enter_wait=0.15)
        time.sleep(0.15)
        lua_inject(sv, 'emu:clearKey(0)', char_sleep=0.02, enter_wait=0.15)
    print("A×2 推进完成，检测键盘屏…")
    t_det = None
    hi = 0
    while True:
        img = capture_game(hwnd)
        if img is not None:
            m = img.mean()
            if m > 140:
                hi += 1
                if hi >= 2:
                    t_det = time.monotonic()
                    print(f"键盘屏检测到 t={t_det:.2f} mean={m:.1f}")
                    break
            else:
                hi = 0
        time.sleep(0.1)
    Image.fromarray(capture_game(hwnd)).save('data/kb_screen.png')
    # ---- 连发 A×8（16 命令）----
    t_send0 = time.monotonic()
    for i in range(8):
        lua_inject(sv, 'emu:addKey(0)')
        lua_inject(sv, 'emu:clearKey(0)')
    print(f"连发 A×8 完成 {time.monotonic() - t_send0:.2f}s")
    # ---- 抓屏时间线 + 转场后保存截图 ----
    t_trans = None
    saved = 0
    t_last = time.monotonic()
    while time.monotonic() - t_last < 14:
        img = capture_game(hwnd)
        if img is not None:
            m = img.mean()
            dt = time.monotonic() - t_det
            if m < 50 and t_trans is None:
                t_trans = dt
                print(f"  t={dt:.2f}s 转场黑屏 mean={m:.1f}")
            if t_trans is not None and m > 60 and saved < 4:
                fn = f'data/tmp_burst2_post{dt:.1f}.png'
                Image.fromarray(img).save(fn)
                print(f"  t={dt:.2f}s 转场后画面 mean={m:.1f} → 保存 {fn}")
                d, best = diff_against_record(img)
                print(f"    vs 录制转场后对话屏: diff={d}px (最优匹配 {best})")
                saved += 1
                if saved >= 4:
                    break
            if dt > 10 and m > 140:
                print(f"  t={dt:.2f}s 仍在键盘屏 mean={m:.1f}（未转场？）")
                t_last = time.monotonic()
        time.sleep(0.1)
    time.sleep(0.5)
    img = capture_game(hwnd)
    if img is not None:
        print(f"最终 mean={img.mean():.1f} dt={(time.monotonic() - t_det):.2f}s")
        d, best = diff_against_record(img)
        print(f"最终 vs 录制转场后对话屏: diff={d}px (最优匹配 {best})")
    proc.terminate()
    try: proc.wait(timeout=5)
    except Exception: proc.kill()
    sav_path = Path(ROM_PATH).with_suffix('.sav')
    if sav_path.exists():
        sav_path.unlink()

if __name__ == '__main__':
    main()
