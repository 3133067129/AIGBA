"""无头推进诊断：注入全按键，每 100ms 记录亮度 + 关键帧保存。
目标：确认无头 47-50s 各阶段画面，定位「无头对话推进慢」原因。
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
OUT = ROOT / 'data/demos/replay/libmgba_probe'
OUT.mkdir(parents=True, exist_ok=True)


def frame_of(t_ms):
    return int(round(t_ms / 1000.0 * FPS))


def main():
    evs = [json.loads(l) for l in open(DEMO, encoding='utf-8') if l.strip()]
    keys = [e for e in evs if e['ev'] == 'key']
    t_base = keys[0]['t']
    events = []
    for k in keys:
        if k['t'] - t_base > 50000:
            break
        try:
            key = Key(k['name'])
        except ValueError:
            continue
        events.append((frame_of(k['t'] - t_base), key, k['down']))
    print('事件 %d 个' % len(events))

    em = Emulator(rom)
    em.core.reset()

    ei = 0
    f = 0
    f_end = frame_of(50000)
    last_snap = -1e9
    log = []
    while f < f_end:
        while ei < len(events) and events[ei][0] <= f:
            _, name, down = events[ei]
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
            img = em.screenshot()
            mean = float(img.mean())
            log.append((t_ms, mean))
            # 存关键帧（每 100ms 全存）
            if 47000 <= t_ms <= 48400:
                Image.fromarray(img).save(OUT / ('t%07d_m%.0f.png' % (t_ms, mean)))
    em.release()

    # 亮度曲线
    print('亮度轨迹 (t_ms, mean):')
    for t, m in log:
        print('  %6d %6.1f' % (t, m))


if __name__ == '__main__':
    main()
