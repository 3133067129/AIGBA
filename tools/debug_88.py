"""调试 (8,8) 格 LEFT 移动失败：逐帧打印坐标/亮度。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import yaml

from src.emulator.keys import Key
from src.emulator.mgba_core import Emulator
from src.state.extractor import GameStateExtractor
from src.control.controller import Controller
from src.control.dfs import DfsExplorer

cfg = yaml.safe_load(open(ROOT / "config" / "settings.yaml", encoding="utf-8"))
emu = Emulator(rom_path=ROOT / cfg["rom"]["path"])
ex = GameStateExtractor()
ctrl = Controller(emu, ex)
emu.load_state((ROOT / "data/checkpoints/outside_room.state").read_bytes())
emu.run_frames(30)

explorer = DfsExplorer(emu, ex, ctrl, outdoor_bright=130, unlock_dialog=False)

PATH = [("RIGHT", (8, 13)), ("UP", (8, 12)), ("UP", (8, 11)), ("UP", (8, 10)),
        ("UP", (8, 9)), ("UP", (8, 8))]
for d, expect in PATH:
    ng = explorer.move_one(d)
    print(f"  {d} → {ng} (期望 {expect}) bright={emu.screenshot().mean():.0f}")
    st = ex.extract(emu)
    print(f"    pos=({st.player_x},{st.player_y})")
    if ng != expect:
        break

st = ex.extract(emu)
print(f"\n在 ({st.player_x},{st.player_y}) 格({st.player_x//16},{st.player_y//16})")
print("按住 LEFT 逐帧观察:")
emu.press_hold(Key.LEFT)
moved = False
for i in range(60):
    emu.run_frames(1)
    st = ex.extract(emu)
    g = (st.player_x // 16, st.player_y // 16)
    if i < 12 or (i % 4 == 0):
        print(f"  f{i}: pos=({st.player_x},{st.player_y}) grid={g}")
    if g != (8, 8):
        moved = True
        break
emu.release()
st = ex.extract(emu)
print(f"结果: moved={moved} pos=({st.player_x},{st.player_y}) bright={emu.screenshot().mean():.0f}")

# 若 LEFT 失败，试 UP（楼梯?）与 DOWN
if not moved:
    for d in ["UP", "DOWN"]:
        emu.press_hold(getattr(Key, d))
        moved2 = False
        for i in range(40):
            emu.run_frames(1)
            st = ex.extract(emu)
            if (st.player_x // 16, st.player_y // 16) != (8, 8):
                moved2 = True
                break
        emu.release()
        st = ex.extract(emu)
        print(f"  {d}: moved={moved2} pos=({st.player_x},{st.player_y}) "
              f"bright={emu.screenshot().mean():.0f}")
        if moved2:
            # 走回来
            emu.press_hold(getattr(Key, {"UP": "DOWN", "DOWN": "UP"}[d]))
            for i in range(40):
                emu.run_frames(1)
                st = ex.extract(emu)
                if (st.player_x // 16, st.player_y // 16) == (8, 8):
                    break
            emu.release()
            print(f"  已走回 ({st.player_x},{st.player_y})")
