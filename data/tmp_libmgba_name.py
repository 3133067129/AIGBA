"""libmgba 无头重放命名窗口 —— 验证「核心输入层注入 = 手柄语义」假设。

键盘 PostMessage/keybd_event 都无法复刻录制（手柄）的命名导航；
libmgba set_keys() 直接注入核心输入层（与手柄同一 m_input 汇合点），
如果假设成立，A/LEFT/DOWN/A 应复刻录制：final A → 转场（命名完成）。

对齐：录制 t_ms 是墙钟（mGBA 60Hz 或 59.73Hz）；无头帧率 59.7275Hz。
  帧号 f = t_ms / 1000 * 59.7275（±0.5 帧精度，远优于 ±200ms 的窗口漂移）。
观察：48-52s 每 50ms 抓帧（亮度 + 字段暗像素），判定 CONFIRMED/DELETED。
"""
import sys, json
sys.path.insert(0, '.')
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import numpy as np
import yaml
from pathlib import Path
from src.emulator.mgba_core import Emulator
from src.emulator.keys import Key

ROOT = Path('.').resolve()
cfg = yaml.safe_load(open('config/settings.yaml', encoding='utf-8'))
rom = str((ROOT / cfg['rom']['path']).resolve())
DEMO = ROOT / 'data/demos/demo_20260807_234704.jsonl'
FPS = 59.7275

def frame_of(t_ms):
    return int(round(t_ms / 1000.0 * FPS))

def main():
    evs = [json.loads(l) for l in open(DEMO, encoding='utf-8') if l.strip()]
    keys = [e for e in evs if e['ev'] == 'key']
    t_base = keys[0]['t']
    # 全段按键 → 事件帧（只跑到 52.5s）
    events = []
    for k in keys:
        if k['t'] - t_base > 52500:
            break
        try:
            key = Key(k['name'])
        except ValueError:
            continue
        events.append((frame_of(k['t'] - t_base), key, k['down']))
    print('按键事件 %d 个（至 52.5s），帧率 %.4f' % (len(events), FPS))

    em = Emulator(rom)
    em.core.reset()

    # 命名窗口 4 键时刻（帧）
    n0 = [e for e in events if e[2] and e[0] >= frame_of(48000) and e[0] <= frame_of(50000)]
    print('命名窗口按键帧:', [(e[0], e[1].name, e[2]) for e in n0])

    # 逐帧驱动 + 事件注入
    ei = 0
    f = 0
    f_end = frame_of(52500)
    last_snap = -1e9
    log = []          # (t_ms, 亮度, 字段暗px)
    field_dark0 = None
    ok_keys = set(Key)  # 全部 Key 可注入
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
        if t_ms - last_snap >= 50 and 47500 <= t_ms <= 52500:
            last_snap = t_ms
            img = em.screenshot().astype(int)
            mean = float(img.mean())
            # 字段区域 x92-104 y58-80 暗像素（与无头坐标一致：240x160 无窗口边框）
            field = img[58:80, 92:104]
            dark = int((field.mean(axis=2) < 120).sum())
            if field_dark0 is None:
                field_dark0 = dark
            log.append((t_ms, mean, dark))
    em.release()

    # 判定
    print('轨迹 (t_ms, 亮度, 字段暗px):')
    for r in log:
        print('  %6d %6.1f %4d' % r)
    inw = [r for r in log if 49655 + 300 <= r[0] <= 49655 + 3000]
    if any(r[1] < 40 for r in inw):
        print('>>> CONFIRMED：命名完成（转场黑）—— libmgba 注入 = 手柄语义 ✓')
    else:
        base = field_dark0
        print('>>> 未转场：字段暗px 基线=%d' % base)

if __name__ == '__main__':
    main()
