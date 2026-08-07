"""v3：从 house_2f_ready（真可动）→ 导航到 (152,112) 门口 → RIGHT 出门 → 解锁 → DFS。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
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
CK = ROOT / "data" / "checkpoints"
F = 0x03000F2C
DIR_KEY = {"UP": Key.UP, "DOWN": Key.DOWN, "LEFT": Key.LEFT, "RIGHT": Key.RIGHT}


def rep(tag):
    st = ex.extract(emu)
    print(f"{tag}: pos=({st.player_x},{st.player_y}) "
          f"grid=({st.player_x//16},{st.player_y//16}) bright={emu.screenshot().mean():.0f}")


def real_move(d, frames=60):
    """方向验证移动。返回 (ok, pos)。"""
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
    st = ex.extract(emu)
    return ok, (st.player_x, st.player_y)


# ---- 1. 恢复真可动态 ----
emu.load_state((CK / "house_2f_ready.state").read_bytes())
emu.run_frames(30)
emu.write(F, b"\x00")  # savestate 恢复后 MOVE_FLAG=1 → 写 0
emu.run_frames(10)
rep("恢复")
ok, pos = real_move("UP")
print(f"恢复后 UP: ok={ok} →{pos}")
if not ok:
    print("✗ 恢复后不可动（savestate 漂移）")
    sys.exit(1)

# ---- 2. 导航到 (152,112) ----
print("导航到门口 (152,112)...")
explorer = DfsExplorer(emu, ex, ctrl, outdoor_bright=999, unlock_dialog=False)
target = (9, 7)  # (152,112)
visited = {explorer._grid()}
stack = []
g = explorer._grid()
facing = "UP"
BACK = {"UP": "DOWN", "DOWN": "UP", "LEFT": "RIGHT", "RIGHT": "LEFT"}
found = False
for steps in range(300):
    if g == target:
        found = True
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
print(f"到门口: {found}（visited={len(visited)}）")
rep("门口")

# ---- 3. 出门 ----
print("面向 RIGHT 按方向键出门...")
emu.press(Key.RIGHT, 4)
emu.run_frames(10)
emu.press(Key.RIGHT, 30)
emu.run_frames(300)
rep("出门后")

# ---- 4. 解锁 + 方向验证 ----
emu.write(F, b"\x00")
emu.run_frames(10)
ok, pos = real_move("UP")
print(f"解锁后 UP: ok={ok} →{pos}")
if not ok:
    ok2, pos2 = real_move("DOWN")
    print(f"解锁后 DOWN: ok={ok2} →{pos2}")
    if not ok2:
        print("✗ 未解锁")
        sys.exit(1)

print("🎉 未白镇解锁成功！")
Path(CK / "outdoor_real.state").write_bytes(emu.save_state())
print("已保存 outdoor_real.state")

# ---- 5. DFS 探索 ----
print("\n=== DFS 探索 ===")
explorer2 = DfsExplorer(emu, ex, ctrl, outdoor_bright=999, unlock_dialog=False,
                        on_step=lambda t: print(f"  {t}"))
result = explorer2.run(max_steps=3000)
print("RESULT:", result)
Path(CK / "outdoor_real.state").write_bytes(emu.save_state())
print("已重存 outdoor_real.state")
