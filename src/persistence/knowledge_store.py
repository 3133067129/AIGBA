"""长期知识持久化：地图图 / 遭遇表 / NPC 笔记 / 任务清单。

全部 JSON 原子写入（先写临时文件再 rename），防崩溃损坏。
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def _atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


class KnowledgeStore:
    def __init__(self, knowledge_dir: str | Path):
        self.dir = Path(knowledge_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.map_graph: dict = self._load("map_graph.json", {"nodes": {}, "edges": []})
        self.encounter_table: dict = self._load("encounter_table.json", {})
        self.npc_notes: dict = self._load("npc_notes.json", {})
        self.checklist: dict = self._load("checklist.json", {"items": []})

    def _load(self, name: str, default: dict) -> dict:
        path = self.dir / name
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return default
        return default

    def _save(self, name: str, data: dict) -> None:
        _atomic_write(self.dir / name, data)

    def save_all(self) -> None:
        self._save("map_graph.json", self.map_graph)
        self._save("encounter_table.json", self.encounter_table)
        self._save("npc_notes.json", self.npc_notes)
        self._save("checklist.json", self.checklist)

    # --- 遭遇表 ---
    def record_encounter(self, map_key: str, species: int, context: str) -> bool:
        """记录 (地图, 物种, 遭遇方式)。返回是否为新记录。"""
        key = f"{map_key}|{species}"
        existing = self.encounter_table.get(key)
        if existing:
            if context not in existing.get("contexts", []):
                existing.setdefault("contexts", []).append(context)
            existing["count"] = existing.get("count", 0) + 1
            return False
        self.encounter_table[key] = {
            "map": map_key, "species": species, "contexts": [context], "count": 1,
        }
        return True

    def species_by_map(self, map_key: str) -> list[int]:
        return sorted({v["species"] for k, v in self.encounter_table.items()
                       if v["map"] == map_key})

    # --- 地图图 ---
    def add_map_node(self, map_key: str, name: str = "") -> None:
        if map_key not in self.map_graph["nodes"]:
            self.map_graph["nodes"][map_key] = {"name": name}

    def add_warp_edge(self, map_a: str, map_b: str) -> None:
        """记录两个地图间存在可通行边（通过传送点移动发现）。"""
        if map_a == map_b:
            return
        for e in self.map_graph["edges"]:
            if {e["a"], e["b"]} == {map_a, map_b}:
                return
        self.map_graph["edges"].append({"a": map_a, "b": map_b})
