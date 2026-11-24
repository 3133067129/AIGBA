"""键盘屏「名字输入序列」实验：UP + A×4 + LEFT + DOWN + A... 转场测试。

背景：replay 的 stretch 把方向键缩短到 100ms，tmp_kb_lua 方向键长按 0.54s——
同样 8 个键，tmp_kb_lua 转场而 replay 不转场。测方向键 hold 对名字输入的影响：
每轮注入「UP + A×4 + LEFT + DOWN + 然后 A 直到转场或 8 次」，统计第几个 A 转场。

用法：python data/tmp_name_seq.py [dir_hold] [a_hold]（默认 100 150）
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
VK2LUA = {'A': 0, 'B': 1, 'S': 2, 's': 3, '<': 4, '>': 5, '^': 6, 'v': 7,
          'LEFT': 4, 'RIGHT': 5, 'UP': 6, 'DOWN': 7}

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

def lua_inject(sv, code):
    for ch in code:
        win32gui.PostMessage(sv, win32con.WM_CHAR, ord(ch), 1)
        time.sleep(0.02)
    time.sleep(0.1)
    scan = ctypes.windll.user32.MapVirtualKeyW(0x0D, 0)
    win32gui.PostMessage(sv, win32con.WM_KEYDOWN, 0x0D, (scan << 16) | 1)
    time.sleep(0.03)
    win32gui.PostMessage(sv, win32con.WM_KEYUP, 0x0D, (scan << 16) | 0xC0000001)
    time.sleep(0.15)

def key_hold(sv, name, hold_ms):
    idx = VK2LUA[name]
    lua_inject(sv, f'emu:addKey({idx})')
    time.sleep(hold_ms / 1000.0)
    lua_inject(sv, f'emu:clearKey({idx})')

def setup():
    """启动 → 注入到 45180 → A×2 进入键盘屏 → 开脚本窗口 → (hwnd, sv, proc)"""
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

def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else 'replay'
    timed = False
    if mode == 'timed':
        timed = True
        mode = 'replay'
    if mode == 'replay':
        # 用录制真实 hold（stretch 后）——完全复刻 replay 的 Lua 段
        evs = [json.loads(l) for l in open(DEMO, encoding='utf-8') if l.strip()]
        keys = [e for e in evs if e['ev'] == 'key']
        t_base = keys[0]['t']
        seg = []
        for k in keys:
            t = k['t'] - t_base
            if 45180 < t <= 62000:
                try: key = Key(k['name'])
                except ValueError: continue
                seg.append({'t': t, 'name': k['name'], 'down': k['down']})
        seg, n = stretch_dir_taps(seg)
        seq = []
        seg_ts = []
        for k in seg:
            if not k['down']:
                continue  # send_pressed 跳过配对 up
            # 找配对 up 的 hold（stretch 后）
            hold = 150
            for u in seg:
                if u['name'] == k['name'] and not u['down'] and u['t'] > k['t']:
                    hold = u['t'] - k['t']
                    break
            seq.append((k['name'], hold))
            seg_ts.append(k['t'])
        print(f"录制序列 {len(seq)} 键: {[(n, h) for n, h in seq]}")
    else:
        dir_hold = int(mode)
        a_hold = int(sys.argv[2]) if len(sys.argv) > 2 else 150
        seq = [('UP', dir_hold)] + [('A', a_hold)] * 4 \
            + [('LEFT', dir_hold), ('DOWN', dir_hold)] + [('A', a_hold)] * 8
        print(f"固定 hold: 方向={dir_hold}ms, A={a_hold}ms")
    hwnd, sv, proc = setup()
    # 进入键盘屏（对话推进 A×2；--no-a2 时跳过——replay 真实对照）
    if '--no-a2' not in sys.argv:
        key_hold(sv, 'A', 150)
        key_hold(sv, 'A', 150)
    # --dir300: 方向键 hold 提升到 300ms（Lua 路径对话屏短按无效的修复实验）
    if '--dir300' in sys.argv:
        seq = [(n, 300 if n in ('UP', 'LEFT', 'DOWN', 'RIGHT') else h) for n, h in seq]
        print(f"方向键 hold 提升到 300ms")
    kb = capture_game(hwnd)
    print(f"键盘屏 baseline mean={kb.mean():.1f}")
    prev = kb
    # 名字序列：UP + A×4 + LEFT + DOWN + A×8（timed 模式按录制时刻调度）
    t_start = time.monotonic()
    last_cap = 0.0
    for i, (name, h) in enumerate(seq, 1):
        if timed:
            # 录制事件时刻（t_base 偏移），等 game_ms 到达
            t_ev = seg_ts[i - 1] if i <= len(seg_ts) else 62000
            while int((time.monotonic() - t_start) * 1000) + 0 < t_ev:
                time.sleep(0.01)
        # verify 抓屏模拟：每 500ms 抓主窗口（与 replay 同节奏）
        if timed and (time.monotonic() - t_start) * 1000 - last_cap >= 500:
            capture_game(hwnd)
            last_cap = (time.monotonic() - t_start) * 1000
        key_hold(sv, name, h)
        img = capture_game(hwnd)
        if img is not None and prev is not None and img.shape == prev.shape:
            d = (np.abs(img.astype(int) - prev.astype(int)).sum(axis=2) > 60).sum()
            print(f"  #{i:2d} {name:4s} hold={h}: diff={d}px mean={img.mean():.1f}")
            if img.mean() < 50:
                print(f"  → 转场发生在第 {i} 个键")
                break
        prev = img
    time.sleep(0.5)
    img = capture_game(hwnd)
    if img is not None:
        print(f"最终 mean={img.mean():.1f}")
    proc.terminate()
    try: proc.wait(timeout=5)
    except Exception: proc.kill()
    sav_path = Path(ROM_PATH).with_suffix('.sav')
    if sav_path.exists():
        sav_path.unlink()

if __name__ == '__main__':
    main()
