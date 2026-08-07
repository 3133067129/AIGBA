"""运行指标：JSONL 追加写入。"""
from __future__ import annotations

import json
from pathlib import Path


class Metrics:
    def __init__(self, log_dir: str | Path):
        self.path = Path(log_dir) / "metrics.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, **fields) -> None:
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(fields, ensure_ascii=False) + "\n")
