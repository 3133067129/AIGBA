"""ROM/存档头部检查工具。

用法: python tools/check_rom.py [rom_path [sav_path]]
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def check_rom(path: Path) -> dict:
    with open(path, "rb") as f:
        header = f.read(0xC0)
    return {
        "title": header[0xA0:0xAC].decode("ascii", "replace").strip("\x00 "),
        "game_code": header[0xAC:0xB0].decode("ascii", "replace").strip("\x00 "),
        "maker": header[0xB0:0xB2].hex(),
        "size": path.stat().st_size,
    }


def check_sav(path: Path) -> dict:
    data = path.read_bytes()
    return {
        "size": len(data),
        "tail_hex": data[-16:].hex(),
        "head_hex": data[:16].hex(),
        "looks_vba_footer": data[-16:] == b"\xff" * 16,
    }


def main() -> None:
    import yaml
    cfg = yaml.safe_load((ROOT / "config" / "settings.yaml").read_text(encoding="utf-8"))
    rom = ROOT / cfg["rom"]["path"]
    print("ROM:", check_rom(rom))
    sav = ROOT / cfg["rom"]["sav"]
    print("SAV:", check_sav(sav))


if __name__ == "__main__":
    main()
