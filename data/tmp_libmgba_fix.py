"""无头验证回放修复语义：DOWN hold 352ms（录制 125ms），final A 保持录制时刻。
跑 3 次验证可重复性。
"""
import sys, json
sys.path.insert(0, '.')
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import numpy as np
import yaml
from pathlib import Path
from PIL import Image
from src.emulator.mgba_core import Emulator
from src.emulator.keys import Key

ROOT = Path('.').resolve()
cfg = yaml.safe_load(open('config/settings.yaml', encoding='utf-8'))
rom = str((ROOT / cfg['rom']['path']).resolve())
DEMO = ROOT / 'data/demos/demo_20260807_234704.jsonl'
FPS = 59.7275
FE_THRESH = 135.0


def frame_of(t_ms):
    return int(round(t_ms / 1000.0 * FPS))


def run(down_hold_ms, label, final_off_ms=1525):
    evs = [json.loads(l) for l in open(DEMO, encoding='utf-8') if l.strip()]
    keys = [e for e in evs if e['ev'] == 'key']
    t_base = keys[0]['t']
    events = []
    for k in keys:
        if k['t'] - t_base > 47800:
            break
        try:
            key = Key(k['name'])
        except ValueError:
            continue
        events.append((frame_of(k['t'] - t_base), key, k['down']))
    em = Emulator(rom)
    em.core.reset()
    ei = 0
    f = 0
    while f < frame_of(47800):
        while ei < len(events) and events[ei][0] <= f:
            _, name, down = events[ei]
            if down:
                em.press_hold(name)
            else:
                em.release()
            ei += 1
        em.run_frames(1)
        f += 1
    em.release()
    fe_frame = None
    while f < frame_of(51000):
        em.run_frames(1)
        f += 1
        if f % 3 == 0 and em.screenshot().mean() > FE_THRESH:
            fe_frame = f
            break

    # A down@fe+150 hold 142
    while f < fe_frame + frame_of(150): em.run_frames(1); f += 1
    em.press_hold(Key.A)
    for _ in range(frame_of(142)): em.run_frames(1); f += 1
    em.release()
    # LEFT down@fe+480 hold 170
    while f < fe_frame + frame_of(480): em.run_frames(1); f += 1
    em.press_hold(Key.LEFT)
    for _ in range(frame_of(170)): em.run_frames(1); f += 1
    em.release()
    # DOWN down@fe+1025 hold down_hold_ms（修复：352ms）
    while f < fe_frame + frame_of(1025): em.run_frames(1); f += 1
    em.press_hold(Key.DOWN)
    for _ in range(frame_of(down_hold_ms)): em.run_frames(1); f += 1
    em.release()
    # final A down@fe+final_off_ms hold 189
    while f < fe_frame + frame_of(final_off_ms): em.run_frames(1); f += 1
    em.press_hold(Key.A)
    for _ in range(frame_of(189)): em.run_frames(1); f += 1
    em.release()
    # 观察 3s
    log = []
    last_snap = -1e9
    f_end = f + frame_of(3000)
    while f < f_end:
        em.run_frames(1); f += 1
        t_ms = int(f / FPS * 1000)
        if t_ms - last_snap >= 200:
            last_snap = t_ms
            mean = float(em.screenshot().mean())
            log.append((t_ms, mean))
            if mean < 40: break
    em.release()
    ok = any(r[1] < 40 for r in log)
    print('%s: DOWN hold=%dms finalA@fe+%d → %s' % (label, down_hold_ms, final_off_ms, 'CONFIRMED' if ok else 'no'))
    return ok


for i in range(3):
    run(352, 'fix-352ms-%d' % i)
