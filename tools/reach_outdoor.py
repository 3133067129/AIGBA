"""走正常出门路线 → 到达户外 (96,128) → 保存状态 → 探索未白镇。

路线（修复版 DFS 实证）：1F 楼梯 (120,208) → (8,13)→(8,8)→(7,8)→(7,7)
→ RIGHT (8,7) → warp → (19,10) → LEFT warp → (96,128) 户外！
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import yaml

from src.emulator.mgba_core import Emulator
from src.state.extractor import GameStateExtractor
from src.control.controller import Controller
from src.control.dfs import DfsExplorer

cfg = yaml.safe_load(open(ROOT / "config" / "settings.yaml", encoding="utf-8"))
CK = ROOT / "data" / "checkpoints"

emu = Emulator(rom_path=ROOT / cfg["rom"]["path"])
ex = GameStateExtractor()
ctrl = Controller(emu, ex)
emu.load_state((CK / "outside_room.state").read_bytes())
emu.run_frames(30)


def rep(tag):
    st = ex.extract(emu)
    print(f"{tag}: pos=({st.player_x},{st.player_y}) "
          f"grid=({st.player_x//16},{st.player_y//16}) bright={emu.screenshot().mean():.0f}")


rep("起点")
explorer = DfsExplorer(emu, ex, ctrl, outdoor_bright=130, unlock_dialog=True,
                       on_step=lambda t: print(f"  {t}"))
result = explorer.run(max_steps=400)
print("RESULT:", result)

if result.get("outdoor"):
    rep("户外！")
    CK_out = CK / "outdoor_real.state"
    CK_out.write_bytes(emu.save_state())
    print(f"✅ 已保存 {CK_out.name}（户外）")
    # 户外探索 100 步看看环境
    print("\n户外探索 80 步:")
    counter = [0]
    def on_step2(text):
        counter[0] += 1
        if counter[0] % 10 == 0:
            print(f"  {text}")
    explorer2 = DfsExplorer(emu, ex, ctrl, outdoor_bright=999, unlock_dialog=False,
                            on_step=on_step2)
    r2 = explorer2.run(max_steps=80)
    print("户外探索 RESULT:", r2)
else:
    print("✗ 未到达户外")
