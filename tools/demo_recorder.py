"""人工演示录制器：预览窗人工操作 → data/demos/demo_*.jsonl（帧级精确轨迹）

用法：
    python tools/demo_recorder.py                    # 默认：未白镇 savestate 起手（试解锁）
    python tools/demo_recorder.py --state <name>     # 指定 savestate
    python tools/demo_recorder.py --cold             # 冷启动自动推进到可动点，再交还人工
    python tools/demo_recorder.py --manual           # 纯人工冷启动：从开机画面起全部自己操作
    python tools/demo_recorder.py --after-door       # 自动开场+导航+出门到未白镇，交还人工试解锁
    python tools/demo_recorder.py --speed 4          # 倍速

录制内容：
- keys 事件：按键状态集变化（帧号精确）→ replay_demo.py 确定性回放
- snap 事件：每 30 帧状态快照（坐标/bright）→ 回放时逐点对照
- note 事件：F1-F5 打标签（解锁/剧情/对话/发现/节点），附截图存档

演示操作提示（当前卡点：未白镇移动锁）：
  试各种按键组合：方向键+A/B/START/SELECT、长按/连按、先调钟再出门等。
  一旦发现可动（人物能走），立刻按 F1 打"解锁"标签——回放即复现。

标签：F1=解锁成功  F2=剧情推进  F3=关键对话  F4=发现  F5=节点
按键：方向键/A/B/回车/退格 = 人工接管；+/- 调速；p 暂停；ESC 结束录制
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

from src.emulator.mgba_core import Emulator
from src.emulator.preview import PreviewWindow
from src.emulator.keys import Key

cfg = yaml.safe_load(open(ROOT / "config" / "settings.yaml", encoding="utf-8"))
CK = ROOT / "data" / "checkpoints"
DEMO_DIR = ROOT / "data" / "demos"
IMG_DIR = DEMO_DIR / "img"
DEMO_DIR.mkdir(parents=True, exist_ok=True)
IMG_DIR.mkdir(exist_ok=True)

# pygame 键码 → 标签（F1-F5）
TAG_KEYS = {
    pygame.K_F1: "解锁成功",
    pygame.K_F2: "剧情推进",
    pygame.K_F3: "关键对话",
    pygame.K_F4: "发现",
    pygame.K_F5: "节点",
}
DIR_KEY = {"UP": Key.UP, "DOWN": Key.DOWN, "LEFT": Key.LEFT, "RIGHT": Key.RIGHT}


def main():
    ap = argparse.ArgumentParser(description="人工演示录制器")
    ap.add_argument("--state", default="outdoor_real.state", help="savestate 名")
    ap.add_argument("--cold", action="store_true", help="冷启动自动推进到可动点再交还人工")
    ap.add_argument("--manual", action="store_true",
                    help="纯人工冷启动：从游戏开机画面起全部自己操作（确定性最强）")
    ap.add_argument("--after-door", action="store_true",
                    help="自动开场+导航+出门到未白镇，交还人工试解锁（当前卡点专用）")
    ap.add_argument("--speed", type=float, default=2.0, help="初始倍速")
    args = ap.parse_args()

    modes = sum([args.cold, args.manual, args.after_door])
    if modes > 1:
        print("--cold / --manual / --after-door 互斥")
        sys.exit(1)

    demo_path = DEMO_DIR / time.strftime("demo_%Y%m%d_%H%M%S.jsonl")
    f = open(demo_path, "w", encoding="utf-8")
    mode = ("after_door" if args.after_door
            else "manual" if args.manual
            else "cold" if args.cold else "state")
    boot = {"ev": "boot", "mode": mode,
            "rom": str(cfg["rom"]["path"]),
            "state": args.state if mode == "state" else None,
            "created": time.strftime("%Y-%m-%d %H:%M:%S")}
    f.write(json.dumps(boot, ensure_ascii=False) + "\n")
    f.flush()

    emu = Emulator(rom_path=ROOT / cfg["rom"]["path"])

    def log_keys(down: tuple[Key, ...], frame: int):
        """帧前采样钩子：记录「即将执行的帧」实际读取的按键集。

        与 pygame 事件延迟无关（SDL 键事件到达队列有 1-8ms 不确定延迟，
        事件式记录会引入帧偏移导致开场分叉）；此处记录模拟器真实按键状态。
        """
        keys = sorted(k.name for k in down)
        f.write(json.dumps({"t": frame, "ev": "keys",
                            "down": keys}) + "\n")
        f.flush()

    emu.set_key_hook(log_keys)

    # ---- 预览 + 录制（所有分支前创建：cold 推进阶段也可见、可录、可 ESC 中止）----
    from src.state.extractor import GameStateExtractor
    ex = GameStateExtractor()

    last_snap = 0
    record_on = True

    def frame_hook(e):
        nonlocal last_snap
        win.push(e.screenshot())
        if record_on and emu.frame_counter - last_snap >= 30:
            last_snap = emu.frame_counter
            st = ex.extract(emu)
            snap = {"t": emu.frame_counter, "ev": "snap",
                    "x": st.player_x, "y": st.player_y,
                    "b": float(e.screenshot().mean())}
            f.write(json.dumps(snap, ensure_ascii=False) + "\n")
            f.flush()
            win.set_status(f"REC ● t={emu.frame_counter} ({st.player_x},{st.player_y})"
                           f" F1解锁 F2剧情 F3对话 F4发现 F5节点")

    def tag_key(keycode):
        if keycode in TAG_KEYS:
            tag = TAG_KEYS[keycode]
            img_name = f"{demo_path.stem}_{emu.frame_counter:07d}.png"
            try:
                from PIL import Image
                Image.fromarray(emu.screenshot()).save(IMG_DIR / img_name)
            except Exception:
                img_name = None
            note = {"t": emu.frame_counter, "ev": "note", "tag": tag, "img": img_name}
            f.write(json.dumps(note, ensure_ascii=False) + "\n")
            f.flush()
            win.set_status(f"🏷 [{tag}] @ t={emu.frame_counter}")

    # auto_pause=False：人工操作不暂停模拟器（实玩体验，录制连贯）
    win = PreviewWindow(scale=4, speed=args.speed, emu=emu,
                        title=f"AIGBA 演示录制 - {demo_path.name}",
                        on_key=tag_key, auto_pause=False)
    emu.on_frame = frame_hook

    # ---- 起点 ----
    def real_move(d, frames=60):
        st0 = ex.extract(emu)
        p0 = (st0.player_x, st0.player_y)
        key = DIR_KEY[d]
        emu.press_hold(key)
        ok = False
        for _ in range(frames):
            emu.run_frames(1)
            st = ex.extract(emu)
            dx, dy = st.player_x - p0[0], st.player_y - p0[1]
            if d == "UP" and dy < -10 and abs(dx) < 8:
                ok = True
                break
            if d == "DOWN" and dy > 10 and abs(dx) < 8:
                ok = True
                break
            if d == "LEFT" and dx < -10 and abs(dy) < 8:
                ok = True
                break
            if d == "RIGHT" and dx > 10 and abs(dy) < 8:
                ok = True
                break
        emu.release()
        emu.run_frames(10)
        return ok

    def real_move_any():
        """4 方向任一可动 = 可控（单方向测试会因出生点撞墙误判不可控）。"""
        for d in ["UP", "DOWN", "LEFT", "RIGHT"]:
            if real_move(d):
                return True
        return False

    if args.manual:
        print("=== 纯人工冷启动：游戏已重置，从标题画面开始 ===")
        print("操作提示（AI 已破解的确定性序列）：")
        print("  标题 → 按 A（变焦）→ 等 ~5 秒 → DOWN+A×2 → 菜单选'新游戏'按 A")
        print("  → 开场对话连按 A → 可动后调钟（面向钟 A → A → UP+A）")
        print("  → 2F 东侧 (152,112) 面向 RIGHT 出门 → 到未白镇试解锁")
        print("REC 已开始——窗口里开始操作吧！")
    elif args.after_door:
        print("=== 自动到未白镇（开场→导航→出门，全程画面可见，ESC 中止）===")
        from src.brain.new_game import NewGameBootstrap
        b = NewGameBootstrap(emu, ex, None)
        assert b.boot_to_title(), "标题失败"
        assert b.start_new_game(), "新游戏失败"
        print("推进开场...")
        t0 = time.time()
        while time.time() - t0 < 600:
            if win.abort_requested():
                print("用户中止")
                break
            if real_move_any():
                print(f"🎉 真可动 ({time.time()-t0:.0f}s)")
                break
            b.advance_with_watchdog(120)
        else:
            print("✗ 未可控")
            sys.exit(1)
        st = ex.extract(emu)
        print(f"可控点: ({st.player_x},{st.player_y})")
        # 导航到 2F 东侧门口 (152,112) = 格 (9,7)
        from src.control.controller import Controller
        from src.control.dfs import DfsExplorer
        ctrl = Controller(emu, ex)
        explorer = DfsExplorer(emu, ex, ctrl, outdoor_bright=999, unlock_dialog=False)
        target = (9, 7)
        visited = {explorer._grid()}
        stack = []
        g = explorer._grid()
        facing = "UP"
        BACK = {"UP": "DOWN", "DOWN": "UP", "LEFT": "RIGHT", "RIGHT": "LEFT"}
        ok = False
        for steps in range(300):
            if win.abort_requested():
                print("用户中止")
                break
            if g == target:
                ok = True
                break
            right = {"UP": "RIGHT", "RIGHT": "DOWN", "DOWN": "LEFT", "LEFT": "UP"}[facing]
            left = {"UP": "LEFT", "LEFT": "DOWN", "DOWN": "RIGHT", "RIGHT": "UP"}[facing]
            moved = False
            for d in [right, facing, left, BACK[facing]]:
                ng = explorer.move_one(d)
                if ng is None:
                    continue
                if ng in visited:
                    explorer.move_one(BACK[d])
                    continue
                facing = d
                visited.add(ng)
                stack.append((g, d))
                g = ng
                moved = True
                break
            if moved:
                continue
            if not stack:
                break
            prev, came = stack.pop()
            explorer.move_one(BACK[came])
            g = prev
        print(f"到门口 (152,112): {ok}")
        # 面向 RIGHT 出门（确定性序列）
        emu.press(Key.RIGHT, 4)
        emu.run_frames(10)
        emu.press(Key.RIGHT, 30)
        emu.run_frames(300)
        st = ex.extract(emu)
        print(f"已到未白镇 ({st.player_x},{st.player_y}) b={emu.screenshot().mean():.0f}")
        print("试解锁：方向键/A/B/START/长按/组合 —— 一旦能走立刻按 F1！")
    elif args.cold:
        print("=== 冷启动（推进阶段窗口可见，ESC 可中止）===")
        from src.brain.new_game import NewGameBootstrap
        b = NewGameBootstrap(emu, ex, None)
        assert b.boot_to_title(), "标题失败"
        assert b.start_new_game(), "新游戏失败"
        print("推进开场...")
        t0 = time.time()
        while time.time() - t0 < 600:
            if win.abort_requested():
                print("用户中止")
                break
            if real_move_any():
                print(f"🎉 真可动 ({time.time()-t0:.0f}s)")
                break
            b.advance_with_watchdog(120)
        else:
            print("✗ 未可控")
            sys.exit(1)
        st = ex.extract(emu)
        print(f"可控点: ({st.player_x},{st.player_y}) —— 请接管操作")
    else:
        state_path = CK / args.state
        assert state_path.exists(), f"savestate 不存在: {state_path}"
        emu.load_state(state_path.read_bytes())
        emu.run_frames(60)
        print(f"加载 {args.state}: pos=({emu.u16(0x02020650)},{emu.u16(0x02020652)})"
              f" bright={emu.screenshot().mean():.0f} —— 请接管操作")

    # ---- 主循环 ----
    try:
        while not win.abort_requested():
            emu.run_frames(1)
    finally:
        f.write(json.dumps({"t": emu.frame_counter, "ev": "end",
                            "msg": "user exit"}) + "\n")
        f.flush()
        f.close()
        win.close()

    n_keys = sum(1 for _ in open(demo_path, encoding="utf-8") if '"keys"' in _)
    n_snap = sum(1 for _ in open(demo_path, encoding="utf-8") if '"snap"' in _)
    print(f"\n录制完成: {demo_path}")
    print(f"  按键事件 {n_keys} 个, 快照 {n_snap} 个, 共 {emu.frame_counter} 帧")
    print(f"回放: .venv\\Scripts\\python.exe tools/replay_demo.py {demo_path.name}")
    print(f"提取知识: .venv\\Scripts\\python.exe tools/demo_knowledge.py {demo_path.name}")


if __name__ == "__main__":
    main()
