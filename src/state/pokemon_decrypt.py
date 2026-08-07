"""绿宝石（Gen3）宝可梦数据解密与解析。

数据结构（零售版 Emerald，来自 pret/pokeemerald）：
- 队伍槽 100 字节；data 区在 +0x20，48 字节 = 4 个子块 × 12 字节
- data 区整体与 key = personality ^ otId 逐 u32 异或加密
- 4 个子块的物理排列由 personality % 24 决定（sSubOrder 置换表）
- 子块类型：0=Growth(species/道具/经验) 1=Attacks(技能) 2=EVs 3=Misc(个体值等)
- 未加密字段：等级 +0x54、当前HP u16 +0x56、最大HP u16 +0x58（RetroKix 实测）
  注：status 字段在队伍槽中的位置待实证标定，暂不解析

物理位置语义（已用真实 .sav 数据实证：5/5 技能合法 + 4/5 物种合法）：
    order = sub_order[personality % 24]
    物理位置 i 存放的子块类型 = order[i]        （即类型 t 位于 order.index(t)）
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

PARTY_SLOT_SIZE = 100
DATA_OFFSET = 0x20
SUBBLOCK_SIZE = 12
NUM_SUBBLOCKS = 4

# 24 种排列：sub_order[p][t] = 类型 t 的物理子块下标
SUB_ORDER: tuple[tuple[int, int, int, int], ...] = (
    (0, 1, 2, 3), (0, 1, 3, 2), (0, 2, 1, 3), (0, 2, 3, 1), (0, 3, 1, 2), (0, 3, 2, 1),
    (1, 0, 2, 3), (1, 0, 3, 2), (1, 2, 0, 3), (1, 2, 3, 0), (1, 3, 0, 2), (1, 3, 2, 0),
    (2, 0, 1, 3), (2, 0, 3, 1), (2, 1, 0, 3), (2, 1, 3, 0), (2, 3, 0, 1), (2, 3, 1, 0),
    (3, 0, 1, 2), (3, 0, 2, 1), (3, 1, 0, 2), (3, 1, 2, 0), (3, 2, 0, 1), (3, 2, 1, 0),
)

# 子块类型
SUB_GROWTH, SUB_ATTACKS, SUB_EVS, SUB_MISC = 0, 1, 2, 3


@dataclass
class Pokemon:
    personality: int = 0
    ot_id: int = 0
    species: int = 0
    held_item: int = 0
    level: int = 0
    current_hp: int = 0
    max_hp: int = 0
    experience: int = 0
    moves: list[int] = field(default_factory=lambda: [0, 0, 0, 0])
    pps: list[int] = field(default_factory=lambda: [0, 0, 0, 0])
    status: int = 0
    # 原始 100 字节（调试/校验用）
    raw: bytes = b""

    @property
    def is_empty(self) -> bool:
        return self.personality == 0 or self.species == 0

    @property
    def is_fainted(self) -> bool:
        return self.current_hp == 0

    @property
    def hp_ratio(self) -> float:
        if self.max_hp <= 0:
            return 0.0
        return self.current_hp / self.max_hp


def decrypt_data(data: bytes, key: int) -> bytes:
    """对 48 字节 data 区逐 u32 异或解密。"""
    out = bytearray(data)
    for i in range(0, 48, 4):
        v = struct.unpack_from("<I", out, i)[0]
        struct.pack_into("<I", out, i, v ^ key)
    return bytes(out)


def parse_pokemon(raw: bytes) -> Pokemon:
    """解析一个 100 字节队伍槽。raw 必须是长度 >= 100 的字节串。"""
    if len(raw) < PARTY_SLOT_SIZE:
        raise ValueError(f"party slot too short: {len(raw)}")

    personality = struct.unpack_from("<I", raw, 0x00)[0]
    ot_id = struct.unpack_from("<I", raw, 0x04)[0]

    p = Pokemon(personality=personality, ot_id=ot_id, raw=bytes(raw[:PARTY_SLOT_SIZE]))

    if personality == 0:
        return p  # 空槽

    key = personality ^ ot_id
    data = decrypt_data(raw[DATA_OFFSET:DATA_OFFSET + 48], key)

    order = SUB_ORDER[personality % 24]
    # 实证语义：物理位置 i 存放子块类型 order[i]；类型 t 在物理位置 order.index(t)
    phys = {t: order.index(t) for t in range(NUM_SUBBLOCKS)}
    growth = data[phys[SUB_GROWTH] * 12: phys[SUB_GROWTH] * 12 + 12]
    attacks = data[phys[SUB_ATTACKS] * 12: phys[SUB_ATTACKS] * 12 + 12]
    misc = data[phys[SUB_MISC] * 12: phys[SUB_MISC] * 12 + 12]

    p.species = struct.unpack_from("<H", growth, 0x00)[0]
    p.held_item = struct.unpack_from("<H", growth, 0x02)[0]
    p.experience = struct.unpack_from("<I", growth, 0x04)[0]

    p.moves = list(struct.unpack_from("<4H", attacks, 0x00))
    p.pps = list(struct.unpack_from("<4B", attacks, 0x08))

    # Misc 子块: pokerus@0, metLocation@1, origins@2, ivs@4(u32), ribbons@8
    # status 字段位置待实证标定（见 state/verify_offsets.py），暂不解析

    p.level = raw[0x54]
    p.current_hp = struct.unpack_from("<H", raw, 0x56)[0]
    p.max_hp = struct.unpack_from("<H", raw, 0x58)[0]
    p.status = 0  # TODO: 实证标定 status 偏移后填充

    return p


def parse_party(party_bytes: bytes) -> list[Pokemon]:
    """解析 6 槽队伍数据（600 字节）。"""
    mons = []
    for i in range(6):
        slot = party_bytes[i * PARTY_SLOT_SIZE: (i + 1) * PARTY_SLOT_SIZE]
        mons.append(parse_pokemon(slot))
    return mons
