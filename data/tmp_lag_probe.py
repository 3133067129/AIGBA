"""回放前 52s 高精度探针：200ms 抓屏 + 按键实际发送时刻 vs 计划时刻。

目的：定位调钟界面卡死的根因 —— 测量回放游戏状态相对录制的时间滞后，
并确认 A@48.577（录制中在调钟界面出现后 27ms 按下）在回放中是否打在
转场黑屏上被吞。
"""
import sys, json, time, subprocess, shutil
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

# --clean-sav：备份/删除，结束恢复
sav_bak = None
if sav.exists():
    sav_bak = sav.with_name(sav.name + '.bak-clean')
    shutil.copy2(sav, sav_bak)
    sav.unlink()
    print('🧹 已备份并删除 .sav')

evs = [json.loads(l) for l in open('data/demos/demo_20260807_234704.jsonl', encoding='utf-8') if l.strip()]
keys = [e for e in evs if e['ev'] == 'key']
keys = [k for k in keys if k['t'] - keys[0]['t'] <= 52000]
t_base = keys[0]['t']

proc = subprocess.Popen([str((ROOT/'mGBA.exe').resolve()), rom],
                        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
hwnd = None
t0 = time.time()
while time.time() - t0 < 20 and not hwnd:
    hwnd = window_backend.find_window('mGBA'); time.sleep(0.3)
if not hwnd:
    print('✗ mGBA 窗口未出现')
    sys.exit(1)
time.sleep(1.0)
win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
win32gui.SetForegroundWindow(hwnd)
time.sleep(0.3)

outdir = Path('data/demos/replay/lag_probe')
outdir.mkdir(parents=True, exist_ok=True)
for p in outdir.glob('*.png'):
    p.unlink()

log = []   # (计划ms, 实际ms, 键, 下/上, 实际-计划)
out = []   # (game_ms, 亮度, text_px)
i = 0
last_cap = -1e9
t_start = time.monotonic()
try:
    while True:
        game_ms = int((time.monotonic() - t_start) * 1000) + t_base
        while i < len(keys) and keys[i]['t'] <= game_ms:
            k = keys[i]
            try:
                key = Key(k['name'])
            except ValueError:
                i += 1
                continue
            actual = int((time.monotonic() - t_start) * 1000) + t_base
            window_backend.send_vk(window_backend.VK[key], up=not k['down'], hwnd=hwnd)
            log.append((k['t'], actual, k['name'], k['down'], actual - k['t']))
            i += 1
        if game_ms - last_cap >= 200:
            last_cap = game_ms
            img = window_backend.capture_hwnd(hwnd)
            if img is not None:
                reg = img[96:158, 8:232]
                dlg = int((reg.mean(axis=2) > 100).sum())
                out.append((game_ms, float(img.mean()), dlg))
                Image.fromarray(img).save(outdir / ('t%07d.png' % game_ms))
        if i >= len(keys):
            break
        time.sleep(0.005)
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

print('\n=== 按键发送延迟（实际-计划）==='.encode('utf-8', 'replace').decode())
lags = [l[4] for l in log]
print('总按键 %d，延迟 min=%d med=%d max=%d ms' % (len(lags), min(lags), int(np.median(lags)), max(lags)))
print('\n=== 关键窗口按键（45-51s）===')
for l in log:
    if 45000 <= l[0] <= 51000:
        print('%7dms 实际%+7dms %s %s' % (l[0], l[4], l[2], 'down' if l[3] else 'up'))
print('\n=== 200ms 轨迹（47-52s 加粗输出）===')
for t, m, d in out:
    mark = ' *' if 47000 <= t <= 52000 else ''
    print('%7d %6.1f %6d%s' % (t, m, d, mark))
