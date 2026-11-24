"""命名界面逐键探针：重放到 48.5s（命名界面），然后逐键发送（间隔抓屏），
把 A/LEFT/DOWN/A 每个键的因果效果分开观察。

关键帧时刻（录制）：
  A    @48.577 (down) / 48.719 (up)
  LEFT @48.907 (down) / 49.077 (up)
  DOWN @49.452 (down) / 49.577 (up)
  A    @49.952 (down) / 50.141 (up)
  → 录制 50.55s 转场黑（命名完成）
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

sav_bak = None
if sav.exists():
    sav_bak = sav.with_name(sav.name + '.bak-clean')
    shutil.copy2(sav, sav_bak)
    sav.unlink()
    print('🧹 已备份并删除 .sav')

evs = [json.loads(l) for l in open('data/demos/demo_20260807_234704.jsonl', encoding='utf-8') if l.strip()]
keys = [e for e in evs if e['ev'] == 'key']
keys = [k for k in keys if k['t'] - keys[0]['t'] <= 48000]
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

outdir = Path('data/demos/replay/name_probe')
outdir.mkdir(parents=True, exist_ok=True)
for p in outdir.glob('*.png'):
    p.unlink()

def cap(game_ms):
    img = window_backend.capture_hwnd(hwnd)
    if img is not None:
        Image.fromarray(img).save(outdir / ('t%07d.png' % game_ms))

# 阶段1：重放到 48.5s（正常时间轴）
i = 0
t_start = time.monotonic()
print('阶段1：重放 0-48.5s...', flush=True)
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
    if game_ms - t_base >= 48500 and i >= len(keys):
        break
    if i >= len(keys):
        time.sleep(0.005); continue
    time.sleep(0.005)
print('阶段1完成，进入命名界面。逐键发送：', flush=True)

# 阶段2：逐键发送 + 间隔抓屏
# (键, down时刻ms, up时刻ms, 名称)
seq = [
    ('A', 0, 140),
    ('LEFT', 0, 170),
    ('DOWN', 0, 125),
    ('A', 0, 190),
]
marker = 48500
try:
    for name, down_ms, up_ms in seq:
        # 抓基线
        cap(marker + 50)
        marker += 150
        window_backend.send_vk(window_backend.VK[Key(name)], up=False, hwnd=hwnd)
        time.sleep(down_ms / 1000)
        window_backend.send_vk(window_backend.VK[Key(name)], up=True, hwnd=hwnd)
        time.sleep(0.05)
        cap(marker)          # 按下后 ~50ms
        marker += 150
        cap(marker)          # 松开后 ~150ms
        marker += 150
        print('  %s down@%dms +%dms up' % (name, marker - 300 - 150 - down_ms, down_ms), flush=True)
        time.sleep(0.2)
    # 观察后续 2.5s（是否转场黑）
    for _ in range(12):
        cap(marker)
        marker += 200
    print('完成。')
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
