"""新游戏流程探索工具（开发用）：标题→菜单→进入游戏。

用法: python tools/try_newgame.py [--steps 8]
每步: 截图 → LLM 描述 → 人工/规则决策按什么键
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
import yaml

from src.emulator.keys import Key
from src.emulator.mgba_core import Emulator
from src.perception.llm_vision import make_provider

DESCRIBE_PROMPT = ("这是宝可梦绿宝石(中文版)的游戏画面。请回答："
                   "1) 当前是什么界面（标题/主菜单/对话/地图/战斗/其他）？"
                   "2) 画面中的全部文字，逐行完整识别（中文）。"
                   "3) 如果屏幕上有可选择菜单，列出每个菜单项及其位置（上/下/左/右/中间）。"
                   "4) 画面中还有什么值得注意的（人物/宝可梦/建筑物/门）。"
                   "简洁回答，用中文。")


def main() -> None:
    cfg = yaml.safe_load((ROOT / "config" / "settings.yaml").read_text(encoding="utf-8"))
    vision = make_provider(cfg["llm"])

    # 不加载存档 —— 干净进入标题画面
    emu = Emulator(rom_path=ROOT / cfg["rom"]["path"])
    emu.run_frames(60)
    print(f"[boot] frame={emu.frame_counter}")

    steps = int(sys.argv[sys.argv.index("--steps") + 1]) if "--steps" in sys.argv else 8
    for i in range(steps):
        emu.run_frames(60)
        screen = emu.screenshot()
        (ROOT / "data" / "screenshots" / f"step{i:02d}.png").write_bytes(
            _to_png(screen))
        mean = float(screen.mean())
        print(f"--- step {i} (frame={emu.frame_counter}, mean_bright={mean:.0f}) ---")
        t0 = time.time()
        desc = vision.describe([screen], DESCRIBE_PROMPT)
        print(f"[LLM {time.time()-t0:.1f}s] {desc[:400]}")
        print("输入按键 [A/a 按A] [B/b] [UP/DOWN/LEFT/RIGHT] [START] [X 结束]: ", end="", flush=True)
        cmd = input().strip().upper()
        if cmd == "X":
            break
        mapping = {"A": Key.A, "B": Key.B, "START": Key.START,
                   "UP": Key.UP, "DOWN": Key.DOWN, "LEFT": Key.LEFT, "RIGHT": Key.RIGHT}
        if cmd in mapping:
            emu.press(mapping[cmd], 10)
            emu.run_frames(30)


def _to_png(screen: np.ndarray) -> bytes:
    from PIL import Image
    import io
    buf = io.BytesIO()
    Image.fromarray(screen).save(buf, format="PNG")
    return buf.getvalue()


if __name__ == "__main__":
    main()
