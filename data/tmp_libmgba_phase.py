"""headless 事件落点分析：每个按键按下时刻的游戏状态（mean 亮度）。
判定 A@48280/LEFT@48610/DOWN@49155/finalA@49655 落在 对话屏/黑屏/键盘屏 哪个阶段。
同时输出键盘屏出现的精确帧。
"""
import sys, json
sys.path.insert(0, '.')
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import numpy as np
import yaml
from pathlib import Path
from src.emulator.mgba_core import Emulator
from src.emulator.keys import Key

ROOT = Path('.').resolve()
cfg = yaml.safe_load(open('config/settings.yaml', encoding='utf-8'))
rom = str((ROOT / cfg['rom']['path']).resolve())
DEMO = ROOT / 'data/demos/demo_20260807_234704.jsonl'
FPS = 59.7275
KEY_MARK = {47078: 'A', 48280: 'A*', 48610: 'LEFT', 49155: 'DOWN', 49655: 'A-fin'}


def frame_of(t_ms):
    return int(round(t_ms / 1000.0 * FPS))


evs = [json.loads(l) for l in open(DEMO, encoding='utf-8') if l.strip()]
keys = [e for e in evs if e['ev'] == 'key']
t_base = keys[0]['t']
events = []
for k in keys:
    if k['t'] - t_base > 51500:
        break
    try:
        key = Key(k['name'])
    except ValueError:
        continue
    events.append((frame_of(k['t'] - t_base), key, k['down'], k['t'] - t_base))
ev_frames = events

em = Emulator(rom)
em.core.reset()
ei = 0
f = 0
f_end = frame_of(51500)
last_snap = -1e9
key_land = {}
while f < f_end:
    while ei < len(ev_frames) and ev_frames[ei][0] <= f:
        _, name, down, t_ms = ev_frames[ei]
        if down:
            mean = float(em.screenshot().mean())
            key_land[t_ms] = mean
            tag = KEY_MARK.get(t_ms, name)
            print('down@%dms (帧%d): mean=%.1f' % (t_ms, f, mean))
        if down:
            em.press_hold(name)
        else:
            em.release()
        ei += 1
    em.run_frames(1)
    f += 1
    t_ms = int(f / FPS * 1000)
    if t_ms - last_snap >= 50:
        last_snap = t_ms
        mean = float(em.screenshot().mean())
        if 46000 <= t_ms <= 51500:
            print('  %dms: mean=%.1f' % (t_ms, mean))
em.release()
