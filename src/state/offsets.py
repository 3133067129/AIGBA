"""内存偏移表加载与校验。

所有提取器只从 offsets.json 读地址，不硬编码。
零售版 Emerald (BPEE) 的高置信偏移作为初始值；
verify_offsets.py 会对 386 hack 重新标定并覆写本文件。
"""
from __future__ import annotations

import json
from pathlib import Path

CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"
OFFSETS_FILE = CONFIG_DIR / "offsets.json"

# 零售版 Emerald 初始偏移（相对 EWRAM 0x02000000 或 IWRAM 0x03000000 的区域偏移）
DEFAULT_OFFSETS: dict = {
    "player_x": {"addr": 0x02025A08, "type": "u16"},
    "player_y": {"addr": 0x02025A0A, "type": "u16"},
    "map_group": {"addr": 0x02025A0C, "type": "u8"},
    "map_num": {"addr": 0x02025A0D, "type": "u8"},
    "party_count": {"addr": 0x020244E9, "type": "u8"},
    "party_data": {"addr": 0x020244EC, "type": "bytes", "size": 600},
    "enemy_party_data": {"addr": 0x02024744, "type": "bytes", "size": 600},
    "battle_type_flags": {"addr": 0x02022FEC, "type": "u16"},
    "battle_main_func": {"addr": 0x03005D04, "type": "u32"},  # IWRAM
    "battle_text_buf": {"addr": 0x02022E2C, "type": "bytes", "size": 100},  # GBK
    "money": {"addr": 0x02025A18, "type": "u32"},
    # 图鉴位图（SB2 区域）——待标定，占位
    "dex_seen_bitmap": {"addr": 0x0202C044, "type": "bytes", "size": 96},   # 待验证
    "dex_owned_bitmap": {"addr": 0x0202C010, "type": "bytes", "size": 96},  # 待验证
}


class OffsetTable:
    def __init__(self, data: dict | None = None):
        self.data = data or dict(DEFAULT_OFFSETS)

    @classmethod
    def load(cls, path: Path | None = None) -> "OffsetTable":
        path = path or OFFSETS_FILE
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return cls(json.load(f))
        return cls()

    def save(self, path: Path | None = None) -> None:
        path = path or OFFSETS_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def get(self, name: str) -> dict:
        if name not in self.data:
            raise KeyError(f"offset not defined: {name}")
        return self.data[name]

    def __contains__(self, name: str) -> bool:
        return name in self.data
