"""队伍解密单测。

不依赖模拟器：构造已知数据验证解密正确性 + 非法数据应产生无效结果。
真实存档的端到端验证在 smoke 测试里做（需要 mgba 加载存档）。
"""
import struct

import pytest

from src.state.pokemon_decrypt import SUB_ORDER, decrypt_data, parse_party, parse_pokemon


def build_party_slot(personality: int, ot_id: int, species: int, level: int,
                     hp: int, move1: int = 0) -> bytes:
    """手工构造一个 100 字节队伍槽（按零售版布局加密）。"""
    raw = bytearray(100)
    struct.pack_into("<I", raw, 0x00, personality)
    struct.pack_into("<I", raw, 0x04, ot_id)
    raw[0x54] = level
    struct.pack_into("<H", raw, 0x56, hp)
    struct.pack_into("<H", raw, 0x58, hp)

    key = personality ^ ot_id
    order = SUB_ORDER[personality % 24]
    growth = bytearray(12)
    struct.pack_into("<H", growth, 0x00, species)
    attacks = bytearray(12)
    struct.pack_into("<H", attacks, 0x00, move1)
    evs = bytearray(12)
    misc = bytearray(12)
    subblocks = [growth, attacks, evs, misc]
    data = bytearray(48)
    for i, sub in enumerate(subblocks):
        data[i * 12:(i + 1) * 12] = sub
    # 按置换打乱物理排列：物理位置 i 存放类型 order[i]
    shuffled = bytearray(48)
    for i, t in enumerate(order):
        shuffled[i * 12:(i + 1) * 12] = data[t * 12:(t + 1) * 12]
    encrypted = bytearray(48)
    for i in range(0, 48, 4):
        v = struct.unpack_from("<I", shuffled, i)[0]
        struct.pack_into("<I", encrypted, i, v ^ key)
    raw[0x20:0x20 + 48] = encrypted
    return bytes(raw)


def test_decrypt_roundtrip():
    """解密是 XOR 的逆操作。"""
    key = 0xDEADBEEF
    data = bytes(range(48))
    assert decrypt_data(decrypt_data(data, key), key) == data


@pytest.mark.parametrize("personality", [1, 5, 23, 24, 100])
def test_parse_pokemon_known_fields(personality):
    raw = build_party_slot(personality, 0x12345678, 25, 5, 30, move1=33)  # 皮卡丘 lv5
    p = parse_pokemon(raw)
    assert p.species == 25
    assert p.level == 5
    assert p.current_hp == p.max_hp == 30
    assert p.moves[0] == 33
    assert not p.is_empty


def test_parse_pokemon_empty_slot():
    p = parse_pokemon(bytes(100))
    assert p.is_empty
    assert p.species == 0


def test_parse_party_six_slots():
    slots = [build_party_slot(100 + i, 0x11111111, 1 + i, 10, 50) for i in range(6)]
    party = parse_party(b"".join(slots))
    assert len(party) == 6
    assert [m.species for m in party] == [1, 2, 3, 4, 5, 6]


def test_sub_order_is_valid_permutation():
    for row in SUB_ORDER:
        assert sorted(row) == [0, 1, 2, 3]
    assert len(SUB_ORDER) == 24
