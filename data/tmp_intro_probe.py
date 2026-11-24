"""前 30s 回放探针：200ms 抓屏 + SendInput 返回值 + 实际发送时刻日志"""
import sys, json, time, subprocess, ctypes
sys.path.insert(0, '.')
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import numpy as np
import yaml
from pathlib import Path
from PIL import Image
from src.emulator import window_backend
from src.emulator.keys import Key

ROOT = Path('.').resolve()
cfg = yaml.safe_load(open('config/settings.yaml', encoding='utf-8'))
rom = str((ROOT / cfg['rom']['path']).resolve())

def send_vk_checked(vk, up):
    """SendInput 并返回返回值（1=成功，0=失败）。"""
    inp = window_backend.INPUT()
    inp.type = window_backend.INPUT_KEYBOARD
    inp.ki.wVk = vk
    inp.ki.dwFlags = window_backend.KEYEVENTF_KEYUP if up else 0
    return ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(window_backend.INPUT))

evs = [json.loads(l) for l in open('data/demos/demo_20260807_234704.jsonl', encoding='utf-8') if l.strip()]
keys = [e for e in evs if e['ev'] == 'key']
keys = [k for k in keys if k['t'] - keys[0]['t'] <= 30000]
t_base = keys[0]['t']

proc = subprocess.Popen([str((ROOT/'mGBA.exe').resolve()), rom],
                        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
import win32con, win32gui
t0 = time.time(); hwnd = None
while time.time() - t0 < 20 and not hwnd:
    hwnd = window_backend.find_window('mGBA'); time.sleep(0.3)
time.sleep(1.0)
win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
win32gui.SetForegroundWindow(hwnd)
time.sleep(0.3)

out = []  # (game_ms, 亮度, 对话px)
log = []  # (scheduled_ms, sent_ms, vk_name, down, ret)
i = 0
last_cap = -1e9
t_start = time.monotonic()
while True:
    game_ms = int((time.monotonic() - t_start) * 1000) + t_base
    while i < len(keys) and keys[i]['t'] <= game_ms:
        k = keys[i]
        try:
            key = Key(k['name'])
        except ValueError:
            i += 1; continue
        sent_ms = int((time.monotonic() - t_start) * 1000) + t_base
        ret = send_vk_checked(window_backend.VK[key], up=not k['down'])
        log.append((k['t'], sent_ms, k['name'], k['down'], ret))
        i += 1
    if game_ms - last_cap >= 200:
        last_cap = game_ms
        img = window_backend.capture_hwnd(hwnd)
        if img is not None:
            reg = img[96:158, 8:232]
            dlg = int((reg.mean(axis=2) > 100).sum())
            out.append((game_ms, float(img.mean()), dlg))
    if i >= len(keys):
        break
    time.sleep(0.005)
for key in list(window_backend.VK):
    send_vk_checked(window_backend.VK[key], up=True)
proc.terminate()
try:
    proc.wait(timeout=5)
except Exception:
    pass

print('=== SendInput 日志（预定t -> 实际t 键 下/上 返回值）===')
fails = [l for l in log if l[4] != 1]
for l in log:
    dn = 'down' if l[3] else 'up'
    mark = '  <<< FAIL' if l[4] != 1 else ''
    print(f'{l[0]:>7}ms -> {l[1]:>7}ms {l[2]:5} {dn:4} ret={l[4]}{mark}')
print(f'共 {len(log)} 次发送，失败 {len(fails)} 次')
for f in fails:
    print(f'  失败: 预定t={f[0]} 实际t={f[1]} {f[2]} {f[3]} ret={f[4]}')
print()
print('=== 200ms 采样轨迹 (t, 亮度, 对话px) ===')
for t, m, d in out:
    print(f'{t:>7} {m:>6.1f} {d:>7}')
