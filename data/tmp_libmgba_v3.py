"""无头验证 v3 缩短语义：注入录制事件流（stretch_dir_taps 缩短后）→ 观察命名界面转场。
headless press_hold = 键盘语义（~150ms/格）；v3 缩短 100ms = 0 格 = 录制轴行为。
对比：baseline（不缩短，1:1 键盘）vs v3（缩短）——看 finalA 后是否转场。
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
OUT = ROOT / 'data/demos/replay/libmgba_v3'
OUT.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(ROOT / 'tools'))
from replay_demo_window import stretch_dir_taps


def frame_of(t_ms):
    return int(round(t_ms / 1000.0 * FPS))


def run(shorten: bool, label, to_ms=51500):
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
    if shorten:
        events, n = stretch_dir_taps(events)
        print('%s: 缩短 %d 个 up' % (label, n))
    ev_frames = [(frame_of(e['t']), Key(e['name']), e['down']) for e in events]

    em = Emulator(rom)
    em.core.reset()
    ei = 0
    f = 0
    f_end = frame_of(to_ms)
    log = []
    last_snap = -1e9
    snaps = []
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
            snaps.append((t_ms, em.screenshot()))
    em.release()
    seg = [(t, m) for t, m in log if 47000 <= t <= 51500]
    print('%s 轨迹(47-51.5s): %s' % (label, ' '.join('%d:%.0f' % (t, m) for t, m in seg)))
    # 找 finalA 后的转场黑屏（finalA up@49844 之后 200ms 内出现 <40）
    dark_after = [(t, m) for t, m in seg if t >= 50000 and m < 40]
    if dark_after:
        print('>>> %s = CONFIRMED 转场黑 @%dms' % (label, dark_after[0][0]))
    else:
        print('>>> %s = 卡在命名界面（50s 后无黑屏）' % label)
    # 保存键盘屏初始 + finalA 后帧
    for t, img in snaps:
        if t in (48500, 49600, 50300, 51000):
            Image.fromarray(img).save(OUT / ('%s_t%d.png' % (label, t)))


run(False, 'baseline-1to1')
run(True, 'v3-shorten')
