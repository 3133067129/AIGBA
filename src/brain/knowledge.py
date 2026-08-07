"""长期知识访问封装：地图图 / 任务清单（Phase 1 子集）。"""
from __future__ import annotations

from src.persistence.knowledge_store import KnowledgeStore


class Knowledge:
    def __init__(self, store: KnowledgeStore):
        self.store = store

    # --- 地图图 ---
    def add_map(self, map_key: str, scene: str = "") -> None:
        self.store.add_map_node(map_key, name=scene)

    def add_warp(self, map_a: str, map_b: str) -> None:
        self.store.add_warp_edge(map_a, map_b)

    def known_maps(self) -> list[str]:
        return sorted(self.store.map_graph["nodes"].keys())

    # --- 对话/事件计数（供目标追踪）---
    def bump_counter(self, name: str) -> int:
        items = self.store.checklist.setdefault("counters", {})
        items[name] = items.get(name, 0) + 1
        self.store._save("checklist.json", self.store.checklist)
        return items[name]

    def get_counter(self, name: str) -> int:
        return self.store.checklist.setdefault("counters", {}).get(name, 0)

    def mark_goal(self, name: str) -> None:
        items = self.store.checklist.setdefault("goals", {})
        items[name] = True
        self.store._save("checklist.json", self.store.checklist)

    def goal_done(self, name: str) -> bool:
        return self.store.checklist.setdefault("goals", {}).get(name, False)
