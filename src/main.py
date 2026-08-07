"""CLI 入口。

用法:
  python src/main.py smoke          # Phase 0 冒烟测试（跑帧/截图/存档往返）
  python src/main.py verify-offsets # 标定 offsets.json（Phase 0）
  python src/main.py new-game       # 新开档（Phase 1 起可用）
  python src/main.py resume         # 从最新 checkpoint 续跑
  python src/main.py run            # 正常自动游玩
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 输出统一 UTF-8：LLM 文本可能含 ® 等符号，GBK 控制台/重定向会崩
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import yaml

from src.emulator.mgba_core import Emulator, EmulatorError
from src.state.extractor import GameStateExtractor
from src.state.offsets import OffsetTable


def load_config() -> dict:
    with open(ROOT / "config" / "settings.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def make_emulator(cfg: dict) -> Emulator:
    return Emulator(
        rom_path=ROOT / cfg["rom"]["path"],
        sav_path=ROOT / cfg["rom"]["sav"],
        sav_footer_bytes=cfg["rom"].get("sav_footer_bytes", 0),
    )


def cmd_smoke(cfg: dict) -> int:
    """冒烟测试：加载 ROM+存档 → 跑 1200 帧 → 截图 → 状态提取 → 存档往返。"""
    emu = make_emulator(cfg)
    extractor = GameStateExtractor()

    print(f"ROM loaded: {emu.core.game_title} [{emu.core.game_code}]")
    print(f"video dims: {emu._video_dims}")

    emu.run_frames(1200)
    print(f"frame counter after 1200 frames: {emu.frame_counter}")

    img = emu.screenshot()
    import numpy as np
    n_colors = len(np.unique(img.reshape(-1, 3), axis=0))
    print(f"screenshot: shape={img.shape} dtype={img.dtype} unique_colors={n_colors}")
    from PIL import Image
    shot_path = ROOT / "data" / "screenshots" / "smoke_frame.png"
    shot_path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(img).save(shot_path)
    print(f"screenshot saved: {shot_path}")

    state = extractor.extract(emu)
    print(f"state: map={state.map_key} pos=({state.player_x},{state.player_y}) "
          f"party={state.party_count} battle={state.in_battle} money={state.money}")
    for m in state.party:
        print(f"  party: species={m.species} lv={m.level} hp={m.current_hp}/{m.max_hp} "
              f"moves={m.moves} item={m.held_item}")

    # 存档往返
    raw = emu.save_state()
    print(f"raw state size: {len(raw)} bytes")
    ok = emu.load_state(raw)
    print(f"load_raw_state roundtrip: {ok}")

    return 0


def cmd_explore(cfg: dict, checkpoint: str = "after_intro_fixed.state",
                max_steps: int = 60, preview: bool = True,
                speed: float = 1.0) -> int:
    """探索模式：从 checkpoint 出发，LLM 引导走向城镇中心 + 对话 NPC + 菜单开合。"""
    from src.brain.explore import ExploreAgent
    from src.brain.knowledge import Knowledge
    from src.control.controller import Controller
    from src.perception.llm_vision import make_provider
    from src.persistence.knowledge_store import KnowledgeStore

    from src.emulator.preview import PreviewWindow

    emu = Emulator(rom_path=ROOT / cfg["rom"]["path"])
    cp = ROOT / "data" / "checkpoints" / checkpoint
    if not cp.exists():
        print(f"[FATAL] checkpoint 不存在: {cp}")
        return 1
    emu.load_state(cp.read_bytes())
    emu.run_frames(45)

    win = None
    if preview:
        try:
            win = PreviewWindow(title="AI 探索 · 绿宝石386", speed=speed, emu=emu)
            emu.on_frame = lambda e: win.push(e.screenshot())
            print(f"[preview] 实时预览窗已打开（+/-调速 p暂停 ESC退出，当前 {speed}x）")
        except Exception as e:
            print(f"[preview] 预览窗打开失败: {e}")
            win = None

    extractor = GameStateExtractor()
    vision = make_provider(cfg["llm"])
    knowledge = Knowledge(KnowledgeStore(ROOT / "data" / "knowledge"))
    controller = Controller(emu, extractor)
    agent = ExploreAgent(emu, extractor, vision, controller, knowledge,
                         preview=win)

    st = extractor.extract(emu)
    print(f"[explore] 起点: pos=({st.player_x},{st.player_y}) "
          f"map={st.map_key} money={st.money}")
    checkpoint_dir = ROOT / "data" / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)

    def _autosave(r):
        # 每步自动保存（文件 ~50KB，开销可忽略），随时可恢复调试
        (checkpoint_dir / "explore_progress.state").write_bytes(
            emu.save_state())

    stats = agent.run(max_steps=max_steps, on_step=_autosave)
    print(f"\n[explore] 完成: {stats['steps']} 步, {stats['seconds']:.0f}s")
    print(f"  NPC对话×{stats['npc_talks']} 菜单开合={'✓' if stats['menu_tested'] else '✗'} "
          f"到达城镇={'✓' if stats['town'] else '✗'}")
    print(f"  动作分布: {stats['actions']}")

    (checkpoint_dir / "explore_progress.state").write_bytes(emu.save_state())
    print(f"已保存 explore_progress.state")
    if win:
        win.close()
    return 0


def cmd_navigate(cfg: dict, max_steps: int = 120, preview: bool = True,
                 speed: float = 1.0) -> int:
    """户外导航：after_intro → 推进妈妈对话 → 户外可控 → DFS 遍历未白镇。

    坐标驱动（不依赖 LLM 方向）：右墙法则遍历 + 每 6 格 LLM 慢速确认
    是否到达城镇中心（qwen 7B 的"场景描述"比"方向判断"可靠）。
    全程单进程连续（不保存/恢复 savestate，绕开过场状态不稳定）。
    """
    import hashlib
    from src.emulator.keys import Key as K
    from src.control.controller import Controller
    from src.control.dfs import DfsExplorer
    from src.emulator.preview import PreviewWindow
    from src.perception.llm_vision import make_provider

    emu = Emulator(rom_path=ROOT / cfg["rom"]["path"])
    cp = ROOT / "data" / "checkpoints" / "after_intro.state"
    if not cp.exists():
        print(f"[FATAL] checkpoint 不存在: {cp}")
        return 1
    emu.load_state(cp.read_bytes())
    emu.run_frames(60)

    win = None
    if preview:
        try:
            win = PreviewWindow(title="AI 导航未白镇 · 绿宝石386", speed=speed, emu=emu)
            emu.on_frame = lambda e: win.push(e.screenshot())
            print(f"[preview] 预览窗已打开（+/-调速 p暂停 ESC退出，当前 {speed}x）")
        except Exception as e:
            print(f"[preview] 预览窗打开失败: {e}")
            win = None

    def _aborted():
        return win is not None and win.abort_requested()

    extractor = GameStateExtractor()
    vision = make_provider(cfg["llm"])
    controller = Controller(emu, extractor)

    # 1. 推进妈妈对话（A 等文字稳定；位置变化 = 转场完成即停，
    #    避免按太多 A 推进过场进家——2026-08-06 实测 A×6 到户外 (152,92)）
    print("[navigate] 推进妈妈对话...")
    start_pos = (extractor.extract(emu).player_x,
                 extractor.extract(emu).player_y)
    for i in range(10):
        if _aborted():
            return 0
        for _ in range(30):
            tr = emu.screenshot()[96:158, 8:232]
            h1 = hashlib.sha256(tr.tobytes()).hexdigest()
            emu.run_frames(5)
            if hashlib.sha256(emu.screenshot()[96:158, 8:232].tobytes()).hexdigest() == h1:
                break
        h = hashlib.sha256(emu.screenshot().tobytes()).hexdigest()[:6]
        emu.press(K.A, 8)
        emu.run_frames(80)
        h2 = hashlib.sha256(emu.screenshot().tobytes()).hexdigest()[:6]
        now = extractor.extract(emu)
        now_pos = (now.player_x, now.player_y)
        if now_pos != start_pos:
            print(f"[navigate] 转场完成（位置变化 {start_pos}->{now_pos}，A×{i+1}）")
            break
        if h2 == h:
            print(f"[navigate] 对话推进完毕 (A×{i+1})")
            break
    st = extractor.extract(emu)
    print(f"[navigate] 当前位置: ({st.player_x},{st.player_y}) "
          f"bright={float(emu.screenshot().mean()):.0f}")

    # 2. 等过场动画播完（过场终点 = 新家内 (120,112)）
    print("[navigate] 等过场播完（终点=家内）...")
    emu.run_frames(400)
    st = extractor.extract(emu)
    print(f"[navigate] 过场后: ({st.player_x},{st.player_y}) "
          f"bright={float(emu.screenshot().mean()):.0f}")

    # 3. A 解锁妈妈对话（savestate 恢复后玩家可能被对话锁定）
    def _can_move() -> bool:
        s0 = extractor.extract(emu)
        pos0 = (s0.player_x, s0.player_y)
        emu.press_hold(K.RIGHT)
        emu.run_frames(25)
        emu.release()
        emu.run_frames(40)
        s1 = extractor.extract(emu)
        return (s1.player_x, s1.player_y) != pos0

    print("[navigate] 解锁对话...")
    for _ in range(8):
        if _can_move():
            print("[navigate] 玩家可控 ✓")
            break
        for _ in range(30):
            tr = emu.screenshot()[96:158, 8:232]
            h1 = hashlib.sha256(tr.tobytes()).hexdigest()
            emu.run_frames(5)
            if hashlib.sha256(emu.screenshot()[96:158, 8:232].tobytes()).hexdigest() == h1:
                break
        emu.press(K.A, 8)
        emu.run_frames(80)

    # 4. 阶段 A：家内 DFS 找门（bright 大幅上升 >45 = 通向户外的门）
    print("[navigate] 阶段A：家内找门...")
    explorer = DfsExplorer(emu, extractor, controller, outdoor_bright=999,
                           unlock_dialog=True,
                           on_step=lambda s: print(f"  {s}") if ("→" in s or "目标" in s or "回溯" in s) else None)

    def _find_door(step, grid, e):
        # 每步探测：bright 上升检测（在 run 循环外单独处理，这里只确认）
        return False

    # 家内 DFS：探测每格 4 方向，bright 上升 > 45 = 门
    door_found = False
    g = explorer._grid()
    visited = {g}
    stack = []
    facing = "UP"
    DIRS = ["UP", "RIGHT", "DOWN", "LEFT"]
    BACKD = {"UP": "DOWN", "DOWN": "UP", "LEFT": "RIGHT", "RIGHT": "LEFT"}
    for _step in range(max_steps):
        if _aborted():
            break
        b0 = float(emu.screenshot().mean())
        right = {"UP": "RIGHT", "RIGHT": "DOWN", "DOWN": "LEFT", "LEFT": "UP"}[facing]
        left = {"UP": "LEFT", "LEFT": "DOWN", "DOWN": "RIGHT", "RIGHT": "UP"}[facing]
        moved = False
        for d in [right, facing, left, BACKD[facing]]:
            ng = explorer.move_one(d)
            if ng is None:
                continue
            b1 = float(emu.screenshot().mean())
            if b1 - b0 > 45:
                print(f"  🎯 找到门! ({g[0]},{g[1]}) {d} -> ({ng[0]},{ng[1]}) "
                      f"bright {b0:.0f}->{b1:.0f}")
                door_found = True
                break
            if ng in visited:
                explorer.move_one(BACKD[d])
                continue
            facing = d
            visited.add(ng)
            stack.append((g, d))
            g = ng
            moved = True
            break
        if door_found:
            break
        if moved:
            continue
        if not stack:
            break
        prev, came = stack.pop()
        explorer.move_one(BACKD[came])
        g = prev
    print(f"[navigate] 阶段A结果: door={door_found} visited={len(visited)}")
    if not door_found:
        print("[navigate] 家内未找到门")
        if win:
            win.close()
        return 1

    # 5. 阶段 B：户外导航（跳过门方向，找城镇中心）
    print("[navigate] 阶段B：户外导航...")
    emu.run_frames(200)  # 出门动画完
    st = extractor.extract(emu)
    print(f"[navigate] 户外: ({st.player_x},{st.player_y}) "
          f"bright={float(emu.screenshot().mean()):.0f}")
    explorer2 = DfsExplorer(emu, extractor, controller, outdoor_bright=999,
                            unlock_dialog=False, door_drop=45,
                            on_step=lambda s: print(f"  {s}") if ("→" in s or "目标" in s or "回溯" in s) else None)

    def _confirm(step, grid, e):
        if _aborted():
            return True
        desc = vision.describe(
            [e.screenshot()],
            "这里是小镇中心/广场吗（能看到很多房子、招牌、宽阔地面或多人）？"
            "只回答一个字：是或否")
        print(f"  [确认{step}] {desc[:40]}")
        return "是" in desc[:3]

    result = explorer2.run(max_steps=max_steps, confirm=_confirm, confirm_every=6)
    print(f"\n[navigate] 阶段B结果: {result}")
    st = extractor.extract(emu)
    print(f"  位置: ({st.player_x},{st.player_y}) "
          f"bright={float(emu.screenshot().mean()):.0f}")

    checkpoint_dir = ROOT / "data" / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    (checkpoint_dir / "town_center.state").write_bytes(emu.save_state())
    print(f"已保存 town_center.state")
    if win:
        win.close()
    return 0


def cmd_verify_offsets(cfg: dict) -> int:
    from src.state.verify_offsets import verify_all
    emu = make_emulator(cfg)
    table = OffsetTable.load()
    verify_all(emu, table)
    table.save()
    print("offsets.json saved")
    return 0


def cmd_new_game(cfg: dict, minutes: int = 20, preview: bool = True) -> int:
    """新开档：标题→菜单→新游戏→开场对话→走出家门（Phase 1 流程）。

    preview=True 时打开 pygame 实时预览窗（ESC 可中止流程）。
    """
    from src.brain.new_game import NewGameBootstrap
    from src.brain.knowledge import Knowledge
    from src.control.controller import Controller
    from src.perception.llm_vision import make_provider
    from src.persistence.knowledge_store import KnowledgeStore

    from src.emulator.preview import PreviewWindow

    emu = Emulator(rom_path=ROOT / cfg["rom"]["path"])
    extractor = GameStateExtractor()
    vision = make_provider(cfg["llm"])
    knowledge = Knowledge(KnowledgeStore(ROOT / "data" / "knowledge"))
    controller = Controller(emu, extractor)

    # 实时预览窗（每帧自动推送，无需手动刷新）
    win = None
    if preview:
        try:
            win = PreviewWindow(emu=emu)
            emu.on_frame = lambda e: win.push(e.screenshot())
            print("[preview] 实时预览窗已打开（ESC 中止流程）")
        except Exception as e:
            print(f"[preview] 预览窗打开失败，继续无预览运行: {e}")
            win = None

    def _aborted() -> bool:
        return win is not None and win.abort_requested()

    def _status(text: str) -> None:
        print(text)
        if win:
            win.set_status(text)

    b = NewGameBootstrap(emu, extractor, vision)
    _status("[new-game] 启动模拟器，等待标题画面...")
    if not b.boot_to_title():
        print("[FATAL] 未能到达标题画面")
        return 1
    if not b.start_new_game():
        print("[FATAL] 新游戏启动失败")
        return 1

    _status("[new-game] 等待博士对话...")
    import time
    t0 = time.time()
    while time.time() - t0 < 200:
        b.run_frames_quiet(300)
        if _aborted():
            _status("[new-game] 用户中止")
            return 0
        if "久等" in vision.describe([emu.screenshot()], "一句话")[:40]:
            break

    _status(f"[new-game] 推进开场（最多 {minutes} 分钟，窗口实时可见）...")
    from src.emulator.keys import Key as K

    def _player_controllable() -> bool:
        """可靠判定（2026-08-06 修正）：静止预检 + 按键测试。

        旧的单键测试在过场动画中误报（动画本身画面持续变化）：
          1. 不按键 30 帧画面变化 > 2% = 过场/字幕动画中 → 不可控
          2. 按方向键 30 帧画面变化 > 5% = 玩家真的动了 → 可控
        """
        import numpy as np
        s0 = emu.screenshot()
        emu.run_frames(30)
        s1 = emu.screenshot()
        if float((s0 != s1).mean()) > 0.02:
            return False  # 动画中（过场/字幕）
        s0 = emu.screenshot()
        emu.press_hold(K.RIGHT)
        emu.run_frames(30)
        emu.release()
        emu.run_frames(10)
        s1 = emu.screenshot()
        return float((s0 != s1).mean()) > 0.05

    t0 = time.time()
    while time.time() - t0 < minutes * 60:
        if _aborted():
            _status("[new-game] 用户中止，保存当前进度")
            break
        if _player_controllable():
            _status(f"[new-game] 玩家可控！({time.time()-t0:.0f}s) 走向门口/出口...")
            for _ in range(8):
                if _aborted():
                    break
                s = emu.screenshot()
                d = vision.describe(
                    [s], "你在房间里，门/出口在哪个方向？只回答：上/下/左/右")[:8]
                key = {"上": K.UP, "下": K.DOWN, "左": K.LEFT, "右": K.RIGHT}\
                    .get(d.strip()[0] if d.strip() else "", K.RIGHT)
                _status(f"[new-game] LLM 判断门方向: {key.name}")
                emu.press_hold(key)
                emu.run_frames(40)
                emu.release()
                emu.run_frames(10)
                if not _player_controllable():
                    _status("[new-game] 场景切换（出门/过场）")
                    break  # 已切换场景（出门/过场）
            break
        else:
            b.advance_with_watchdog(120, on_change=lambda d, t: _status(f"  [{t}s] {d}"))
    # 出门后可能触发过场（搬家卡车动画）→ 推进到真正可控再保存
    # （2026-08-06 教训：旧逻辑在过场中保存，checkpoint 恢复后玩家不可控）
    _status("[new-game] 推进可能的出门过场，直到真正可控...")
    for _ in range(10):
        if _player_controllable():
            _status("[new-game] 真正可控 ✓")
            break
        b.advance_with_watchdog(90, on_change=lambda d, t: _status(f"  [{t}s] {d}"))
    checkpoint_dir = ROOT / "data" / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    (checkpoint_dir / "after_intro.state").write_bytes(emu.save_state())
    _status(f"[new-game] 已保存 after_intro.state（当前帧 {emu.frame_counter}）")
    if win:
        win.close()
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="AI 玩宝可梦绿宝石386")
    parser.add_argument("cmd", choices=["smoke", "verify-offsets", "new-game",
                                        "explore", "navigate", "resume", "run"])
    parser.add_argument("--minutes", type=int, default=20, help="开场推进时长（分钟）")
    parser.add_argument("--steps", type=int, default=60, help="探索步数上限")
    parser.add_argument("--speed", type=float, default=1.0,
                        help="预览倍速（0.5~30，运行时 +/- 调整）")
    parser.add_argument("--checkpoint", default="after_intro_fixed.state",
                        help="探索起点 checkpoint 文件名")
    parser.add_argument("--no-preview", action="store_true",
                        help="不打开实时预览窗（无头运行）")
    args = parser.parse_args()

    cfg = load_config()
    try:
        if args.cmd == "smoke":
            rc = cmd_smoke(cfg)
        elif args.cmd == "verify-offsets":
            rc = cmd_verify_offsets(cfg)
        elif args.cmd == "navigate":
            rc = cmd_navigate(cfg, max_steps=args.steps,
                              preview=not args.no_preview, speed=args.speed)
        elif args.cmd == "explore":
            rc = cmd_explore(cfg, checkpoint=args.checkpoint,
                             max_steps=args.steps, preview=not args.no_preview,
                             speed=args.speed)
        elif args.cmd == "new-game":
            rc = cmd_new_game(cfg, minutes=args.minutes, preview=not args.no_preview)
        else:
            print(f"命令 {args.cmd} 尚未实现（Phase 1+）")
            rc = 1
    except EmulatorError as e:
        print(f"[FATAL] {e}")
        rc = 1
    sys.exit(rc)


if __name__ == "__main__":
    main()
