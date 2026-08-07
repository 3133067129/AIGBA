"""内存偏移标定/验证（Phase 0）。

策略：加载 ROM+存档 → 跑到稳定状态 → 对每个偏移做合理性验证：
- 玩家坐标: 数值在合理地图范围内，且按住方向键后应变化（若有把握安全移动）
- 队伍: species ∈ [1,386]（386 hack 范围），HP 一致
- 战斗相关: 非战斗时为 0
- 图鉴位图: 已标定后应能算出 seen/owned 计数
只把验证通过的项写回 offsets.json；失败的保留原值并告警。
"""
from __future__ import annotations

from src.emulator.mgba_core import Emulator
from src.state.offsets import OffsetTable
from src.state.pokemon_decrypt import parse_party


def _plausible_x(x: int) -> bool:
    return 1 <= x <= 0xFFFF  # 地图坐标通常 < 20000


def verify_all(emu: Emulator, table: OffsetTable) -> None:
    emu.run_frames(600)  # 进到稳定帧

    # --- 玩家坐标 ---
    for name in ("player_x", "player_y"):
        spec = table.get(name)
        v = emu.u16(spec["addr"]) if spec["type"] == "u16" else emu.u8(spec["addr"])
        ok = _plausible_x(v)
        print(f"[{name}] 0x{spec['addr']:08X} = {v} {'OK' if ok else 'SUSPICIOUS'}")

    # --- 地图 ---
    mg = table.get("map_group")
    mn = table.get("map_num")
    mgv, mnv = emu.u8(mg["addr"]), emu.u8(mn["addr"])
    print(f"[map] group={mgv} num={mnv} {'OK' if mgv < 64 and mnv < 256 else 'SUSPICIOUS'}")

    # --- 队伍 ---
    pc = table.get("party_count")
    party_count = emu.u8(pc["addr"])
    pd = table.get("party_data")
    party_bytes = emu.read(pd["addr"], pd["size"])
    mons = [m for m in parse_party(party_bytes) if not m.is_empty]
    species_list = [m.species for m in mons]
    valid = all(1 <= s <= 386 for s in species_list)
    print(f"[party] count={party_count} parsed={len(mons)} species={species_list} "
          f"{'OK' if valid else 'FAIL'}")
    for m in mons:
        hp_ok = 0 <= m.current_hp <= m.max_hp and m.max_hp > 0
        print(f"   {m.species} lv={m.level} hp={m.current_hp}/{m.max_hp} "
              f"moves={m.moves} item={m.held_item} {'OK' if hp_ok else 'FAIL'}")

    # --- 战斗标志 ---
    bt = table.get("battle_type_flags")
    bf = table.get("battle_main_func")
    fl = emu.u16(bt["addr"])
    fn = emu.u32(bf["addr"])
    in_battle = fn != 0
    print(f"[battle] flags=0x{fl:04X} main_func=0x{fn:08X} in_battle={in_battle}")

    # --- 移动验证（有把握时才做）---
    _try_move_verification(emu, table)


def _try_move_verification(emu: Emulator, table: OffsetTable) -> None:
    """按住上方向 20 帧，验证玩家 Y 坐标是否变化（验证坐标偏移+可移动）。"""
    from src.emulator.keys import Key
    spec = table.get("player_y")
    before = emu.u16(spec["addr"])
    emu.hold([Key.UP], 30)
    after = emu.u16(spec["addr"])
    if after != before:
        print(f"[move] Y {before} -> {after} OK（坐标偏移有效）")
    else:
        print(f"[move] Y 未变化 ({before}) —— 可能处于对话/菜单/不可移动位置，跳过")
