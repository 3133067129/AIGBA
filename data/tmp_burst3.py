"""A×8 连发转场后的名字精确验证（capture_hwnd 240x160 同路径抓屏）。

tmp_burst2 用 PrintWindow 客户区（1278x704）对比失败——缩放伪影 5.4-19.6%。
本实验改用 window_backend.capture_hwnd（NEAREST → 240x160，与录制器同路径），
转场后密集抓屏（100ms 间隔）与录制 51-56s 全部快照对比——同状态 diff 应 <1000px，
名字不同（AAAAAAA vs A）则对话框文字区域差异 → 数千 px。

流程：setup → A×2 推进 → 检测键盘屏 → 连发 A×8 → 转场后 100ms×20 张抓屏 →
对每张找录制 50.8-56s 快照最小 diff → 报告全局最小 diff 及其时间点。

用法：python data/tmp_burst3.py
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

def load_record_shots(t0=50.5, t1=58.0):
    """预载录制快照（50.5-58s）：{(ts, name): img_float}"""
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
    print(f"录制快照预载 {len(rec)} 张（50.5-58s）")
    # A×2 推进 → 检测键盘屏（capture_hwnd）
    for _ in range(2):
        lua_inject(sv, 'emu:addKey(0)', char_sleep=0.02, enter_wait=0.15)
        time.sleep(0.15)
        lua_inject(sv, 'emu:clearKey(0)', char_sleep=0.02, enter_wait=0.15)
    print("A×2 推进完成，检测键盘屏…")
    t_det = None
    hi = 0
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
    # 键盘屏与录制键盘屏对比（进入状态一致性）
    kb = window_backend.capture_hwnd(hwnd)
    best_kb = min(rec, key=lambda r: diff_px(kb, r[1]))
    print(f"键盘屏 vs 录制: min diff={diff_px(kb, best_kb[1])}px @ {best_kb[0]:.3f}s (mean={best_kb[1].mean():.1f})")
    # 连发 A×8
    t_send0 = time.monotonic()
    for i in range(8):
        lua_inject(sv, 'emu:addKey(0)')
        lua_inject(sv, 'emu:clearKey(0)')
    print(f"连发 A×8 完成 {time.monotonic() - t_send0:.2f}s")
    # 转场后密集抓屏 100ms×20
    t_trans = None
    results = []
    for k in range(22):
        time.sleep(0.1)
        img = window_backend.capture_hwnd(hwnd)
        if img is None: continue
        m = img.mean()
        dt = time.monotonic() - t_det
        if m < 50 and t_trans is None:
            t_trans = dt
            print(f"  t={dt:.2f}s 转场黑屏 mean={m:.1f}")
        if t_trans is not None and m > 60:
            best = min(rec, key=lambda r: diff_px(img, r[1]))
            d = diff_px(img, best[1])
            results.append((d, dt, best[0], m))
            print(f"  t={dt:.2f}s mean={m:.1f} vs 录制 min diff={d}px @ {best[0]:.3f}s")
    if results:
        d, dt, bts, m = min(results)
        print(f"\n=== 结论：转场后最佳匹配 diff={d}px @ 回放{dt:.2f}s vs 录制{bts:.3f}s (mean={m:.1f}) ===")
        print(f"（基准：同路径同状态 diff 应 <1000px；名字不同则数千 px）")
    proc.terminate()
    try: proc.wait(timeout=5)
    except Exception: proc.kill()
    sav_path = Path(ROM_PATH).with_suffix('.sav')
    if sav_path.exists():
        sav_path.unlink()

if __name__ == '__main__':
    main()
