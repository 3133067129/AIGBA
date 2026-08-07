"""checkpoint 管理：savestate + meta JSON，定期与里程碑双轨。

文件：data/checkpoints/<tag>_<n>.state（raw state 字节）
      data/checkpoints/<tag>_<n>.meta.json（时间/地图/徽章/图鉴等摘要）
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from src.emulator.mgba_core import Emulator


class CheckpointManager:
    def __init__(self, checkpoint_dir: str | Path):
        self.dir = Path(checkpoint_dir)
        self.dir.mkdir(parents=True, exist_ok=True)

    def save(self, emu: Emulator, tag: str, meta: dict) -> Path:
        """保存一个 checkpoint，返回 state 文件路径。"""
        n = 0
        while (self.dir / f"{tag}_{n}.state").exists():
            n += 1
        state_path = self.dir / f"{tag}_{n}.state"
        state_path.write_bytes(emu.save_state())
        meta_path = self.dir / f"{tag}_{n}.meta.json"
        meta = {"tag": tag, "saved_at": time.time(), **meta}
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                             encoding="utf-8")
        return state_path

    def milestone(self, emu: Emulator, name: str, meta: dict) -> Path:
        """里程碑存档（每徽章/关键剧情），不覆盖同名。"""
        return self.save(emu, f"milestone_{name}", meta)

    def load_latest(self, emu: Emulator) -> dict | None:
        """加载最新 checkpoint（按修改时间）。返回 meta dict 或 None。"""
        states = sorted(self.dir.glob("*.state"), key=lambda p: p.stat().st_mtime,
                        reverse=True)
        if not states:
            return None
        latest = states[0]
        emu.load_state(latest.read_bytes())
        meta_path = latest.with_suffix(".meta.json")
        if meta_path.exists():
            return json.loads(meta_path.read_text(encoding="utf-8"))
        return {"tag": latest.stem}
