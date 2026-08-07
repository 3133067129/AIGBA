"""演示知识提取：人工演示轨迹 → 人类/AI 可读的知识文档。

用法：
    python tools/demo_knowledge.py <demo.jsonl> [--out <path.md>]

输出（data/knowledge/demos/<name>.md）：
- 路径概要：坐标序列压缩 + 显著 warp（坐标跳变）/ 界面开合（bright 跳变）
- 按键统计 + 完整操作序列串（按帧排序，可复制为 AI 的示范 skill）
- note 锚点片段：每个标签前后 N 帧的按键窗口（解锁/剧情等关键时刻的操作）
- 坐标可达域：演示覆盖的格子集（地图结构学习）

guide agent 可在需要「示范操作」时引用这些文档。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEMO_DIR = ROOT / "data" / "demos"
KNOW_DIR = ROOT / "data" / "knowledge" / "demos"

WARP_TOL = 128    # 坐标跳变 > 128px 视为传送/warp
BRIGHT_TOL = 50   # bright 跳变 > 50 视为界面开合
WINDOW = 120      # note 前后按键窗口（帧）


def main():
    ap = argparse.ArgumentParser(description="演示知识提取")
    ap.add_argument("demo", help="demo jsonl 文件名或路径")
    ap.add_argument("--out", default=None, help="输出 md 路径")
    ap.add_argument("--window", type=int, default=WINDOW)
    args = ap.parse_args()

    demo_path = DEMO_DIR / args.demo if not Path(args.demo).exists() else Path(args.demo)
    assert demo_path.exists(), f"demo 不存在: {demo_path}"

    events = [json.loads(l) for l in open(demo_path, encoding="utf-8") if l.strip()]
    boot = events[0]

    # ---- 重建按键时间线：keys 事件 → (帧, down集) ----
    key_events = []   # (frame, added:set, removed:set)
    prev = set()
    for ev in events[1:]:
        if ev["ev"] == "keys":
            cur = set(ev["down"])
            if cur != prev:
                key_events.append((ev["t"], cur - prev, prev - cur))
                prev = cur

    # ---- 坐标轨迹 + 事件流 ----
    snaps = [ev for ev in events if ev["ev"] == "snap"]
    notes = [ev for ev in events if ev["ev"] == "note"]

    cells = set()
    path = []          # [(frame, x, y)]
    flow = []          # 显著事件描述
    last_x = last_y = None
    last_b = None
    for s in snaps:
        x, y, b = s["x"], s["y"], s["b"]
        cells.add((x // 16, y // 16))
        if last_x is not None:
            if abs(x - last_x) > WARP_TOL or abs(y - last_y) > WARP_TOL:
                flow.append(f"t={s['t']} ⚡传送: ({last_x},{last_y}) → ({x},{y})")
            elif (x, y) != (last_x, last_y):
                path.append((s["t"], x, y))
        if last_b is not None and abs(b - last_b) > BRIGHT_TOL:
            kind = "界面开" if b > last_b else "界面关"
            flow.append(f"t={s['t']} {kind}: bright {last_b:.0f} → {b:.0f}")
        last_x, last_y, last_b = x, y, b

    # ---- 按键统计 + 操作序列 ----
    press_count = Counter()
    ops = []           # [(frame, op_string)]
    for t, added, removed in key_events:
        for k in sorted(added):
            press_count[k] += 1
            ops.append((t, f"+{k}"))
        for k in sorted(removed):
            ops.append((t, f"-{k}"))

    # ---- 输出 ----
    out = args.out or (KNOW_DIR / (demo_path.stem + ".md"))
    out.parent.mkdir(parents=True, exist_ok=True)

    L = []
    L.append(f"# 演示轨迹：{demo_path.stem}")
    L.append("")
    L.append(f"- 模式: {boot['mode']} | 起点: {boot.get('state', '冷启动')}")
    L.append(f"- 创建: {boot.get('created', '?')}")
    L.append(f"- 总帧数: {events[-1]['t'] if events else 0}"
             f" | 按键次数: {sum(press_count.values())}"
             f" | 覆盖格子: {len(cells)}")
    L.append("")

    if notes:
        L.append("## 关键标签")
        for n in notes:
            L.append(f"- {n['tag']} @ t={n['t']}  img={n.get('img', '-')}")
        L.append("")

    if flow:
        L.append("## 显著事件流")
        L.extend(f"- {x}" for x in flow)
        L.append("")

    if path:
        L.append(f"## 路径（{len(path)} 个移动点）")
        seg = []
        for t, x, y in path:
            seg.append(f"({x},{y})")
        L.append("→ ".join(seg))
        L.append("")

    if press_count:
        L.append("## 按键统计")
        L.append("、".join(f"{k}×{v}" for k, v in press_count.most_common()))
        L.append("")

    if notes:
        L.append(f"## 标签前后按键窗口（±{args.window} 帧）")
        for n in notes:
            t0 = n["t"]
            win = [op for (t, op) in ops if abs(t - t0) <= args.window]
            if win:
                L.append(f"\n### {n['tag']} @ t={t0}")
                L.append("`" + " ".join(f"{t}:{op}" for t, op in win) + "`")
        L.append("")

    if ops:
        L.append("## 完整操作序列")
        L.append("`" + " ".join(f"{t}:{op}" for t, op in ops) + "`")
        L.append("")

    out.write_text("\n".join(L), encoding="utf-8")
    print(f"知识已写入: {out}")
    print(f"  覆盖 {len(cells)} 格 | 按键 {sum(press_count.values())} 次 | "
          f"事件 {len(flow)} 条 | 标签 {len(notes)} 个")


if __name__ == "__main__":
    main()
