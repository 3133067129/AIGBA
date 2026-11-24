"""手柄人工示范录制器（mGBA 真实窗口旁路录制）。

用户在 mGBA.exe 窗口里用手柄正常玩；本工具在一旁（不抢焦点、不发输入）：
- ~125Hz 轮询手柄（pygame.joystick）→ key 事件
- 每 ~500ms PrintWindow 抓 mGBA 窗口 → 240x160 PNG 快照
- 监控 ROM 目录 *.ss* mtime → save 事件（快速存档）
- 画面大跳变 → jump 事件（疑似快速读档）

用法：
    python tools/gamepad_demo_recorder.py              # 自动启动 mGBA + 录制
    python tools/gamepad_demo_recorder.py --attach     # 挂到已开的 mGBA 窗口
    python tools/gamepad_demo_recorder.py --test       # 手柄逐键核对（映射验证）
    python tools/gamepad_demo_recorder.py --xinput     # XInput 原始状态对照

事件格式（JSONL，t=毫秒相对时间）：
    {"ev":"boot","mode":"window-gamepad","rom":..., "mapping":...}
    {"t":ms,"ev":"key","name":"A","down":true}   # name=GBA 键名或原始标签(BTN5/AX4+)
    {"t":ms,"ev":"snap","img":"<stem>_t0005000.png"}
    {"t":ms,"ev":"save","file":"xxx.ss1"}        # 存档文件变化
    {"t":ms,"ev":"save","btn":"BTN6"}            # 存档按钮（config/gamepad.yaml）
    {"t":ms,"ev":"jump"}                         # 画面大跳变（场景切换提示；读档以按钮事件为准）

知识提取：python tools/demo_knowledge_window.py <demo.jsonl> [--llm]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pygame
import yaml
from PIL import Image

from src.emulator import window_backend
from src.emulator.gamepad import DIR_NAMES, Gamepad, NoGamepadError, make_gamepad
from src.perception.screen import diff_ratio

cfg = yaml.safe_load(open(ROOT / "config" / "settings.yaml", encoding="utf-8"))
GP = yaml.safe_load(open(ROOT / "config" / "gamepad.yaml", encoding="utf-8"))["gamepad"]
ROM_PATH = str((ROOT / cfg["rom"]["path"]).resolve())
ROM_NAME = Path(ROM_PATH).name
ROM_DIR = Path(ROM_PATH).parent
MGBA_EXE = ROOT / "mGBA.exe"

DEMO_DIR = ROOT / "data" / "demos"
IMG_DIR = DEMO_DIR / "img"
DEMO_DIR.mkdir(parents=True, exist_ok=True)
IMG_DIR.mkdir(exist_ok=True)

SNAP_INTERVAL_S = 0.5   # 快照间隔
POLL_INTERVAL_S = 0.008  # 手柄轮询间隔（~125Hz）
JUMP_DIFF = 0.55         # 相邻快照 diff 超过 = 画面跳变（场景切换提示）
# 2026-08-08 实测：走路镜头滚动/对话字幕翻页都会 diff>0.55，
# 方向键任意事件(按下/松开)都重置安静窗口 → 走路连击不再误报；
# 真实读档有 AX5+ 按钮事件，jump 只是辅助提示。
JUMP_QUIET_MS = 1000


def _activate(hwnd):
    import win32con
    import win32gui
    try:
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        pass


def run_test(use_xinput: bool = False) -> int:
    """逐键核对：每个事件单独一行（SDL 原始事件 + 映射动作 + 心跳实时状态）。"""
    try:
        g = make_gamepad(deadzone=GP["deadzone"], threshold=GP["threshold"],
                         prefer_xinput=use_xinput)
    except Exception as e:
        print(f"✗ 无法初始化手柄: {e}")
        return 1
    print(f"🎮 手柄: {g.name}")
    if not use_xinput:
        print(f"   mGBA 映射: {g.mapping_summary()}")
    print("测试中（Ctrl+C 退出）。逐键按，每个事件单独一行：")
    print("  · SDL 行  = pygame 收到的原始输入事件（直接证据）")
    print("  · 🎮 行   = 识别出的动作（A/B/方向/原始标签 BTN<i>/AX<i>±）")
    print("  · 心跳行  = 每 5s 的实时原始状态")
    print("  → 存档/读档键：记下 🎮 行的原始标签，填入 config/gamepad.yaml")
    t0 = time.monotonic()
    last_beat = 0.0
    try:
        while True:
            if not use_xinput:
                # 原始 SDL 事件流：直接证明 pygame 是否收到物理输入
                for ev in pygame.event.get():
                    if ev.type == pygame.JOYBUTTONDOWN:
                        print(f"  SDL: 按钮{ev.button} ↓", flush=True)
                    elif ev.type == pygame.JOYBUTTONUP:
                        print(f"  SDL: 按钮{ev.button} ↑", flush=True)
                    elif ev.type == pygame.JOYHATMOTION:
                        print(f"  SDL: hat{ev.hat} → {ev.value}", flush=True)
                    elif ev.type == pygame.JOYAXISMOTION and abs(ev.value) > 0.1:
                        print(f"  SDL: 轴{ev.axis} = {ev.value:+.2f}", flush=True)
            for label, down in g.poll():
                print(f"  🎮 {label}{'↓' if down else '↑'}", flush=True)
            now = time.monotonic()
            if now - last_beat > 5.0:
                last_beat = now
                if isinstance(g, Gamepad):
                    btns = [i for i in range(g.j.get_numbuttons())
                            if g.j.get_button(i)]
                    hat = g.j.get_hat(0) if g.j.get_numhats() > 0 else "-"
                    axes = [round(g.j.get_axis(i), 2)
                            for i in range(g.j.get_numaxes())]
                    print(f"  [心跳 {now - t0:.0f}s] 按住={btns} hat={hat} "
                          f"axes={axes}", flush=True)
            time.sleep(0.03)
    except KeyboardInterrupt:
        print("\n✓ 测试结束")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="手柄人工示范录制器")
    ap.add_argument("--test", action="store_true", help="手柄逐键核对模式")
    ap.add_argument("--xinput", action="store_true", help="--test 时用 XInput 直读对照")
    ap.add_argument("--attach", action="store_true",
                    help="挂到已打开的 mGBA 窗口（不自动启动）")
    args = ap.parse_args()

    if args.test:
        return run_test(use_xinput=args.xinput)

    # ---- 手柄 ----
    try:
        g = make_gamepad(deadzone=GP["deadzone"], threshold=GP["threshold"])
    except NoGamepadError as e:
        print(f"✗ {e}")
        print("提示：插上接收器、打开手柄电源后再试；或 --xinput 用 XInput 直读")
        return 1
    print(f"🎮 手柄: {g.name}")
    print(f"   mGBA 映射: {g.mapping_summary()}")

    # ---- 窗口 ----
    if args.attach:
        hwnd = window_backend.find_window(ROM_NAME)
        if not hwnd:
            print(f"✗ 未找到 mGBA 窗口（标题含 {ROM_NAME!r}）。先手动开 mGBA + ROM")
            return 1
        print("📎 挂到已开窗口")
    else:
        print(f"🚀 启动 mGBA: {MGBA_EXE}")
        import subprocess
        subprocess.Popen([str(MGBA_EXE.resolve()), ROM_PATH],
                         creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
        t0 = time.time()
        hwnd = None
        while time.time() - t0 < 20:
            hwnd = window_backend.find_window(ROM_NAME)
            if hwnd:
                break
            time.sleep(0.5)
        if not hwnd:
            print("✗ mGBA 窗口未出现")
            return 1
        time.sleep(1.0)  # 等首帧渲染

    # ---- 录制 ----
    demo_path = DEMO_DIR / time.strftime("demo_%Y%m%d_%H%M%S.jsonl")
    stem = demo_path.stem
    f = open(demo_path, "w", encoding="utf-8")
    boot = {"ev": "boot", "mode": "window-gamepad",
            "rom": ROM_PATH, "gamepad": g.name,
            "mapping": g.mapping_summary(),
            "save_btn": GP.get("savestate_save_btn"),
            "load_btn": GP.get("savestate_load_btn"),
            "created": time.strftime("%Y-%m-%d %H:%M:%S")}
    f.write(json.dumps(boot, ensure_ascii=False) + "\n")
    f.flush()

    save_btn = GP.get("savestate_save_btn")
    load_btn = GP.get("savestate_load_btn")
    seen_ss: dict[str, float] = {}
    last_snap_ms = 0
    last_scan = 0.0
    last_dir_change_ms = -10**9
    last_snap_img = None
    n_keys = n_snaps = n_saves = n_jumps = 0
    t_start = time.monotonic()

    def now_ms() -> int:
        return int((time.monotonic() - t_start) * 1000)

    def write(ev: dict) -> None:
        f.write(json.dumps(ev, ensure_ascii=False) + "\n")
        f.flush()

    def do_snap(force: bool = False) -> None:
        nonlocal last_snap_ms, last_snap_img, n_snaps
        ms = now_ms()
        if not force and ms - last_snap_ms < SNAP_INTERVAL_S * 1000:
            return
        last_snap_ms = ms
        _activate(hwnd)
        img = window_backend.capture_hwnd(hwnd)
        if img is None:
            return
        img_name = f"{stem}_t{ms:07d}.png"
        Image.fromarray(img).save(IMG_DIR / img_name)
        write({"t": ms, "ev": "snap", "img": img_name})
        n_snaps += 1
        # 画面跳变检测（疑似读档）：diff 大 + 最近无方向输入
        if last_snap_img is not None:
            d = diff_ratio(last_snap_img, img)
            if d > JUMP_DIFF and ms - last_dir_change_ms > JUMP_QUIET_MS:
                nonlocal n_jumps
                write({"t": ms, "ev": "jump", "diff": round(d, 2)})
                n_jumps += 1
        last_snap_img = img

    print(f"🎮 录制中（Ctrl+C 结束）→ {demo_path.name}")
    try:
        while True:
            for label, down in g.poll():
                ms = now_ms()
                if label in {save_btn, load_btn}:
                    ev = {"t": ms, "ev": "save" if label == save_btn else "load",
                          "btn": label}
                    write(ev)
                    n_saves += 1
                    do_snap(force=True)  # 存档后立刻抓一帧（里程碑画面）
                    continue
                if label in DIR_NAMES:  # 按下/松开都算：单步点按也会触发镜头滚动
                    last_dir_change_ms = ms
                write({"t": ms, "ev": "key", "name": label, "down": down})
                n_keys += 1
            do_snap()
            # 存档文件监控（mGBA savestatePath 空 → 存 ROM 目录）
            now = time.monotonic()
            if now - last_scan >= 0.5:
                last_scan = now
                for p in sorted(ROM_DIR.glob("*.ss*")):
                    try:
                        mtime = p.stat().st_mtime
                    except OSError:
                        continue
                    if p.name in seen_ss:
                        if mtime > seen_ss[p.name]:
                            seen_ss[p.name] = mtime
                            write({"t": now_ms(), "ev": "save", "file": p.name})
                            n_saves += 1
                            do_snap(force=True)
                    else:
                        seen_ss[p.name] = mtime  # 基准记录，不触发
            time.sleep(POLL_INTERVAL_S)
    except KeyboardInterrupt:
        pass
    finally:
        write({"t": now_ms(), "ev": "end", "msg": "user exit"})
        f.close()

    dur_s = time.monotonic() - t_start
    print(f"\n录制完成: {demo_path.name}  时长 {dur_s:.0f}s")
    print(f"  按键事件 {n_keys} | 快照 {n_snaps} | 存档/跳变 {n_saves}/{n_jumps}")
    print(f"知识提取: .venv\\Scripts\\python.exe tools/demo_knowledge_window.py {demo_path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
