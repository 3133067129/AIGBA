"""headless 实验：跳过 A@48280（录制中该键按在黑屏转场期；回放中落在键盘屏/过渡期）。
场景：
  1. skip-A48280: 注入到 48.0s（黑屏）→ 跳过 A@48280 → LEFT/DOWN(100ms 缩短) → finalA@49655 → 转场？
  2. baseline: 完整事件流（对照，已知卡）
  3. skip-all-A: 跳过 A@48280 和 finalA 后的 A@50875
观察：finalA 后黑屏转场 + 名字槽内容变化。
"""
import sys, json
sys.path.insert(0, '.')
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import numpy as np, yaml
from pathlib import Path
from PIL import Image
from src.emulator.mgba_core import Emulator
from src.emulator.keys import Key

ROOT = Path('.').resolve()
cfg = yaml.safe_load(open('config/settings.yaml', encoding='utf-8'))
rom = str((ROOT / cfg['rom']['path']).resolve())
DEMO = ROOT / 'data/demos/demo_20260807_234704.jsonl'
FPS = 59.7275
OUT = ROOT / 'data/demos/replay/libmgba_skip'
OUT.mkdir(parents=True, exist_ok=True)

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

def run(label, skip_48280=False, shorten=True, to_ms=51500):
    evs = [json.loads(l) for l in open(DEMO, encoding='utf-8') if l.strip()]
    keys = [e for e in evs if e['ev'] == 'key']
    t_base = keys[0]['t']
    events = []
    for k in keys:
        t = k['t'] - t_base
        if t > to_ms: break
        if skip_48280 and 48100 <= t <= 48500: continue  # 跳过 A@48280
        try: key = Key(k['name'])
        except ValueError: continue
        events.append({'t': t, 'name': k['name'], 'down': k['down']})
    if shorten:
        events, n = stretch_dir_taps(events)
        print('%s: 缩短 %d 个 up' % (label, n))
    ev_frames = [(frame_of(e['t']), Key(e['name']), e['down']) for e in events]
    em = Emulator(rom); em.core.reset()
    ei = 0; f = 0
    f_end = frame_of(to_ms)
    log = []; last_snap = -1e9
    while f < f_end:
        while ei < len(ev_frames) and ev_frames[ei][0] <= f:
            _, name, down = ev_frames[ei]
            if down: em.press_hold(name)
            else: em.release()
            ei += 1
        em.run_frames(1); f += 1
        t_ms = int(f / FPS * 1000)
        if t_ms - last_snap >= 100:
            last_snap = t_ms
            mean = float(em.screenshot().mean())
            log.append((t_ms, mean))
            if t_ms in (48500, 49600, 50300, 51000):
                Image.fromarray(em.screenshot()).save(OUT / ('%s_t%d.png' % (label, t_ms)))
    em.release()
    seg = [(t, m) for t, m in log if 47000 <= t <= 51500]
    print('%s 轨迹(47-51.5s): %s' % (label, ' '.join('%d:%.0f' % (t, m) for t, m in seg)))
    dark_after = [(t, m) for t, m in seg if t >= 50000 and m < 40]
    print('>>> %s = %s' % (label, 'CONFIRMED 转场黑 @%dms' % dark_after[0][0] if dark_after else '卡在命名界面'))

run('skip-A48280', skip_48280=True)
run('baseline-full')
