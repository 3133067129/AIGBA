"""A×8 转场 + 对话推进 A×7 后的画面与录制全局对比——名字/推进对齐验证。

假设（2026-08-08）：回放 A×2 推进后进入的键盘屏（mean 160.7）与录制
（mean 150.2）是不同变体——回放是「默认名字确认屏」，A 连按=选是转场
（A×8 三次复现转场）；录制 UP+A×3 到达「名字输入屏」。若默认名字=A，
A×8 转场后名字=A（用户规则 ✅）。转场后 A×7 快路径推进 7 次对话——
推进完成后画面与录制 55-62s 快照对比：diff 小 = 名字同+推进对齐。

流程：setup → A×2 → 检测键盘屏 → burst A×8 → 检测转场 → burst A×7 →
抓屏（0.5s×8 张）→ 每张对录制 54-62.5s 全部快照找 min diff。

用法：python data/tmp_burst4.py
"""
import sys, time, subprocess, ctypes, json, re
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

def burst(sv, names):
    for name in names:
        idx = {'A': 0, 'B': 1, 'S': 2, 's': 3, 'LEFT': 5, 'RIGHT': 4, 'UP': 6, 'DOWN': 7}.get(name)
        if idx is None:
            continue
        lua_inject(sv, f'emu:addKey({idx})')
        lua_inject(sv, f'emu:clearKey({idx})')

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

def load_record_shots(t0=54.0, t1=62.5):
    out = []
    for f in SHOTS.glob('demo_20260807_234704_*.png'):
        m = re.search(r'_t(\d+)\.png', f.name)
        if not m: continue
        ts = int(m.group(1)) / 1000.0
        if t0 <= ts <= t1:
            out.append((ts, np.asarray(Image.open(f).convert('RGB')).astype(int)))
    out.sort()
    return out

def diff_px(a, b):
    return int((np.abs(a - b).sum(axis=2) > 60).sum())

def main():
    hwnd, sv, proc = setup()
    print(f"setup 完成（~{time.monotonic() - 0:.1f}s）")
    rec = load_record_shots()
    print(f"录制快照预载 {len(rec)} 张（54-62.5s）")
    # A×2 推进 → 检测键盘屏
    for _ in range(2):
        lua_inject(sv, 'emu:addKey(0)', char_sleep=0.02, enter_wait=0.15)
        time.sleep(0.15)
        lua_inject(sv, 'emu:clearKey(0)', char_sleep=0.02, enter_wait=0.15)
    print("A×2 推进完成，检测键盘屏…")
    t_det = None; hi = 0
    while True:
        img = window_backend.capture_hwnd(hwnd)
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
    # burst A×8 → 转场
    t0 = time.monotonic()
    burst(sv, ['A'] * 8)
    print(f"A×8 连发完成 {time.monotonic() - t0:.2f}s，等转场…")
    t_trans = None
    while time.monotonic() - t0 < 10:
        img = window_backend.capture_hwnd(hwnd)
        if img is not None:
            m = img.mean()
            if m < 50 and t_trans is None:
                t_trans = time.monotonic()
                print(f"  转场黑屏 t={t_trans - t_det:.2f}s mean={m:.1f}")
            if t_trans is not None and m > 60:
                print(f"  转场后画面 t={time.monotonic() - t_det:.2f}s mean={m:.1f}")
                break
        time.sleep(0.1)
    else:
        print("  ⚠️ 未检测到转场")
    # 转场后 A×7 推进（快路径）
    time.sleep(0.4)
    t1 = time.monotonic()
    burst(sv, ['A'] * 7)
    print(f"A×7 推进连发完成 {time.monotonic() - t1:.2f}s")
    # 抓屏 8 张（每 0.5s）→ 对比录制 54-62.5s
    best_overall = (1e9, None, None)
    for k in range(8):
        time.sleep(0.5)
        img = window_backend.capture_hwnd(hwnd)
        if img is None: continue
        m = img.mean()
        dt = time.monotonic() - t_det
        best = min(rec, key=lambda r: diff_px(img, r[1]))
        d = diff_px(img, best[1])
        print(f"  回放 t={dt:.2f}s mean={m:.1f} vs 录制 min diff={d}px @ {best[0]:.3f}s (rec mean={best[1].mean():.1f})")
        if d < best_overall[0]:
            best_overall = (d, dt, best[0])
    d, dt, bts = best_overall
    print(f"\n=== 结论：全局最小 diff={d}px @ 回放{dt:.2f}s vs 录制{bts:.3f}s ===")
    print("（<1000px = 名字 A + 推进对齐 ✅；2000-4000px = 名字错或推进差；>8000px = 发散 ✗）")
    proc.terminate()
    try: proc.wait(timeout=5)
    except Exception: proc.kill()
    sav_path = Path(ROM_PATH).with_suffix('.sav')
    if sav_path.exists():
        sav_path.unlink()

if __name__ == '__main__':
    main()
