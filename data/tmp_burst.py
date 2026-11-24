"""键盘屏「连发注入」实验：验证 REPL 250ms/命令执行节奏 + 键盘屏检测触发。

模型：每次 REPL 执行被 Interrupter 包裹（核心冻结 ~250ms/命令）。逐命令同步等待
太慢（0.66s/命令）；连发（不等执行）则消息队列 FIFO 顺序执行，转场键（第 16 命令）
在 ~4s 后执行完——执行间隙 250ms 恰好构成按住窗口（录制 hold 93-234ms）。

流程：启动 → 注入 demo 到 45.18s → 开「脚本」→ 100ms 抓屏检测键盘屏（mean>140）
→ 连发第 1-8 键（16 命令，快路径 0.008s/字符 + 0.05s wait）→ 抓屏时间线记录转场。

用法：python data/tmp_burst.py
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
# mGBA GBAKey：RIGHT=4 LEFT=5 UP=6 DOWN=7 A=0（勿反）
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
    """快路径连发：WM_CHAR 逐字符 + Enter（不等 REPL 执行，靠队列 FIFO）"""
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
    # 开「脚本」
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
    hwnd, sv, proc = setup()
    print(f"setup 完成（~{time.monotonic() - 0:.1f}）")
    # 录制 45-62s 段（stretch 后）第 1-8 键
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
    # 连发 8×A（16 事件 down/up）——矩阵实验已证 A 单键可转场；机制验证用最简序列
    burst_events = []
    for i in range(8):
        burst_events.append({'t': 0, 'name': 'A', 'down': True})
        burst_events.append({'t': 0, 'name': 'A', 'down': False})
    print(f"连发 {len(burst_events)} 事件（A×8）")
    # ---- 先推进对话到键盘屏（录制 45.2s 起的键在 45180 段之外）----
    # 慢速注入 A×2（tmp_name_seq 已验证：对话屏 A×2 后键盘屏出现）
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
    # ---- 连发 16 命令 ----
    t_send0 = time.monotonic()
    for e in burst_events:
        idx = VK2LUA.get(e['name'])
        if idx is None:
            print(f"  ✗ 无映射 {e['name']}"); continue
        cmd = 'addKey' if e['down'] else 'clearKey'
        lua_inject(sv, f'emu:{cmd}({idx})')
    t_send1 = time.monotonic()
    print(f"连发完成 {t_send1 - t_send0:.2f}s（16 命令）")
    # ---- 抓屏时间线记录转场 ----
    prev = capture_game(hwnd)
    t_trans = None
    t_last = time.monotonic()
    while time.monotonic() - t_last < 12:
        img = capture_game(hwnd)
        if img is not None:
            m = img.mean()
            dt = time.monotonic() - t_det
            if m < 50 and t_trans is None:
                t_trans = dt
                print(f"  t={dt:.2f}s 转场黑屏 mean={m:.1f}")
            if t_trans is not None and m > 60:
                print(f"  t={dt:.2f}s 转场后画面 mean={m:.1f}")
                break
            if dt > 8 and m > 140:
                print(f"  t={dt:.2f}s 仍在键盘屏 mean={m:.1f}（未转场？）")
                t_last = time.monotonic()
        time.sleep(0.1)
    time.sleep(0.5)
    img = capture_game(hwnd)
    if img is not None:
        print(f"最终 mean={img.mean():.1f} dt={(time.monotonic() - t_det):.2f}s")
    proc.terminate()
    try: proc.wait(timeout=5)
    except Exception: proc.kill()
    sav_path = Path(ROM_PATH).with_suffix('.sav')
    if sav_path.exists():
        sav_path.unlink()

if __name__ == '__main__':
    main()
