"""命名界面 4 变体决定性实验（2x2：通道 × 时序）

变体：
  V1 control       PostMessage × 录制时刻      （预期失败=复现基线）
  V2 kbd-raw       keybd_event × 录制时刻      （通道假设：PostMessage 方向键导航错误）
  V3 gate-post     PostMessage × fe锚定时序     （时序假设：游戏状态漂移导致键落错状态）
  V4 gate-kbd      keybd_event × fe锚定时序     （两者组合=可能的最优修复）

fe = 本运行淡入完成时刻（亮度>135，100ms 轮询）——自适应锚点，抵消漂移。
用户节奏（录制游戏态）：A@fe+130±100, LEFT@+460, DOWN@+1005, A@+1505（fe_rec≈48.15）
门控计划：A@fe+150, LEFT@fe+480, DOWN@fe+1025, A@fe+1525（hold 用录制值）

判定（final A 后）：
  CONFIRMED = 亮度<40（转场黑=命名完成）
  DELETED   = 字段字母像素归零且无转场（final A 删了字母）
  STUCK     = 无变化
"""
import sys, json, time, subprocess, shutil, ctypes
sys.path.insert(0, '.')
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import numpy as np
import yaml
from pathlib import Path
from PIL import Image
from src.emulator import window_backend
from src.emulator.keys import Key
import win32con, win32gui

ROOT = Path('.').resolve()
cfg = yaml.safe_load(open('config/settings.yaml', encoding='utf-8'))
rom = str((ROOT / cfg['rom']['path']).resolve())
sav = Path(rom).with_suffix('.sav')
DEMO = ROOT / 'data/demos/demo_20260807_234704.jsonl'
OUT = ROOT / 'data/demos/replay/name_exp'

# 录制 4 键：名字, demo 时刻 down/up（t_base=297）
SEQ_REC = [('A', 48280, 48422), ('LEFT', 48610, 48780), ('DOWN', 49155, 49280), ('A', 49655, 49844)]
# 门控偏移（相对 fe）与 hold：A+150, +330, +545, +500
GATE_OFF = [0, 330, 875, 1375]
GATE_HOLD = [142, 170, 125, 189]

VARIANTS = ['control', 'kbd-raw', 'gate-post', 'gate-kbd']


def clean_sav():
    if sav.exists():
        sav.unlink()


def launch():
    proc = subprocess.Popen([str((ROOT / 'mGBA.exe').resolve()), rom],
                            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
    hwnd = None
    t0 = time.time()
    while time.time() - t0 < 20 and not hwnd:
        hwnd = window_backend.find_window('mGBA')
        time.sleep(0.3)
    if not hwnd:
        raise RuntimeError('mGBA 窗口未出现')
    time.sleep(1.0)
    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    win32gui.SetForegroundWindow(hwnd)
    time.sleep(0.3)
    return proc, hwnd


def send(hwnd, name, down, channel):
    vk = window_backend.VK[Key(name)]
    if channel == 'kbd':
        if down:
            ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
        else:
            ctypes.windll.user32.keybd_event(vk, 0, 2, 0)
    else:
        window_backend.send_vk(vk, up=not down, hwnd=hwnd)


def run_variant(variant):
    clean_sav()
    proc, hwnd = launch()
    OUT.mkdir(parents=True, exist_ok=True)
    evs = [json.loads(l) for l in open(DEMO, encoding='utf-8') if l.strip()]
    keys = [e for e in evs if e['ev'] == 'key']
    t_base = keys[0]['t']
    t_start = time.monotonic()
    i = 0
    fe = None
    tmpl = None
    phase = 'main'          # main → fe_poll → window
    plan = []
    sent = [False] * 4
    sent_up = [False] * 4
    log = []                # (demo_ms, 亮度, 字段px)
    sents = []              # (键, down/up, 实际demo_ms, 计划demo_ms)
    last_cap = -1e9
    last_poll = -1e9
    frames = []
    try:
        while True:
            game_ms = int((time.monotonic() - t_start) * 1000) + t_base
            d = game_ms - t_base
            if d > 54500:
                break

            if phase == 'main':
                while i < len(keys) and keys[i]['t'] <= game_ms:
                    k = keys[i]
                    send(hwnd, k['name'], k['down'], 'post')
                    i += 1
                if d >= 47900:
                    phase = 'fe_poll'
            elif phase == 'fe_poll':
                if d - last_poll >= 100:
                    last_poll = d
                    img = window_backend.capture_hwnd(hwnd)
                    if img is not None and float(img.mean()) > 135:
                        fe = game_ms
                        tmpl = img[58:80, 92:104].astype(int)
                        frames.append((img, 'fe'))
                        print('  fe=%.3fs' % ((fe - t_base) / 1000), flush=True)
                        if variant.startswith('gate'):
                            ch = 'kbd' if variant == 'gate-kbd' else 'post'
                            base = fe + 150
                            for j, (n, _, _) in enumerate(SEQ_REC):
                                dt = base + GATE_OFF[j]
                                plan.append((dt, dt + GATE_HOLD[j], n, ch))
                        phase = 'window'
            elif phase == 'window':
                if variant in ('control', 'kbd-raw'):
                    ch = 'kbd' if variant == 'kbd-raw' else 'post'
                    while i < len(keys) and keys[i]['t'] <= game_ms:
                        k = keys[i]
                        if k['t'] - t_base > 50000:
                            break
                        send(hwnd, k['name'], k['down'], ch)
                        sents.append((k['name'], k['down'], k['t'] - t_base, k['t'] - t_base))
                        i += 1
                else:
                    for j, (dt, ut, n, ch) in enumerate(plan):
                        if not sent[j] and game_ms >= dt:
                            send(hwnd, n, True, ch)
                            sent[j] = True
                            sents.append((n, True, game_ms - t_base, dt - t_base))
                        elif sent[j] and not sent_up[j] and game_ms >= ut:
                            send(hwnd, n, False, ch)
                            sent_up[j] = True
                            sents.append((n, False, game_ms - t_base, ut - t_base))

            # 轨迹：fe 前 300ms 起，每 300ms
            if fe is not None and d >= fe - t_base - 300 and d - last_cap >= 300:
                last_cap = d
                img = window_backend.capture_hwnd(hwnd)
                if img is not None:
                    px = int((np.abs(img[58:80, 92:104].astype(int) - tmpl).sum(axis=2) > 60).sum())
                    log.append((d, float(img.mean()), px))
                    if fe - t_base - 300 <= d <= fe - t_base + 2600:
                        frames.append((img, 't%07d' % d))
            time.sleep(0.005)
    finally:
        for key in list(window_backend.VK):
            window_backend.send_vk(window_backend.VK[key], up=True, hwnd=hwnd)
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            pass

    # 存帧
    for img, tag in frames:
        Image.fromarray(img).save(OUT / ('%s_%s.png' % (variant, tag)))

    # 判定
    outcome = 'NO-FE'
    if fe is not None:
        lastA = None
        for (n, down, act, _) in reversed(sents):
            if n == 'A' and down:
                lastA = act
                break
        if lastA is None:
            outcome = 'NO-LASTA'
        else:
            inw = [r for r in log if lastA + 300 <= r[0] <= lastA + 3000]
            if any(r[1] < 40 for r in inw):
                outcome = 'CONFIRMED'
            else:
                pxmin = min([r[2] for r in log if lastA <= r[0] <= lastA + 2000] or [999])
                if all(r[1] > 100 for r in log if lastA <= r[0] <= lastA + 2000) and pxmin < 40:
                    outcome = 'DELETED'
                else:
                    outcome = 'STUCK'

    print('  outcome = %s' % outcome, flush=True)
    print('  sends: ' + ' '.join('%s%s@%d' % (n, 'v' if down else '^', act) for (n, down, act, _) in sents), flush=True)
    if log:
        print('  轨迹(demo, 亮度, 字段px): ' + ' '.join('%d:%.0f/%d' % r for r in log), flush=True)
    return variant, outcome, fe, sents, log


def main():
    # 原 sav 备份
    orig_bak = None
    if sav.exists():
        orig_bak = sav.with_name(sav.name + '.bak-orig')
        shutil.copy2(sav, orig_bak)
    evs = [json.loads(l) for l in open(DEMO, encoding='utf-8') if l.strip()]
    t_base = next(e['t'] for e in evs if e['ev'] == 'key')
    results = []
    for variant in VARIANTS:
        print('=' * 64, flush=True)
        print('变体 %s' % variant, flush=True)
        try:
            results.append(run_variant(variant))
        except Exception as e:
            print('  异常: %r' % e, flush=True)
        time.sleep(2)
    print('=' * 64)
    print('变体      结局      fe(演示时刻)')
    for variant, outcome, fe, sents, log in results:
        print('%-10s %-11s fe=%.2f' % (variant, outcome, (fe - t_base) / 1000 if fe else -1))


if __name__ == '__main__':
    main()
