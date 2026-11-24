"""定位回放帧画面对应录制哪个时刻（全谱最优匹配 + 同刻对比）。

round-20 走路段帧锚定疑团：F_dlg1=6845 帧 vs 录制弹出帧预期 5340，差 ~1500 帧。
对比回放帧与录制全部快照，找最优匹配 t_m + 与「同刻录制帧」的 diff，判断回放
画面时间轴 vs 录制时间轴的关系（整体偏移多少、走路段是否分叉）。
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.perception.screen import diff_ratio  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
REPLAY_DIR = ROOT / "data/demos/replay/demo_20260807_234704"
DEMO = ROOT / "data/demos/demo_20260807_234704.jsonl"
IMG_DIR = ROOT / "data/demos/img"

# 要分析的回放帧（墙钟 abs）：玩家移动段 111s + 走路段 119.6s
rp_frames = [int(x) for x in sys.argv[1:]] or [110973, 119585]

events = [json.loads(l) for l in open(DEMO, encoding="utf-8") if l.strip()]
rec_evs = [e for e in events if e["ev"] == "snap"]
rec = {s["t"]: np.asarray(Image.open(IMG_DIR / s["img"]).convert("RGB"))
       for s in rec_evs}
rec_ts = sorted(rec)
print(f"录制快照 {len(rec_ts)} 张（{rec_ts[0]}..{rec_ts[-1]}ms）")

from bisect import bisect_left, bisect_right  # noqa: E402

for tr in rp_frames:
    p = REPLAY_DIR / f"t{tr:07d}.png"
    if not p.exists():
        print(f"\n=== 回放 t{tr} 不存在")
        continue
    img = np.asarray(Image.open(p).convert("RGB"))
    # 全谱：录制全部快照最优匹配
    best = min((diff_ratio(img, rec[t]), t) for t in rec_ts)
    # 同刻：±0.5s 内匹配
    lo = bisect_left(rec_ts, tr - 500)
    hi = bisect_right(rec_ts, tr + 500)
    same = min((diff_ratio(img, rec[rec_ts[i]]), rec_ts[i])
               for i in range(lo, hi)) if lo < hi else (None, None)
    print(f"\n=== 回放 t{tr}（墙钟 {tr/1000:.1f}s）")
    print(f"  全谱最优: 录制 t{best[1]}（{best[1]/1000:.1f}s）diff={best[0]:.3f}"
          f"（漂移 {best[1]-tr:+d}ms）")
    print(f"  同刻±0.5s: {('录制 t%d diff=%.3f' % (same[1], same[0])) if same[0] is not None else '无快照'}")
