"""命名界面输入机制探针：重放到 48.3s（命名界面刚出现），然后依次测试
不同按键/不同发送机制，每步抓屏。判定哪个通道能让名字栏输入字母。

测试序列（每步间隔抓屏）：
  A1: PostMessage VK_X（当前机制）          → 若字段出现字母 = 机制OK
  B : PostMessage VK_Z（B=取消/返回）       → 若界面变化 = B 通道OK
  A2: PostMessage VK_X 再按                 → 若 A1 失败则再试
  A3: keybd_event VK_X（真实输入流）        → 若输入 = PostMessage 通道问题
  A4: PostMessage VK_X 变体 lParam          → 排除 lParam 细节
"""
import sys, json, time, subprocess, shutil, ctypes
sys.path.insert(0, '.')
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import numpy as np
import yaml
from pathlib import Path
from PIL import Image
from src.emulator import window_backend
from src.emulator.keys import Key
import win32con, win32gui

ROOT = Path('.').resolve()
cfg = yaml.safe_load(open('config/settings.yaml', encoding='utf-8'))
rom = str((ROOT / cfg['rom']['path']).resolve())
sav = Path(rom).with_suffix('.sav')

sav_bak = None
if sav.exists():
    sav_bak = sav.with_name(sav.name + '.bak-clean')
    shutil.copy2(sav, sav_bak)
    sav.unlink()
    print('🧹 已备份并删除 .sav')

evs = [json.loads(l) for l in open('data/demos/demo_20260807_234704.jsonl', encoding='utf-8') if l.strip()]
keys = [e for e in evs if e['ev'] == 'key']
keys = [k for k in keys if k['t'] - keys[0]['t'] <= 48200]
t_base = keys[0]['t']

proc = subprocess.Popen([str((ROOT/'mGBA.exe').resolve()), rom],
                        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
hwnd = None
t0 = time.time()
while time.time() - t0 < 20 and not hwnd:
    hwnd = window_backend.find_window('mGBA'); time.sleep(0.3)
if not hwnd:
    print('✗ mGBA 窗口未出现'); sys.exit(1)
time.sleep(1.0)
win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
win32gui.SetForegroundWindow(hwnd)
time.sleep(0.3)

outdir = Path('data/demos/replay/key_probe')
outdir.mkdir(parents=True, exist_ok=True)
for p in outdir.glob('*.png'):
    p.unlink()

frames = []
def cap(tag):
    img = window_backend.capture_hwnd(hwnd)
    if img is not None:
        Image.fromarray(img).save(outdir / ('%s.png' % tag))
        frames.append((tag, img))

def field_diff(tag_a, tag_b):
    a = np.asarray(Image.open(outdir/(tag_a+'.png')).convert('RGB')).astype(int)
    b = np.asarray(Image.open(outdir/(tag_b+'.png')).convert('RGB')).astype(int)
    d = (a != b).sum(axis=2)
    return int(d.sum())

# 阶段1：重放到 48.2s
i = 0
t_start = time.monotonic()
print('阶段1：重放至 48.2s...', flush=True)
while True:
    game_ms = int((time.monotonic() - t_start) * 1000) + t_base
    while i < len(keys) and keys[i]['t'] <= game_ms:
        k = keys[i]
        try:
            key = Key(k['name'])
        except ValueError:
            i += 1; continue
        window_backend.send_vk(window_backend.VK[key], up=not k['down'], hwnd=hwnd)
        i += 1
    if game_ms - t_base >= 48000 and i >= len(keys):
        break
    if i >= len(keys):
        time.sleep(0.005); continue
    time.sleep(0.005)
time.sleep(0.35)  # 等淡入完成
cap('00_ready')
print('命名界面就绪，字段 diff 基线。')

def press_post(vk, hold=0.15):
    window_backend.send_vk(vk, up=False, hwnd=hwnd)
    time.sleep(hold)
    window_backend.send_vk(vk, up=True, hwnd=hwnd)
    time.sleep(0.1)

def press_variant(vk, ext=0, scan_override=None):
    """lParam 变体：repeat=0 的 down；scan 可覆盖"""
    scan = scan_override if scan_override is not None else ctypes.windll.user32.MapVirtualKeyW(vk, 0)
    lparam_down = ext | (scan << 16)   # 无 repeat 位
    lparam_up = ext | (scan << 16) | 0x80000000 | 0x40000000
    win32gui.PostMessage(hwnd, win32con.WM_KEYDOWN, vk, lparam_down)
    time.sleep(0.15)
    win32gui.PostMessage(hwnd, win32con.WM_KEYUP, vk, lparam_up)
    time.sleep(0.1)

def press_keybd(vk):
    ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
    time.sleep(0.15)
    ctypes.windll.user32.keybd_event(vk, 0, 2, 0)
    time.sleep(0.1)

try:
    # A1: 当前 PostMessage 机制
    cap('01_beforeA')
    press_post(window_backend.VK[Key.A])
    cap('02_afterA_post')
    print('A1 PostMessage: 字段变化 %d px' % field_diff('01_beforeA', '02_afterA_post'))

    # A2: 再按一次 A（等 500ms 确认无延迟输入）
    time.sleep(0.5)
    cap('03_beforeA2')
    press_post(window_backend.VK[Key.A])
    cap('04_afterA2')
    print('A2 PostMessage again: %d px' % field_diff('03_beforeA2', '04_afterA2'))

    # B: B 键（取消/返回）
    time.sleep(0.5)
    cap('05_beforeB')
    press_post(window_backend.VK[Key.B])
    cap('06_afterB')
    print('B PostMessage: %d px' % field_diff('05_beforeB', '06_afterB'))

    # A3: keybd_event（真实输入流）
    time.sleep(0.5)
    cap('07_beforeKbd')
    press_keybd(window_backend.VK[Key.A])
    cap('08_afterKbd')
    print('A keybd_event: %d px' % field_diff('07_beforeKbd', '08_afterKbd'))

    # A4: PostMessage lParam 变体（无 repeat 位）
    time.sleep(0.5)
    cap('09_beforeVar')
    press_variant(window_backend.VK[Key.A])
    cap('10_afterVar')
    print('A variant lParam: %d px' % field_diff('09_beforeVar', '10_afterVar'))

    # A5: keybd_event LEFT（对照：方向键 keybd_event 是否也动）
    time.sleep(0.5)
    cap('11_beforeKbdL')
    press_keybd(window_backend.VK[Key.LEFT])
    cap('12_afterKbdL')
    print('LEFT keybd_event: %d px' % field_diff('11_beforeKbdL', '12_afterKbdL'))

    # A6: PostMessage LEFT（对照：方向键 PostMessage 是否动）
    time.sleep(0.5)
    cap('13_beforePL')
    press_post(window_backend.VK[Key.LEFT])
    cap('14_afterPL')
    print('LEFT PostMessage: %d px' % field_diff('13_beforePL', '14_afterPL'))
finally:
    for key in list(window_backend.VK):
        window_backend.send_vk(window_backend.VK[key], up=True, hwnd=hwnd)
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        pass
    if sav_bak is not None:
        shutil.copy2(sav_bak, sav)
        sav_bak.unlink(missing_ok=True)
        print('🧹 已恢复 .sav')
