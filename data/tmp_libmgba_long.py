"""无头命名界面：确认 DOWN 有效间隔 + 长按假设。
变体 C: A+LEFT + DOWN×3(间隔167ms) + final A@fe+1525 —— 成功节奏复现，逐帧确认光标
变体 D: A+LEFT + DOWN 长按 500ms + final A —— 若光标到确定按钮 = 「长按=多次滚动」假设成立
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


def prep(label):
    """注入到 fe 检测。返回 (em, f, fe_frame)。"""
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
    print('%s: fe=%d 帧' % (label, fe_frame))
    return em, f, fe_frame


def red_boxes(img):
    """红色高亮聚类：返回 (y范围, x范围) 列表。"""
    r = img[:, :, 0].astype(int); g = img[:, :, 1].astype(int); b = img[:, :, 2].astype(int)
    red = (r > 150) & (g < 100) & (b < 100)
    boxes = []
    if red.sum() == 0:
        return boxes
    ys, xs = np.where(red)
    # 按 y 聚类（间隔>8px 分块）
    y_sorted = np.sort(np.unique(ys))
    groups = []
    cur = [y_sorted[0]]
    for y in y_sorted[1:]:
        if y - cur[-1] <= 8:
            cur.append(y)
        else:
            groups.append(cur); cur = [y]
    groups.append(cur)
    for g_ys in groups:
        m = np.isin(ys, g_ys)
        boxes.append((g_ys[0], g_ys[-1], int(xs[m].min()), int(xs[m].max()), int(xs[m].size)))
    return boxes


def snap(em, tag):
    img = em.screenshot()
    Image.fromarray(img).save(OUT / ('%s.png' % tag))
    print('  [%s] 红框: %s' % (tag, red_boxes(img)))


def runC(label='C-3x167ms'):
    em, f, fe = prep(label)
    # A down@fe+150 hold 142
    while f < fe + frame_of(150): em.run_frames(1); f += 1
    em.press_hold(Key.A)
    for _ in range(frame_of(142)): em.run_frames(1); f += 1
    em.release()
    # LEFT down@fe+480 hold 170
    while f < fe + frame_of(480): em.run_frames(1); f += 1
    em.press_hold(Key.LEFT)
    for _ in range(frame_of(170)): em.run_frames(1); f += 1
    em.release()
    snap(em, label + '_afterLEFT')
    # DOWN ×3：down@fe+1025, 间隔 167ms(10帧)
    for i in range(3):
        while f < fe + frame_of(1025): em.run_frames(1); f += 1
        em.press_hold(Key.DOWN)
        for _ in range(frame_of(125)): em.run_frames(1); f += 1
        em.release()
        snap(em, '%s_DOWN%d' % (label, i + 1))
        for _ in range(10): em.run_frames(1); f += 1
    # final A down@fe+1525
    while f < fe + frame_of(1525): em.run_frames(1); f += 1
    em.press_hold(Key.A)
    for _ in range(frame_of(189)): em.run_frames(1); f += 1
    em.release()
    snap(em, label + '_FIN')
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
    print('%s 轨迹: %s' % (label, ' '.join('%d:%.0f' % (r[0], r[1]) for r in log)))
    print('>>> %s = %s' % (label, 'CONFIRMED' if any(r[1] < 40 for r in log) else 'NOT-TRANSITION'))
    em.release()


def runD(label='D-longdown'):
    em, f, fe = prep(label)
    while f < fe + frame_of(150): em.run_frames(1); f += 1
    em.press_hold(Key.A)
    for _ in range(frame_of(142)): em.run_frames(1); f += 1
    em.release()
    while f < fe + frame_of(480): em.run_frames(1); f += 1
    em.press_hold(Key.LEFT)
    for _ in range(frame_of(170)): em.run_frames(1); f += 1
    em.release()
    snap(em, label + '_afterLEFT')
    # DOWN 长按 500ms
    while f < fe + frame_of(1025): em.run_frames(1); f += 1
    em.press_hold(Key.DOWN)
    for _ in range(frame_of(500)): em.run_frames(1); f += 1
    em.release()
    snap(em, label + '_afterDOWNlong')
    # final A
    while f < fe + frame_of(1525): em.run_frames(1); f += 1
    em.press_hold(Key.A)
    for _ in range(frame_of(189)): em.run_frames(1); f += 1
    em.release()
    snap(em, label + '_FIN')
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
    print('%s 轨迹: %s' % (label, ' '.join('%d:%.0f' % (r[0], r[1]) for r in log)))
    print('>>> %s = %s' % (label, 'CONFIRMED' if any(r[1] < 40 for r in log) else 'NOT-TRANSITION'))
    em.release()


runC()
runD()
