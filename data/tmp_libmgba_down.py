"""无头命名界面 DOWN 最小测试：短按 vs 长按 vs 多击，看键盘高亮是否移动。
流程：无头跑注入全按键到 fe 检测 → 只注入 DOWN（不同模式）→ 截图对比键盘区。
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
OUT = ROOT / 'data/demos/replay/libmgba_down'
OUT.mkdir(parents=True, exist_ok=True)


def frame_of(t_ms):
    return int(round(t_ms / 1000.0 * FPS))


def run(hold_frames, repeat, label):
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

    # fe 检测
    fe_frame = None
    while f < frame_of(51000):
        if fe_frame is None:
            em.run_frames(1)
            f += 1
            if f % 3 == 0 and em.screenshot().mean() > FE_THRESH:
                fe_frame = f
        else:
            # 高亮位置稳定后注入 DOWN
            break
    print('%s: fe=%d 帧' % (label, fe_frame))
    # 等 30 帧稳定
    for _ in range(30):
        em.run_frames(1); f += 1
    img_before = em.screenshot()
    Image.fromarray(img_before).save(OUT / ('%s_before.png' % label))
    # 注入 DOWN
    for r in range(repeat):
        em.press_hold(Key.DOWN)
        for _ in range(hold_frames):
            em.run_frames(1); f += 1
        em.release()
        for _ in range(6):
            em.run_frames(1); f += 1
    for _ in range(24):
        em.run_frames(1); f += 1
    img_after = em.screenshot()
    Image.fromarray(img_after).save(OUT / ('%s_after.png' % label))
    em.release()

    # 键盘区 diff
    d = (np.abs(img_before - img_after).mean(axis=2) > 60)
    ys, xs = np.where(d)
    print('  %s: 变化 %d px' % (label, d.sum()))
    if len(ys):
        print('  y%d-%d x%d-%d' % (ys.min(), ys.max(), xs.min(), xs.max()))
    return d.sum()


for hold, rep, label in [(8, 1, 'short'), (30, 1, 'long'), (8, 3, 'triple')]:
    run(hold, rep, label)
