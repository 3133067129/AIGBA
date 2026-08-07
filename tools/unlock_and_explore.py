"""解锁未白镇（写 0x03000F2C=0）→ 可动验证 → DFS 全图探索。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import yaml
from PIL import Image

from src.emulator.keys import Key
from src.emulator.mgba_core import Emulator
from src.state.extractor import GameStateExtractor
from src.control.controller import Controller
from src.control.dfs import DfsExplorer

cfg = yaml.safe_load(open(ROOT / "config" / "settings.yaml", encoding="utf-8"))
emu = Emulator(rom_path=ROOT / cfg["rom"]["path"])
ex = GameStateExtractor()
ctrl = Controller(emu, ex)
CK = ROOT / "data" / "checkpoints"
DIR_KEY = {"UP": Key.UP, "DOWN": Key.DOWN, "LEFT": Key.LEFT, "RIGHT": Key.RIGHT}

MOVE_FLAG = 0x03000F2C  # 可动标志：0=可动，1=锁

emu.load_state((CK / "outdoor_real.state").read_bytes())
emu.run_frames(30)


def rep(tag):
    st = ex.extract(emu)
    print(f"{tag}: pos=({st.player_x},{st.player_y}) "
          f"grid=({st.player_x//16},{st.player_y//16}) bright={emu.screenshot().mean():.0f}")


rep("锁态")

# 解锁
emu.write(MOVE_FLAG, b"\x00")
emu.run_frames(10)
print(f"写入 0x{MOVE_FLAG:08X}=0")
rep("解锁后")

# 可动验证
moved_any = False
for d in ["UP", "DOWN", "LEFT", "RIGHT"]:
    st0 = ex.extract(emu)
    p0 = (st0.player_x, st0.player_y)
    emu.press_hold(DIR_KEY[d])
    moved = False
    for _ in range(60):
        emu.run_frames(1)
        st = ex.extract(emu)
        if (st.player_x, st.player_y) != p0:
            moved = True
            break
    emu.release()
    emu.run_frames(15)
    st = ex.extract(emu)
    print(f"  {d}: moved={moved} →({st.player_x},{st.player_y}) "
          f"bright={emu.screenshot().mean():.0f}")
    moved_any = moved_any or moved
    if moved:
        # 走回来
        emu.press_hold({"UP": Key.DOWN, "DOWN": Key.UP,
                        "LEFT": Key.RIGHT, "RIGHT": Key.LEFT}[d])
        for _ in range(60):
            emu.run_frames(1)
            st = ex.extract(emu)
            if (st.player_x, st.player_y) == p0:
                break
        emu.release()
        emu.run_frames(15)

if not moved_any:
    print("✗ 仍锁（标志可能被自动改回）")
    sys.exit(1)

print("🎉 解锁成功！保存状态")
Path(CK / "outdoor_real.state").write_bytes(emu.save_state())

# 截图
img = emu.screenshot()
Image.fromarray(img).save(ROOT / "data/tmp_dumps/town_unlocked.png")
print("已保存 town_unlocked.png")

# DFS 全图探索未白镇
print("\n=== DFS 探索未白镇 ===")
explorer = DfsExplorer(emu, ex, ctrl, outdoor_bright=999, unlock_dialog=False,
                       on_step=lambda t: print(f"  {t}"))
result = explorer.run(max_steps=3000)
print("RESULT:", result)
Path(CK / "outdoor_real.state").write_bytes(emu.save_state())
print("已重存 outdoor_real.state")
