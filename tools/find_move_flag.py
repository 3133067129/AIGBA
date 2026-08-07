"""行为标定"可动标志"：同进程内 可控(家) vs 锁(未白镇) diff → 逐个写回测试。

流程：
1. 冷启动 → 玩家可控 (152,112) → dump A
2. 面向 RIGHT warp → 未白镇锁态 (136,112) → dump B
3. diff → 候选标志字节 → 锁态下逐个写回 A 的值 → 可动测试
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import yaml

from src.emulator.keys import Key
from src.emulator.mgba_core import Emulator
from src.brain.new_game import NewGameBootstrap
from src.state.extractor import GameStateExtractor
from src.perception.llm_vision import make_provider

cfg = yaml.safe_load(open(ROOT / "config" / "settings.yaml", encoding="utf-8"))
emu = Emulator(rom_path=ROOT / cfg["rom"]["path"])
ex = GameStateExtractor()
vision = make_provider(cfg["llm"])
b = NewGameBootstrap(emu, ex, vision)
CK = ROOT / "data" / "checkpoints"
DUMP = ROOT / "data" / "tmp_dumps"
PX, PY = 0x02020650, 0x02020652


def player_controllable():
    s0 = emu.screenshot()
    emu.run_frames(30)
    s1 = emu.screenshot()
    if float((s0 != s1).mean()) > 0.02:
        return False
    s0 = emu.screenshot()
    emu.press_hold(Key.RIGHT)
    emu.run_frames(30)
    emu.release()
    emu.run_frames(10)
    s1 = emu.screenshot()
    return float((s0 != s1).mean()) > 0.05


def dump_mem(tag):
    data = emu.read(0x02000000, 0x40000) + emu.read(0x03000000, 0x8000)
    (DUMP / f"flag_{tag}.bin").write_bytes(data)
    return data


def can_move(d, frames=50):
    st0 = ex.extract(emu)
    p0 = (st0.player_x, st0.player_y)
    emu.press_hold(d)
    moved = False
    for _ in range(frames):
        emu.run_frames(1)
        st = ex.extract(emu)
        if (st.player_x, st.player_y) != p0:
            moved = True
            break
    emu.release()
    emu.run_frames(10)
    return moved


# ---- 1. 冷启动到可控 ----
print("=== 冷启动 ===")
assert b.boot_to_title(), "标题失败"
assert b.start_new_game(), "新游戏失败"
print("等待博士对话...")
t0 = time.time()
while time.time() - t0 < 200:
    b.run_frames_quiet(300)
    if "久等" in vision.describe([emu.screenshot()], "一句话")[:40]:
        break
print("推进开场...")
t0 = time.time()
while time.time() - t0 < 420:
    if player_controllable():
        print(f"🎉 可控 ({time.time()-t0:.0f}s)")
        break
    b.advance_with_watchdog(120, on_change=lambda d, t: None)

st = ex.extract(emu)
print(f"可控点: ({st.player_x},{st.player_y})")
A = dump_mem("A_house")
print("dump A（家可动态）✓")

# ---- 2. warp 出门 ----
print("面向 RIGHT warp...")
emu.press(Key.RIGHT, 4)
emu.run_frames(10)
emu.press(Key.RIGHT, 30)
emu.run_frames(300)
st = ex.extract(emu)
print(f"出门后: ({st.player_x},{st.player_y}) bright={emu.screenshot().mean():.0f}")
B = dump_mem("B_town")
print("dump B（未白镇锁态）✓")

# ---- 3. diff ----
diffs = [i for i in range(len(A)) if A[i] != B[i]]
print(f"总差异: {len(diffs)}")
# 排除玩家坐标（0x20650/52）
diffs = [i for i in diffs if not (0x20648 <= i <= 0x20660)]
# 候选：差异字节（优先 IWRAM 0x30000+ 和小值）
iwram = [i for i in diffs if i >= 0x30000]
ewram = [i for i in diffs if i < 0x30000]
print(f"IWRAM 差异: {len(iwram)} EWRAM 差异: {len(ewram)}")

# 候选排序：IWRAM 优先，小值优先
cands = sorted(iwram, key=lambda i: (abs(A[i] - B[i]) > 5, i)) + \
        sorted(ewram, key=lambda i: (abs(A[i] - B[i]) > 5, i))
print(f"候选: {len(cands)}")

# ---- 4. 逐个写回测试 ----
print("\n=== 写回测试（锁态改 A 值）===")
emu.load_state((CK / "outdoor_real.state").read_bytes())
emu.run_frames(30)
tested = 0
for i in cands:
    addr = i + 0x02000000 if i < 0x30000 else i + 0x03000000 - 0x30000
    # 实际地址计算：EWRAM 基址 0x02000000，IWRAM 基址 0x03000000
    addr = (0x02000000 + i) if i < 0x40000 else (0x03000000 + (i - 0x40000))
    if A[i] == B[i]:
        continue
    emu.write(addr, bytes([A[i]]))
    emu.run_frames(5)
    if can_move(Key.DOWN):
        print(f"🎉🎉🎉 可动标志 = 0x{addr:08X}（B={B[i]} → A={A[i]}）")
        Path(CK / "outdoor_real.state").write_bytes(emu.save_state())
        sys.exit(0)
    tested += 1
    if tested % 200 == 0:
        print(f"  已测 {tested}...")
print(f"测试 {tested} 个候选，未找到")

# 也试试方向键移动（DOWN 不行试 RIGHT）
print("\n=== 补测 RIGHT 方向 ===")
emu.load_state((CK / "outdoor_real.state").read_bytes())
emu.run_frames(30)
for i in cands:
    addr = (0x02000000 + i) if i < 0x40000 else (0x03000000 + (i - 0x40000))
    if A[i] == B[i]:
        continue
    emu.write(addr, bytes([A[i]]))
    emu.run_frames(5)
    if can_move(Key.RIGHT):
        print(f"🎉🎉🎉 可动标志 = 0x{addr:08X}（RIGHT 可动）")
        Path(CK / "outdoor_real.state").write_bytes(emu.save_state())
        sys.exit(0)
print("补测未找到")
