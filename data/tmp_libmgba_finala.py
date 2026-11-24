"""headless 观察 finalA 按下瞬间：光标/名字槽/大字符区的逐帧响应。
注入录制事件流（v3 缩短）→ 48.0-52s 每帧输出红区 + 名字槽指纹 + 大字符指纹。
"""
import sys, json
sys.path.insert(0, '.')
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import numpy as np, yaml
from pathlib import Path
from src.emulator.mgba_core import Emulator
from src.emulator.keys import Key

ROOT = Path('.').resolve()
cfg = yaml.safe_load(open('config/settings.yaml', encoding='utf-8'))
rom = str((ROOT / cfg['rom']['path']).resolve())
DEMO = ROOT / 'data/demos/demo_20260807_234704.jsonl'
FPS = 59.7275

sys.path.insert(0, str(ROOT / 'tools'))
from replay_demo_window import stretch_dir_taps

def frame_of(t_ms): return int(round(t_ms / 1000.0 * FPS))

def red_boxes(img):
    r = img[:, :, 0].astype(int); g = img[:, :, 1].astype(int); b = img[:, :, 2].astype(int)
    red = (r > 150) & (g < 100) & (b < 100)
    if red.sum() == 0: return []
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

evs = [json.loads(l) for l in open(DEMO, encoding='utf-8') if l.strip()]
keys = [e for e in evs if e['ev'] == 'key']
t_base = keys[0]['t']
events = []
for k in keys:
    t = k['t'] - t_base
    if t > 51500: break
    try: key = Key(k['name'])
    except ValueError: continue
    events.append({'t': t, 'name': k['name'], 'down': k['down']})
events, n = stretch_dir_taps(events)
print('缩短 %d 个 up' % n)
ev_frames = [(frame_of(e['t']), Key(e['name']), e['down']) for e in events]

em = Emulator(rom); em.core.reset()
ei = 0; f = 0
# 快速推进到 48.5s
while f < frame_of(48500):
    while ei < len(ev_frames) and ev_frames[ei][0] <= f:
        _, name, down = ev_frames[ei]
        if down: em.press_hold(name)
        else: em.release()
        ei += 1
    em.run_frames(1); f += 1
# 48.5-51s 逐帧观察
while f < frame_of(51000):
    while ei < len(ev_frames) and ev_frames[ei][0] <= f:
        _, name, down = ev_frames[ei]
        mark = '▼%s' % name if down else '▲%s' % name
        print('帧%d 事件 %s' % (f, mark))
        if down: em.press_hold(name)
        else: em.release()
        ei += 1
    em.run_frames(1); f += 1
    if f % 2 == 0:
        img = em.screenshot()
        mean = float(img.mean())
        rb = red_boxes(img)
        ns = int((img[26:46, 28:90].sum(axis=2) < 300).sum())
        cf = int((img[50:110, 128:216].sum(axis=2) < 300).sum())
        print('帧%d %dms: mean=%.1f 红区=%s 名字槽=%d 大字符=%d' % (f, int(f/FPS*1000), mean, rb, ns, cf))
em.release()
