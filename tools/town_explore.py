"""从 outdoor_real.state（未白镇户外可动）出发：DFS 全图 + 找邻居家/建筑/路口。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import yaml
from PIL import Image

from src.emulator.mgba_core import Emulator
from src.state.extractor import GameStateExtractor
from src.control.controller import Controller
from src.control.dfs import DfsExplorer

cfg = yaml.safe_load(open(ROOT / "config" / "settings.yaml", encoding="utf-8"))
emu = Emulator(rom_path=ROOT / cfg["rom"]["path"])
ex = GameStateExtractor()
ctrl = Controller(emu, ex)
CK = ROOT / "data" / "checkpoints"

emu.load_state((CK / "outdoor_real.state").read_bytes())
emu.run_frames(30)
st = ex.extract(emu)
print(f"起点: ({st.player_x},{st.player_y}) bright={emu.screenshot().mean():.0f}")

# 记录所有格子的 bright（找建筑/门/路口线索）
visited = {}


def on_step(text):
    st = ex.extract(emu)
    visited[(st.player_x // 16, st.player_y // 16)] = float(emu.screenshot().mean())
    print(f"  {text}")


explorer = DfsExplorer(emu, ex, ctrl, outdoor_bright=999, unlock_dialog=False,
                       on_step=on_step)
result = explorer.run(max_steps=3000)
print("RESULT:", result)

# 分析：格子的 bright 分布（找异常点 = 建筑/门）
print(f"\n访问 {len(visited)} 格")
xs = [g[0] for g in visited]
ys = [g[1] for g in visited]
print(f"范围: x {min(xs)}-{max(xs)}, y {min(ys)}-{max(ys)}")
# bright 直方图
from collections import Counter
brights = Counter(int(v) for v in visited.values())
print("bright 分布:", dict(sorted(brights.items())))

# 保存户外状态（DFS 结束时位置）
Path(CK / "outdoor_real.state").write_bytes(emu.save_state())
print("已重存 outdoor_real.state")

# 截图
img = emu.screenshot()
Image.fromarray(img).save(ROOT / "data/tmp_dumps/town_end.png")
print("已保存 town_end.png")
