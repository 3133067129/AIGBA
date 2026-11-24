"""键盘屏方向键实验：B1=[A,LEFT,DOWN,A] 连发能否转场 + 方向键 hold 滚动诊断。

第三次运行 burst [A,LEFT,DOWN,A] 未转场（52.95s 仍键盘屏）；tmp_kb_lua 完整
18 键慢速注入转场成功（55.2s）。差异候选：方向键 hold≈250ms 滚动（光标移多格）、
键盘屏进入状态不同、连发执行间隙不足。本实验直接测 B1 连发转场：

阶段1 键盘屏检测（capture_hwnd 240x160 同路径）→ 与录制键盘屏 diff（状态一致性）
阶段2 B1=[A,LEFT,DOWN,A] 连发（快路径）→ 12s 窗口检测转场（mean<50）
阶段3 若未转场：C1=[A,LEFT,DOWN,A] + 慢速注入方向键变体（LEFT/DOWN 前加 sleep 让
       核心运行窗口）→ 再检测转场
阶段4 转场后抓屏（240x160）→ 与录制 51-56s 快照全局最小 diff → 名字判定

用法：python data/tmp_kb_dir.py
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
VK2LUA = {'A': 0, 'B': 1, 'S': 2, 's': 3, 'LEFT': 5, 'RIGHT': 4, 'UP': 6, 'DOWN': 7}

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

def burst(sv, names, pad=0.0):
    """连发键序（每键 addKey+clearKey）；pad=键间额外 sleep（慢速变体）"""
    for name in names:
        idx = VK2LUA.get(name)
        if idx is None:
            continue
        lua_inject(sv, f'emu:addKey({idx})')
        if pad:
            time.sleep(pad)
        lua_inject(sv, f'emu:clearKey({idx})')
        if pad:
            time.sleep(pad)

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

def load_record_shots(t0=48.0, t1=58.0):
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

def wait_transition(hwnd, t_det, timeout=14.0):
    """等转场：mean<50 黑屏 → mean>60 转场后画面。返回 (dt_trans, dt_post, m_post) 或 None。
    用绝对时间（time.monotonic() - t_det 只用于打印；循环退出用 timeout 控制）"""
    t_trans = None; t_post = None; m_post = None
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        img = window_backend.capture_hwnd(hwnd)
        if img is not None:
            m = img.mean()
            dt = time.monotonic() - t_det
            if m < 50 and t_trans is None:
                t_trans = dt
                print(f"  t={dt:.2f}s 转场黑屏 mean={m:.1f}")
            if t_trans is not None and m > 60:
                t_post = dt; m_post = m
                print(f"  t={dt:.2f}s 转场后画面 mean={m:.1f}")
                return t_trans, t_post, m_post
        time.sleep(0.1)
    return None

def main():
    hwnd, sv, proc = setup()
    print(f"setup 完成（~{time.monotonic() - 0:.1f}s）")
    rec = load_record_shots()
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
    kb = window_backend.capture_hwnd(hwnd)
    best = min(rec, key=lambda r: diff_px(kb, r[1]))
    print(f"键盘屏 vs 录制: min diff={diff_px(kb, best[1])}px @ {best[0]:.3f}s (rec mean={best[1].mean():.1f})")
    Image.fromarray(kb).save('data/kb_screen_240.png')
    # ---- 阶段2：B1=[A,LEFT,DOWN,A] 连发转场 ----
    print("\n--- 阶段2：B1=[A,LEFT,DOWN,A] 连发 ---")
    t0 = time.monotonic()
    burst(sv, ['A', 'LEFT', 'DOWN', 'A'])
    print(f"连发完成 {time.monotonic() - t0:.2f}s")
    r = wait_transition(hwnd, t_det)
    if r is not None:
        t_trans, t_post, m_post = r
        img = window_backend.capture_hwnd(hwnd)
        best = min(rec, key=lambda x: diff_px(img, x[1]))
        d0 = diff_px(img, best[1])
        print(f"B1 转场成功！转场后 vs 录制: min diff={d0}px @ {best[0]:.3f}s")
        # 转场后注入 1 次对话 A（推进 1 行）再对比（双对比：0 推进/1 推进）
        time.sleep(0.3)
        burst(sv, ['A'])
        time.sleep(0.6)
        img2 = window_backend.capture_hwnd(hwnd)
        best2 = min(rec, key=lambda x: diff_px(img2, x[1]))
        d1 = diff_px(img2, best2[1])
        print(f"B1 推进1次后 vs 录制: min diff={d1}px @ {best2[0]:.3f}s (mean={img2.mean():.1f})")
        print(f"  → 若 d0/d1 任一 <800px = 同行同名字（名字=A ✅）；若均 >2000px = 名字/状态不同 ✗")
    else:
        print("B1 未转场（12s+ 仍在键盘屏）→ 阶段3 慢速变体")
        # ---- 阶段3：C1=[A,LEFT,DOWN,A] 慢速（键间 pad 0.5s 给核心运行窗口）----
        print("\n--- 阶段3：C1 慢速变体 pad=0.5s ---")
        t0 = time.monotonic()
        burst(sv, ['A', 'LEFT', 'DOWN', 'A'], pad=0.5)
        print(f"慢速连发完成 {time.monotonic() - t0:.2f}s")
        r = wait_transition(hwnd, t_det)
        if r is not None:
            t_trans, t_post, m_post = r
            img = window_backend.capture_hwnd(hwnd)
            best = min(rec, key=lambda x: diff_px(img, x[1]))
            print(f"C1 转场成功！转场后 vs 录制: min diff={diff_px(img, best[1])}px @ {best[0]:.3f}s")
        else:
            print("C1 也未转场")
    proc.terminate()
    try: proc.wait(timeout=5)
    except Exception: proc.kill()
    sav_path = Path(ROM_PATH).with_suffix('.sav')
    if sav_path.exists():
        sav_path.unlink()

if __name__ == '__main__':
    main()
