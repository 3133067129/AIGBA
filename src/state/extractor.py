"""从模拟器内存提取结构化游戏状态（纯内存，无 LLM）。"""
from __future__ import annotations

from dataclasses import dataclass, field

from src.emulator.mgba_core import Emulator
from src.state.offsets import OffsetTable
from src.state.pokemon_decrypt import Pokemon, parse_party


@dataclass
class GameState:
    frame: int = 0
    player_x: int = 0
    player_y: int = 0
    map_group: int = 0
    map_num: int = 0
    in_battle: bool = False
    battle_type_flags: int = 0
    party: list[Pokemon] = field(default_factory=list)
    party_count: int = 0
    money: int = 0
    battle_text: str = ""
    timeline_hash: str = ""

    @property
    def map_key(self) -> str:
        return f"{self.map_group}:{self.map_num}"


def _decode_gbk(data: bytes) -> str:
    """GBK 解码内存中的显示字符串，失败时返回空串。"""
    try:
        text = data.split(b"\xff", 1)[0].split(b"\x00", 1)[0]
        return text.decode("gbk", errors="replace").strip("\x00\xff")
    except Exception:
        return ""


class GameStateExtractor:
    def __init__(self, offsets: OffsetTable | None = None):
        self.offsets = offsets or OffsetTable.load()

    def _read(self, emu: Emulator, name: str) -> int | bytes:
        spec = self.offsets.get(name)
        addr = spec["addr"]
        if spec["type"] == "u8":
            return emu.u8(addr)
        if spec["type"] == "u16":
            return emu.u16(addr)
        if spec["type"] == "u32":
            return emu.u32(addr)
        if spec["type"] == "bytes":
            return emu.read(addr, spec.get("size", 1))
        raise ValueError(f"unknown type: {spec['type']}")

    def extract(self, emu: Emulator) -> GameState:
        s = GameState()
        s.frame = emu.frame_counter

        s.player_x = self._read(emu, "player_x")
        s.player_y = self._read(emu, "player_y")
        s.map_group = self._read(emu, "map_group")
        s.map_num = self._read(emu, "map_num")
        s.party_count = self._read(emu, "party_count")
        s.money = self._read(emu, "money")

        battle_func = self._read(emu, "battle_main_func")
        s.in_battle = battle_func != 0
        s.battle_type_flags = self._read(emu, "battle_type_flags")

        party_bytes = self._read(emu, "party_data")
        if isinstance(party_bytes, bytes):
            s.party = parse_party(party_bytes)
            s.party = [m for m in s.party if not m.is_empty]

        text = self._read(emu, "battle_text_buf")
        if isinstance(text, bytes):
            s.battle_text = _decode_gbk(text)

        s.timeline_hash = self._hash(s)
        return s

    @staticmethod
    def _hash(s: GameState) -> str:
        """位置/战斗/队伍状态的快照哈希，用于卡死检测与去重。"""
        party_sig = tuple((m.species, m.current_hp, m.level, m.status) for m in s.party)
        return f"{s.map_key}:{s.player_x},{s.player_y}:{s.in_battle}:{party_sig}"
