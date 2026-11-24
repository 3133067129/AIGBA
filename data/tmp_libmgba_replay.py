"""无头验证修复后的回放按键流（stretch 后）：
注入 demo 按键（到 51s，命名界面完成段）→ 确认转场 + 亮度轨迹 vs 录制。
对比：拉伸前（基线）vs 拉伸后（修复）。
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
OUT = ROOT / 'data/demos/replay/libmgba_replay'
OUT.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(ROOT / 'tools'))
from replay_demo_window import stretch_dir_taps, DIR_KEYS


def frame_of(t_ms):
    return int(round(t_ms / 1000.0 * FPS))


def run(stretch: bool, label, to_ms=51000):
    evs = [json.loads(l) for l in open(DEMO, encoding='utf-8') if l.strip()]
    keys = [e for e in evs if e['ev'] == 'key']
    t_base = keys[0]['t']
    events = []
    for k in keys:
        if k['t'] - t_base > to_ms:
            break
        try:
            key = Key(k['name'])
        except ValueError:
            continue
        events.append({'t': k['t'] - t_base, 'name': k['name'], 'down': k['down']})
    if stretch:
        events, n = stretch_dir_taps(events)
        print('%s: 拉伸 %d 个 up' % (label, n))
    # 事件按帧号
    ev_frames = [(frame_of(e['t']), Key(e['name']), e['down']) for e in events]

    em = Emulator(rom)
    em.core.reset()
    ei = 0
    f = 0
    f_end = frame_of(to_ms)
    log = []
    last_snap = -1e9
    while f < f_end:
        while ei < len(ev_frames) and ev_frames[ei][0] <= f:
            _, name, down = ev_frames[ei]
            if down:
                em.press_hold(name)
            else:
                em.release()
            ei += 1
        em.run_frames(1)
        f += 1
        t_ms = int(f / FPS * 1000)
        if t_ms - last_snap >= 100:
            last_snap = t_ms
            mean = float(em.screenshot().mean())
            log.append((t_ms, mean))
    em.release()
    # 命名界面段轨迹（46-51s）
    seg = [(t, m) for t, m in log if 46000 <= t <= 51000]
    print('%s 轨迹(46-51s): %s' % (label, ' '.join('%d:%.0f' % (t, m) for t, m in seg)))
    dark = [t for t, m in seg if m < 40]
    print('>>> %s = %s' % (label, 'CONFIRMED 转场 @%dms' % dark[0] if dark else 'NOT-TRANSITION'))


run(False, 'baseline-1:1')
run(True, 'fixed-stretch')
