# -*- coding: utf-8 -*-
"""走路段场景分类：录制 108-165s 每帧 vs 3 个参考帧的 diff_ratio。

参考：
  R1 = 录制 95047（起床段 2F 房间）
  R2 = 录制 107047（出门后 0.2s——床边出门后）
  R3 = 录制 151547（走路场景房间——回放 116.1s 的最优匹配）
输出每帧对三者的 diff，分类：<0.2=同场景。
"""
import glob, os, sys
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.perception.screen import diff_ratio

IMG = r"c:\Users\Administrator\Desktop\projects\AIGBA\data\demos\img"
DEMO = "demo_20260807_234704"

def load(t_ms):
    for f in os.listdir(IMG):
        if f.endswith(f"_t{t_ms:07d}.png"):
            return np.asarray(Image.open(os.path.join(IMG, f)).convert("RGB"))
    return None

def dr(a, b, skip=3):
    """跳过顶部 3 行的 diff_ratio（抗顶部白条/窗口边框差异）。"""
    a2 = a[skip:].astype(np.int16)
    b2 = b[skip:].astype(np.int16)
    # 块级 8x8 平均
    h, w = a2.shape[0] // 8 * 8, a2.shape[1] // 8 * 8
    aa = a2[:h].reshape(h // 8, 8, w // 8, 8, 3).mean(axis=(1, 3))
    bb = b2[:h].reshape(h // 8, 8, w // 8, 8, 3).mean(axis=(1, 3))
    return float((np.abs(aa - bb) > 20).mean())

refs = {}
for name, t in [("R1_95s_2F", 95047), ("R2_107s_出门", 107047), ("R3_151s_走路", 151547)]:
    refs[name] = load(t)
    print(f"{name}: 载入 {t}ms {'OK' if refs[name] is not None else 'FAIL'}")

print(f"\n{'t_ms':>8} | {'R1_2F':>6} {'R2_107':>6} {'R3_151':>6} | 最优")
t = 108047
while t <= 165047:
    a = load(t)
    if a is not None:
        d = {n: dr(a, r) for n, r in refs.items()}
        best = min(d, key=d.get)
        # 走路段中段加回放帧对比（116.1s）
        mark = ""
        if t in (151547, 154547):
            mark = " ←回放匹配目标"
        print(f"{t:>8} | {d['R1_95s_2F']:6.2f} {d['R2_107s_出门']:6.2f} {d['R3_151s_走路']:6.2f} | {best}{mark}")
    t += 2000

# 回放帧对比
print("\n=== 回放帧 vs 3 参考 ===")
repdir = r"c:\Users\Administrator\Desktop\projects\AIGBA\data\demos\replay\demo_20260807_234704"
for t in [115084, 115587, 116095, 118168, 120178, 125054]:
    p = os.path.join(repdir, f"t{t:07d}.png")
    if os.path.exists(p):
        a = np.asarray(Image.open(p).convert("RGB"))
        d = {n: dr(a, r) for n, r in refs.items()}
        best = min(d, key=d.get)
        print(f"rp {t:>7} | {d['R1_95s_2F']:6.2f} {d['R2_107s_出门']:6.2f} {d['R3_151s_走路']:6.2f} | {best}")
    else:
        print(f"rp {t}: 帧不存在")
