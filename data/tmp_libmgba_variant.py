"""无头命名界面变体实验：DOWN 次数 vs 转场 + 每步截图与录制快照对比。
变体 A: A + LEFT + DOWN×3 + A（多按 DOWN）
变体 B: A + LEFT + DOWN + A（录制节奏，复现基线）
判定：final A 后亮度<40 = 转场（命名完成）。
每步（A后/LEFT后/DOWN后/finalA后）截图，与录制 t0048547/9047/9547/50547 对比。
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
OUT = ROOT / 'data/demos/replay/libmgba_variant'
OUT.mkdir(parents=True, exist_ok=True)


def frame_of(t_ms):
    return int(round(t_ms / 1000.0 * FPS))


def tap_at(em, f, key, off_ms, hold_ms, fe_frame, snap_tag):
    """推进到 fe+off_ms，按下 key hold_ms 后松开。返回新帧号。"""
    while f < fe_frame + frame_of(off_ms):
        em.run_frames(1); f += 1
    em.press_hold(key)
    for _ in range(frame_of(hold_ms)):
        em.run_frames(1); f += 1
    em.release()
    # 松开后 300ms 稳定帧
    for _ in range(frame_of(300)):
        em.run_frames(1); f += 1
    Image.fromarray(em.screenshot()).save(OUT / ('%s.png' % snap_tag))
    return f


def run(downs, label):
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

    # fe 检测（每 3 帧亮度采样）
    fe_frame = None
    while f < frame_of(51000):
        em.run_frames(1)
        f += 1
        if f % 3 == 0 and em.screenshot().mean() > FE_THRESH:
            fe_frame = f
            break
    print('%s: fe=%d 帧' % (label, fe_frame))

    # 门控：A(fe+150,142) LEFT(fe+480,170) DOWN×(fe+1025,125) A(fe+1525,189)
    f = tap_at(em, f, Key.A, 150, 142, fe_frame, label + '_A')
    f = tap_at(em, f, Key.LEFT, 480, 170, fe_frame, label + '_LEFT')
    for i in range(downs):
        f = tap_at(em, f, Key.DOWN, 1025, 125, fe_frame, '%s_DOWN%d' % (label, i + 1))
    f = tap_at(em, f, Key.A, 1525, 189, fe_frame, label + '_FIN')
    em.release()

    # 观察 final A 后 3s
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
            if mean < 40:
                break
    Image.fromarray(em.screenshot()).save(OUT / ('%s_final.png' % label))
    print('%s 轨迹(finalA up 后): %s' % (label, ' '.join('%d:%.0f' % (r[0], r[1]) for r in log)))
    outcome = 'CONFIRMED' if any(r[1] < 40 for r in log) else 'NOT-TRANSITION'
    print('>>> %s = %s' % (label, outcome))
    return outcome


for label, downs in [('A-triple-down', 3), ('B-single-down', 1)]:
    run(downs, label)
