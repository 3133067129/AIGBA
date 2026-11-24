"""窗口版演示知识提取：快照 diff 分段 + 输入对齐 → 轨迹知识文档。

读 tools/gamepad_demo_recorder.py 录制的 demo（t=毫秒，img=相对路径）：
- 按键时间线（key 事件）→ 阶段类型判定（探索=方向键 / 对话=A 连按 / 转场=大 diff 无按键）
- 快照 diff → 场景变化/转场边界
- save/load 事件（按钮 + 存档文件）→ 里程碑；jump 仅是画面跳变提示，
  不作文档里程碑（2026-08-08 实测：jump 多为对话字幕/走路镜头滚动误报，
  真实读档以 AX5+ 按钮事件为准）

用法：
    python tools/demo_knowledge_window.py <demo.jsonl> [--llm] [--out <path.md>]

--llm：用 qwen2.5vl（Ollama，GPU）对每个阶段的代表画面做场景描述
     （每个阶段一次调用，数秒；不传则只用像素/按键特征）

输出 data/knowledge/demos/<stem>.window.md —— guide agent 学习「示范操作」的素材。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import yaml
from PIL import Image

from src.perception.screen import diff_ratio

DEMO_DIR = ROOT / "data" / "demos"
IMG_DIR = DEMO_DIR / "img"
KNOW_DIR = ROOT / "data" / "knowledge" / "demos"

# 相邻快照 diff 阈值
TRANSITION_DIFF = 0.50   # > 场景切换（转场/菜单开合）
MOTION_DIFF = 0.08       # > 画面有运动（走路/NPC 动画/对话盒开合）
SEG_GAP_MS = 1500        # 同阶段内快照最大间隔（超过则切开，避免跨静默段）
DIR_KEYS = {"UP", "DOWN", "LEFT", "RIGHT"}


def load_images(snap_events: list[dict]) -> dict:
    """t → numpy 图像（缺失的 img 返回 None）。"""
    imgs = {}
    for s in snap_events:
        p = IMG_DIR / s["img"]
        try:
            imgs[s["t"]] = np.asarray(Image.open(p).convert("RGB"), dtype=np.uint8)
        except FileNotFoundError:
            imgs[s["t"]] = None
    return imgs


def build_segments(snaps: list[dict], imgs: dict, keys: list[dict],
                   milestones: list[dict]) -> list[dict]:
    """把快照序列切成阶段（探索/对话/转场/运动/静止）。

    分类依据（方向键优先——走路时镜头滚动也会产生大 diff，先归探索；
    大 diff 无方向时看 A 键：字幕翻页→对话，否则→转场）：
        - 探索：1.5s 内有方向键按下
        - 对话/转场：diff > TRANSITION_DIFF（有/无 A 键）
        - 运动：diff > MOTION_DIFF（NPC/水波等无输入动画）
        - 静止/对话：其余
    之后同类型连续段合并 + 吸收碎片段（<3 帧快照并入相邻段）。
    """
    def classify(i: int, t: int, img, prev_img) -> str:
        d = diff_ratio(prev_img, img) if (img is not None and prev_img is not None) else 0.0
        if any(k["name"] in DIR_KEYS and k["down"]
               for k in keys if abs(k["t"] - t) < SEG_GAP_MS):
            return "探索"
        if d > TRANSITION_DIFF:
            a_pressed = any(k["name"] == "A" and k["down"]
                            for k in keys if abs(k["t"] - t) < 1000)
            return "对话" if a_pressed else "转场"
        if d > MOTION_DIFF:
            return "运动"
        return "静止/对话"

    segments = []
    for i, s in enumerate(snaps):
        t = s["t"]
        prev_img = imgs.get(snaps[i - 1]["t"]) if i > 0 else None
        seg_type = classify(i, t, imgs.get(t), prev_img)
        new_seg = (not segments or
                   segments[-1]["type"] != seg_type or
                   t - segments[-1]["t_end"] > SEG_GAP_MS)
        if new_seg:
            segments.append({"type": seg_type, "t0": t, "t_end": t,
                             "snaps": [s], "milestones": []})
        else:
            segments[-1]["t_end"] = t
            segments[-1]["snaps"].append(s)
    # 吸收碎片段：<3 帧快照且时长不足 1.5s 的并入相邻段
    # （优先并给同类型邻居，否则并入前一段，避免文档里一堆一帧"转场"）
    out = []
    i = 0
    while i < len(segments):
        seg = segments[i]
        if (len(seg["snaps"]) < 3 and len(segments) > 1
                and seg["t_end"] - seg["t0"] < 1500):
            prev = out[-1] if out else None
            nxt = segments[i + 1] if i + 1 < len(segments) else None
            target = None
            if prev and prev["type"] == seg["type"]:
                target = prev
            elif nxt and nxt["type"] == seg["type"]:
                target = nxt
            elif prev:
                target = prev
            else:
                target = nxt
            target["snaps"].extend(seg["snaps"])
            target["snaps"].sort(key=lambda x: x["t"])
            target["t0"] = min(target["t0"], seg["t0"])
            target["t_end"] = max(target["t_end"], seg["t_end"])
            target["milestones"].extend(seg["milestones"])
        else:
            out.append(seg)
        i += 1
    # 里程碑归属
    for m in milestones:
        for seg in out:
            if seg["t0"] <= m["t"] <= seg["t_end"]:
                seg["milestones"].append(m)
                break
    return out


def keys_in_window(keys: list[dict], t0: int, t1: int) -> Counter:
    """时间段内按键统计（down 事件）。"""
    c = Counter()
    for k in keys:
        if t0 - 200 <= k["t"] <= t1 + 200 and k["down"]:
            c[k["name"]] += 1
    return c


def main() -> int:
    ap = argparse.ArgumentParser(description="窗口版演示知识提取")
    ap.add_argument("demo", help="demo jsonl 文件名或路径")
    ap.add_argument("--llm", action="store_true", help="用 qwen 描述各阶段画面")
    ap.add_argument("--out", default=None, help="输出 md 路径")
    args = ap.parse_args()

    demo_path = DEMO_DIR / args.demo if not Path(args.demo).exists() else Path(args.demo)
    assert demo_path.exists(), f"demo 不存在: {demo_path}"

    events = [json.loads(l) for l in open(demo_path, encoding="utf-8") if l.strip()]
    boot = events[0]
    keys = [e for e in events if e["ev"] == "key"]
    snaps = [e for e in events if e["ev"] == "snap"]
    milestones = [e for e in events if e["ev"] in ("save", "load")]
    imgs = load_images(snaps)

    segments = build_segments(snaps, imgs, keys, milestones)
    press_count = Counter(k["name"] for k in keys if k["down"])

    # ---- 阶段 LLM 描述（可选）----
    llm_desc: dict[int, str] = {}
    if args.llm and segments:
        import src.perception.llm_vision as lv
        provider = lv.make_provider(yaml.safe_load(
            open(ROOT / "config" / "settings.yaml", encoding="utf-8"))["llm"])
        print("LLM 描述阶段画面（GPU）...")
        t0_llm = time.time()
        for seg in segments:
            rep = seg["snaps"][len(seg["snaps"]) // 2]
            img = imgs.get(rep["t"])
            if img is None:
                continue
            try:
                desc = provider.describe(
                    [img],
                    "这是宝可梦绿宝石386（中文汉化）的游戏画面。"
                    "用一句话描述当前场景：在室内还是室外、有无对话/菜单、"
                    "画面里有什么关键元素（人物/门/钟/宝可梦等）。")
                llm_desc[seg["t0"]] = desc.strip()
                print(f"  t={seg['t0']}ms [{seg['type']}]: {desc[:60]}...")
            except Exception as e:
                print(f"  t={seg['t0']}ms LLM 失败: {e}")
        print(f"LLM 完成，耗时 {time.time() - t0_llm:.0f}s")

    # ---- 输出 ----
    out = args.out or (KNOW_DIR / (demo_path.stem + ".window.md"))
    out.parent.mkdir(parents=True, exist_ok=True)

    L = []
    L.append(f"# 窗口版演示轨迹：{demo_path.stem}")
    L.append("")
    L.append(f"- 手柄: {boot.get('gamepad', '?')} | 映射: {boot.get('mapping', '?')}")
    L.append(f"- 创建: {boot.get('created', '?')}")
    dur_ms = events[-1]["t"] if events else 0
    L.append(f"- 时长: {dur_ms / 1000:.1f}s | 按键 {len(keys)} 次 | 快照 {len(snaps)} 张"
             f" | 里程碑 {len(milestones)} 个")
    L.append("")

    if milestones:
        L.append("## 里程碑（存档/读档）")
        for m in milestones:
            extra = m.get("file") or m.get("btn") or m.get("diff", "")
            L.append(f"- t={m['t']}ms [{m['ev']}] {extra}")
        L.append("")

    if segments:
        L.append("## 阶段（%d 段）" % len(segments))
        L.append("")
        for i, seg in enumerate(segments):
            n = len(seg["snaps"])
            ms = seg["milestones"]
            L.append(f"### {i}. [{seg['type']}] t={seg['t0']}–{seg['t_end']}ms"
                     f"（{n} 帧快照）")
            if ms:
                L.append("  - 🏷 " + "、".join(
                    f"[{m['ev']}]@{m['t']}ms" for m in ms))
            if seg["t0"] in llm_desc:
                L.append(f"  - 画面: {llm_desc[seg['t0']]}")
            c = keys_in_window(keys, seg["t0"], seg["t_end"])
            if c:
                L.append("  - 按键: " + "、".join(
                    f"{k}×{v}" for k, v in c.most_common(8)))
            rep = seg["snaps"][n // 2]["img"]
            L.append(f"  - 代表图: img/{rep}")
        L.append("")

    if press_count:
        L.append("## 按键统计")
        L.append("、".join(f"{k}×{v}" for k, v in press_count.most_common()))
        L.append("")

    # 完整操作序列（压缩：连续同键只记首末）
    if keys:
        L.append("## 操作序列（压缩）")
        ops = []
        prev_label, prev_down, prev_t = None, None, 0
        for k in keys:
            if k["name"] == prev_label and k["down"] == prev_down:
                continue
            if prev_label is not None:
                ops.append(f"{prev_t}ms:{prev_label}{'↓' if prev_down else '↑'}")
            prev_label, prev_down, prev_t = k["name"], k["down"], k["t"]
        if prev_label is not None:
            ops.append(f"{prev_t}ms:{prev_label}{'↓' if prev_down else '↑'}")
        L.append("`" + " ".join(ops) + "`")
        L.append("")

    out.write_text("\n".join(L), encoding="utf-8")
    print(f"知识已写入: {out}")
    print(f"  {len(segments)} 段 | 按键 {len(keys)} 次 | 里程碑 {len(milestones)} 个")
    return 0


if __name__ == "__main__":
    sys.exit(main())
