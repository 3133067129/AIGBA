"""libmgba 无头命名界面决定性实验：视觉锚点(fe) + 核心注入(=手柄语义)

假设：窗口实验失败是「通道」问题（键盘≠手柄语义），帧号硬对齐漂移 ~222ms
让 A 落在转场期。本实验用核心注入（set_keys → keysActive → KEYINPUT，与手柄
同一 m_input 汇合点）+ fe 视觉锚点（亮度>135）重对齐门控时序。

录制节奏（fe_rec≈48.15s，demo 时刻）：A@fe+130, LEFT@fe+460, DOWN@fe+1005, A@fe+1505
hold：A 142ms, LEFT 170ms, DOWN 125ms, A 189ms

门控计划：A@fe+150(hold 142), LEFT@fe+480(170), DOWN@fe+1025(125), A@fe+1525(189)

判定（final A 后 3s 窗口）：
  CONFIRMED = 亮度<40（转场=命名完成）
  DELETED   = 字段字母暗px 消失且亮度>100
  STUCK     = 其他
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

# 命名 4 键：门控偏移（相对 fe）与 hold
GATE = [(Key.A, 150, 142), (Key.LEFT, 480, 170), (Key.DOWN, 1025, 125), (Key.A, 1525, 189)]


def frame_of(t_ms):
    return int(round(t_ms / 1000.0 * FPS))


def main():
    evs = [json.loads(l) for l in open(DEMO, encoding='utf-8') if l.strip()]
    keys = [e for e in evs if e['ev'] == 'key']
    t_base = keys[0]['t']
    # 全部按键 → 事件帧（fe 前全部注入；fe 后的命名键由门控接管）
    events = []
    for k in keys:
        if k['t'] - t_base > 47800:   # fe 前安全区（录制 fe≈48.15s）
            break
        try:
            key = Key(k['name'])
        except ValueError:
            continue
        events.append((frame_of(k['t'] - t_base), key, k['down']))
    print('注入按键事件 %d 个（至 47.8s）' % len(events))

    em = Emulator(rom)
    em.core.reset()

    # 阶段 1：注入全部 fe 前按键，逐帧驱动到 47.8s，期间不检测 fe
    ei = 0
    f = 0
    f_pre = frame_of(47800)
    while f < f_pre:
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

    # 阶段 2：fe 检测（每 50ms 亮度），47.8s → 51s
    fe_frame = None
    fe_t = None
    f_end = frame_of(51000)
    last_snap = -1e9
    log = []          # (t_ms, 亮度, 字段暗px)
    field_base = None
    phase = 'fe_poll'
    gi = 0            # 门控索引
    g_sent = [False] * 4
    g_up = [False] * 4
    g_down_f = [0] * 4
    g_up_f = [0] * 4
    OUT = ROOT / 'data/demos/replay/libmgba_gate'
    OUT.mkdir(parents=True, exist_ok=True)
    saved_frames = {}  # tag -> (f, img)
    while f < f_end:
        # 门控注入（按帧号，fe 锚定）
        if phase == 'gate' and fe_frame is not None:
            for j, (name, off_ms, hold_ms) in enumerate(GATE):
                if not g_sent[j] and f >= fe_frame + frame_of(off_ms):
                    em.press_hold(name)
                    g_sent[j] = True
                    g_down_f[j] = f
                elif g_sent[j] and not g_up[j] and f >= g_down_f[j] + frame_of(hold_ms):
                    em.release()
                    g_up[j] = True
                    g_up_f[j] = f
        em.run_frames(1)
        f += 1
        t_ms = int(f / FPS * 1000)
        if t_ms - last_snap >= 50 and 47800 <= t_ms <= 51000:
            last_snap = t_ms
            img = em.screenshot().astype(int)
            mean = float(img.mean())
            field = img[58:80, 92:104]
            dark = int((field.mean(axis=2) < 120).sum())
            if field_base is None:
                field_base = dark
            log.append((t_ms, mean, dark))
            if phase == 'fe_poll' and mean > FE_THRESH:
                fe_t = t_ms
                fe_frame = f
                phase = 'gate'
                print('  fe=%.3fs (帧 %d)' % (fe_t / 1000, fe_frame), flush=True)
            # 存关键帧：fe/A后/LEFT后/DOWN后/finalA后 各 +400ms
            for tag, (a, b) in [('fe', (fe_frame if fe_frame else -1, None)),
                                ('A', (g_down_f[0], g_up_f[0])),
                                ('LEFT', (g_down_f[1], g_up_f[1])),
                                ('DOWN', (g_down_f[2], g_up_f[2])),
                                ('FIN', (g_up_f[3], None))]:
                if a and a > 0 and (b is None or b > 0) and tag not in saved_frames:
                    mark = f - a if b is None else f - b
                    if mark == frame_of(400):
                        saved_frames[tag] = (f, em.screenshot())
                        print('  存帧 %s @ t=%dms' % (tag, t_ms), flush=True)
    em.release()

    # 存帧到磁盘
    for tag, (f, img) in saved_frames.items():
        Image.fromarray(img).save(OUT / ('%s_f%d.png' % (tag, f)))

    # 输出轨迹
    print('轨迹 (t_ms, 亮度, 字段暗px):')
    for r in log:
        print('  %6d %6.1f %4d' % r)
    if fe_t is None:
        print('>>> 未检测到 fe（亮度从未 >135）—— 帧对齐严重错位')
        return

    # 判定：final A up 后窗口
    fA_up = g_up_f[3]
    tA_up = int(fA_up / FPS * 1000)
    inw = [r for r in log if tA_up + 200 <= r[0] <= tA_up + 3000]
    if any(r[1] < 40 for r in inw):
        print('>>> CONFIRMED：命名完成（转场黑）—— 核心注入+视觉锚定 = 手柄语义 ✓')
    else:
        px = min([r[2] for r in inw] or [999])
        print('>>> 未转场：窗口内最小字段暗px=%d（基线=%d）→ %s'
              % (px, field_base, 'DELETED' if px < 40 else 'STUCK'))


if __name__ == '__main__':
    main()
