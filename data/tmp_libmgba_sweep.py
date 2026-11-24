"""无头命名界面 DOWN 按住时长扫参：7/14/21/28/42/60 帧，追踪滚动距离 + final A 转场。
流程：注入到 fe → A(150,142) → LEFT(480,170) → DOWN 按住 N 帧 → 截图 → final A@fe+1525 → 判定。
每档输出：DOWN 后红框位置（原生坐标）+ 显示格内容指纹 + 转场判定。
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
OUT = ROOT / 'data/demos/replay/libmgba_sweep'
OUT.mkdir(parents=True, exist_ok=True)


def frame_of(t_ms):
    return int(round(t_ms / 1000.0 * FPS))


def red_boxes(img):
    r = img[:, :, 0].astype(int); g = img[:, :, 1].astype(int); b = img[:, :, 2].astype(int)
    red = (r > 150) & (g < 100) & (b < 100)
    if red.sum() == 0:
        return []
    ys, xs = np.where(red)
    y_sorted = np.sort(np.unique(ys))
    groups, cur = [], [y_sorted[0]]
    for y in y_sorted[1:]:
        if y - cur[-1] <= 8: cur.append(y)
        else: groups.append(cur); cur = [y]
    groups.append(cur)
    out = []
    for gys in groups:
        m = np.isin(ys, gys)
        out.append((int(gys[0]), int(gys[-1]), int(xs[m].min()), int(xs[m].max()), int(xs[m].size)))
    return out


def content_fingerprint(img):
    """显示格 x44-70 y30-60 内容指纹（非红像素分布）。"""
    zone = img[30:62, 44:72]
    g = zone[:, :, 1].astype(int) + zone[:, :, 0].astype(int) + zone[:, :, 2].astype(int)
    return int((g < 300).sum())


def run(hold_frames, label):
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

    # A
    while f < fe_frame + frame_of(150): em.run_frames(1); f += 1
    em.press_hold(Key.A)
    for _ in range(frame_of(142)): em.run_frames(1); f += 1
    em.release()
    # LEFT
    while f < fe_frame + frame_of(480): em.run_frames(1); f += 1
    em.press_hold(Key.LEFT)
    for _ in range(frame_of(170)): em.run_frames(1); f += 1
    em.release()
    img_left = em.screenshot()
    # DOWN 按住 hold_frames
    while f < fe_frame + frame_of(1025): em.run_frames(1); f += 1
    em.press_hold(Key.DOWN)
    for _ in range(hold_frames): em.run_frames(1); f += 1
    em.release()
    img_down = em.screenshot()
    Image.fromarray(img_down).save(OUT / ('%s_down.png' % label))
    # final A
    while f < fe_frame + frame_of(1525): em.run_frames(1); f += 1
    em.press_hold(Key.A)
    for _ in range(frame_of(189)): em.run_frames(1); f += 1
    em.release()
    # 观察 2s
    log = []
    last_snap = -1e9
    f_end = f + frame_of(2000)
    while f < f_end:
        em.run_frames(1); f += 1
        t_ms = int(f / FPS * 1000)
        if t_ms - last_snap >= 200:
            last_snap = t_ms
            mean = float(em.screenshot().mean())
            log.append((t_ms, mean))
            if mean < 40: break
    em.release()
    # LEFT 后 vs DOWN 后 显示格指纹差
    fp = abs(content_fingerprint(img_left) - content_fingerprint(img_down))
    print('%s: hold=%df(%.0fms) 红框LEFT=%s → DOWN后=%s 指纹差=%d 转场=%s'
          % (label, hold_frames, hold_frames / FPS * 1000, red_boxes(img_left), red_boxes(img_down),
             fp, 'YES' if any(r[1] < 40 for r in log) else 'no'))


for n in [7, 14, 21, 28, 42, 60]:
    run(n, 'hold%d' % n)
