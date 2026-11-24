"""窗口回放 + 录制质量验证。

回放：把录制的示范按键用 SendInput 按原时间轴发到 mGBA 窗口（真实时间轴）。
验证：--verify 时按录制同节奏抓屏（500ms/张），结束后与录制快照对比——
      每张回放快照在录制时间线 ±5s 内找最相似快照，统计最优 diff 分布：
      - 对齐：中位 diff < 0.20 且发散帧（>0.55）< 10% → 回放与录制一致，录制质量可靠
      - 发散：大量 >0.55 的帧 → 回放中途与录制分叉（输入丢失/时序漂移/起点不同）
      报告存 data/demos/replay/<stem>/report.txt。

用法：
    python tools/replay_demo_window.py <demo.jsonl> --launch --verify   # 全段回放+验证
    python tools/replay_demo_window.py <demo.jsonl> --to 60             # 只回放前 60s（肉眼检查）
    python tools/replay_demo_window.py <demo.jsonl>                     # 挂已开的 mGBA 窗口回放
    python tools/replay_demo_window.py <demo.jsonl> --launch --walk-lua # 走路段 Lua 帧级调度（根治分叉）
    python tools/replay_demo_window.py <demo.jsonl> --launch --probe-walk  # 走路段探针（诊断）

注意：
- 按键走 PostMessage 直发 mGBA 窗口（本机火绒 HIPS 拦 SendInput，2026-08-08 实测
  全部 0/87 失败）；仍建议回放期间别动电脑（会周期重置前台焦点）
- 存档/读档/跳变事件跳过（PostMessage 触发不了手柄键）；本 demo 无读档，
  从 mGBA 冷启动回放即可确定性复现
- --verify 需要 --launch（回放起点必须与录制起点一致：都从冷启动开始）
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from bisect import bisect_left, bisect_right
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import subprocess

import numpy as np
import yaml
from PIL import Image

from src.emulator import window_backend
from src.emulator.keys import Key
from src.perception.screen import diff_ratio

DEMO_DIR = ROOT / "data" / "demos"
IMG_DIR = DEMO_DIR / "img"
REPLAY_DIR = DEMO_DIR / "replay"

cfg = yaml.safe_load(open(ROOT / "config" / "settings.yaml", encoding="utf-8"))
ROM_PATH = str((ROOT / cfg["rom"]["path"]).resolve())
ROM_NAME = Path(ROM_PATH).name
MGBA_EXE = ROOT / "mGBA.exe"

SKIP_EVENTS = {"save", "load", "jump"}
CAP_INTERVAL_MS = 500
# v10.3（round-20）：匹配窗口 5000 → 15000——起床段帧表时代回放墙钟 = 帧轴
# + 键盘屏段 Lua 注入冻结累计（实测 ~9.1s：round-19 弹出确认 98.1s 墙钟 =
# 录制 89.0s 帧轴）。走路段快照（帧名 = 墙钟）相对录制帧轴恒偏移冻结累计
# （>5s）→ 旧窗口走路段全谱匹配必失败。±15s 覆盖冻结累计波动；走路段场景
# 唯一性强（走廊/楼梯口/卧室各有特征），误配风险可控。判定后需复核报告
# 「时间漂移」的连续性：整体平移对齐（drift 恒 ≈ −9000）≠ 分叉（drift 漂移）。
MATCH_WINDOW_MS = 15000     # 回放快照与录制快照的匹配窗口（吸收冻结累计/时序漂移）
ALIGNED_DIFF = 0.25         # 最优 diff 低于 = 对齐帧
DIVERGED_DIFF = 0.55        # 最优 diff 高于 = 发散帧
VERDICT_MED_MAX = 0.20      # 中位 diff 上限
VERDICT_DIV_MAX = 0.10      # 发散帧占比上限

# 方向键短点按补偿（2026-08-08 窗口回放实证定标 v3）
# 关键事实（窗口录制快照 + 回放快照对比）：
# - 44.5-47.5s 是对话屏（A 键连按推进），48.5s 才是命名键盘屏（亮度 150）
# - 录制键盘屏：LEFT 拨动(170ms)/DOWN 拨动(125ms) 后光标纹丝不动
#   （rec 48.547→49.547 红区恒定 (57-60,69-72)）→ 轴拨动有效按住 <150ms = 0 格
#   → finalA 选中初始光标（字母 A）→ 转场
# - 键盘 PostMessage 170ms 按住 = 1 格（绿宝石菜单按住 ~150ms 滚 1 格）
#   → 回放 1:1 光标偏 1 格 → finalA 落空卡命名屏幕
# - headless「DOWN 352ms = 2 格」测的是键盘行为，不是录制轴行为——拉伸方向错误
# 修复：命名界面段（45-51s）方向键短点按缩短到 100ms（0 格），复刻录制轴行为。
# 50s 后段落暂不处理（全段验证后按发散分布定规则）。
SHORTEN_ZONE_MS = (45000, 51000)   # 命名界面段（键盘屏 48.3-50.5s + 前后余量）
SHORTEN_HOLD_MS = 100              # 缩短目标（<150ms = 0 格，等效录制轴拨动）
SHORTEN_MAX_MS = 300               # 仅 <300ms 的短点按
DIR_KEYS = {"UP", "DOWN", "LEFT", "RIGHT"}

# 键盘屏段 Lua 注入（2026-08-08 实证）
# 背景：键盘屏（命名界面）期间 mGBA 的 Qt 焦点对象偏离 Window/Display，PostMessage
# 键盘消息全部无效（A/B/方向/START/SELECT 逐键探针均无反应，消息到达窗口过程但
# 未变成 GBA 输入）。对话屏 PostMessage A 有效（决定性测试：停住 4s 画面恒定 mean=94.3，
# 单次 PostMessage A → 82.6 推进）。
# 修复：键盘屏段改用 mGBA「脚本」控制台（Tools→脚本... 菜单第 4 项，客户区 y=81，
# 物理鼠标点击）的 Lua 环境直注入 core：emu:addKey(N)/emu:clearKey(N)（与 SDL 手柄
# 等效，绕过 Qt 键盘系统）。窗口路径：Tools 菜单 PostMessage 鼠标点击有效 →
# QMenu popup（类名 Qt51516QWindowPopup*）物理点击第 4 项 →「脚本」窗口 →
# 物理点击 prompt（窗口坐标 y≈616）→ PostMessage WM_CHAR 逐字符输入 + Enter。
# Lua 键位索引与 socketserver.lua 一致：A=0 B=1 S(select)=2 s(start)=3 ←=4 →=5 ↑=6 ↓=7。
# 实测：45.18-62s 段 22 事件 Lua 注入后转场成功（键盘屏 161.5 → 游戏画面 80.7）。
LUA_ZONE_MS = (45180, 62000)       # 键盘屏段（demo 时间：键盘屏出现→名字确认转场）
LUA_HOLD_MS = 66000                # Lua 注入持续时刻（abs 时刻）。fix7：62-66s 的
                                   # A×3（62.03/63.52/65.48，妈妈对话推进）走 Lua
                                   # 连发快路径（fix6 实证慢路径 1.3s/键序列化交付
                                   # 累积落后 3-4s → 对话未完成先断流 → 冻结）；
                                   # 66s 后立即关窗+WM_ACTIVATE 恢复 PostMessage，
                                   # 在 66-84s 长空闲期沉淀焦点——fix5 实证 62.03s
                                   # 刚关窗的恢复只稳定 ~2 键（65.48s A 失效），
                                   # 90s 长沉淀恢复则长期稳定（89.33-94.81 A×8 全
                                   # 生效），故恢复点必须赶在长空闲期之前
LUA_PREPARE_MS = 4000              # Lua 窗口准备提前量（开窗/聚焦耗时 ~3.5s）
# mGBA GBAKey 枚举（include/mgba/internal/gba/input.h）：A=0 B=1 S=2 s=3
# RIGHT=4 LEFT=5 UP=6 DOWN=7 R=8 L=9——LEFT/RIGHT 勿反（2026-08-08 实证：
# 反了则键盘屏内光标左右移动反，名字错乱转场延迟）
VK2LUA = {"A": 0, "B": 1, "S": 2, "s": 3, "<": 5, ">": 4, "^": 6, "v": 7,
          "R": 8, "L": 9, "LEFT": 5, "RIGHT": 4, "UP": 6, "DOWN": 7}
MENU_TOOLS_X = 230                  # 菜单栏 Tools 客户区 x（实测弹出位置）
MENU_SCRIPTING_Y = 81               # Tools 菜单「脚本...」客户区 y（实测映射）
PROMPT_WIN_Y = 616                  # 脚本窗口 prompt QLineEdit 窗口 y（标题栏下 39px）

# 走路段 Lua 帧级调度（2026-08-08 socket 方案，根治走路段 PostMessage 分叉）
# 架构见 tools/probe_lua_walk.py 模块 docstring：sched_server.lua 的 frame 回调
# （videoFrameEnded 核心线程同步执行，零冻结）+ socket 8890 帧调度——走路段
# （106.5s+）全部按键按游戏帧精确落地（F(t) = F_gate + round((t−WALK_KEY_ABS)
# ×0.06) − 1），PostMessage 不再参与：无帧相位抖动、hold 精确复刻、位置差不累积。
SCHED_PORT = 8890
PLAYER_X = 0x02020650        # 玩家像素 x（u16，16px/格，第一代已标定）
PLAYER_Y = 0x02020652        # 玩家像素 y
MAP_BANK = 0x02025A0C        # 地图 bank（u8）
MAP_ID = 0x02025A0E          # 地图 id（u8）
COORD_ALARM_PX = 64          # 坐标积分误差 > 4 格 → 走路段分叉报警中止
A8_SPAM_CAP = 40             # fix11/fix14c 注入 A 总数软上限。第九轮修正：
                             # 录制 2F 总 A-down=43（起床 8+第二对话 35，用户
                             # 连按）从未锁；第七轮 fix11 注入 ~26 次且「(120,
                             # 112) 锁」实为楼梯 warp（坐标冻结=转场特征，见
                             # 走路段坐标反馈的 warp 豁免）——A 连按本身不锁
                             # （hack 的剧情锁另有触发条件，见数据/knowledge/
                             # lock_analysis.md）。上限 40 保录制 43 之下余量


class ReplayWindowLost(Exception):
    """回放窗口失效且无法恢复（mGBA 进程退出/窗口销毁、重找失败）→ 中止回放。

    2026-08-08 全段实证：301s 处 PostMessage 抛 1400 无效窗口句柄（mGBA 窗口
    销毁）→ send_vk 无防护 → 整段 traceback。修复：safe_send 先尝试重找窗口
    （进程活着则窗口可能重建），重找失败抛此异常优雅中止（日志完整 + 清理 .sav）。
    """


def stretch_dir_taps(keys: list[dict]) -> tuple[list[dict], int]:
    """命名界面段方向键短点按的 up 提前到 down+SHORTEN_HOLD_MS（复刻录制 0 格）。

    - down 时刻不变（回放节奏不变）；仅 up 提前
    - 仅 45-51s 且 <300ms 的短点按缩短；其他段事件原样透传
    - 返回 (重排后事件列表, 缩短计数)
    """
    out: list[dict] = []
    pending: dict[str, tuple[int, dict]] = {}
    n_shorten = 0
    for e in keys:
        name = e["name"]
        if name in DIR_KEYS:
            if e["down"]:
                pending[name] = (e["t"], e)
            else:
                dt, down_ev = pending.pop(name, (None, None))
                if dt is None:
                    out.append(e)  # 孤儿 up（不配对）照发
                    continue
                hold = e["t"] - dt
                if (SHORTEN_ZONE_MS[0] <= dt <= SHORTEN_ZONE_MS[1]
                        and hold < SHORTEN_MAX_MS):
                    e = {**e, "t": dt + SHORTEN_HOLD_MS}
                    n_shorten += 1
                out.append(down_ev)
                out.append(e)
        else:
            out.append(e)
    out.sort(key=lambda k: k["t"])
    return out, n_shorten


def drop_first_wake_a(keys: list[dict]) -> list[dict]:
    """fix14：drop 整个 A×8（89.33-94.61s 全部 A 事件）。

    fix8-13 实证：睡眠场景里 A 弹「再睡」循环对话（fix9 ASCII 实证睡眠+
    底部对话框；fix10 时间线 95s 推进完回到纯睡眠 24.0 人没醒）——A×8
    是污染源（RIGHT 唤醒重试被其对话框 mean 66-70 干扰/堵住）。drop 后：
    RIGHT 重试（84.5-96s）在焦点养好（15-24s 抖动，fix13 实证）后唤醒
    → 房间场景无 A×8 污染 → A×8 自愈补发（95.5-99.5s）触发并推进起床
    对话 → 转场 → A×6 对齐。
    """
    out = []
    for e in keys:
        if e["name"] == "A" and 89500 <= e["t"] <= 95200:
            continue  # A×8 的 down/up 全 drop（abs 89.5-95.2s，含最后 1 对 94.61s）
        out.append(e)
    return out


WALK_KEY_ABS = 106500  # 走路段第一键 abs 阈值（录制 106.55s 相对 = 106847 abs）
# v10.3（2026-08-08）：走路段帧表首键 = 出门后第一 RIGHT（109438）——下床
# DOWN（106844-108282，长按 1.44s）并入 A 批帧表（A 批上界），walk 批跳过。
# 理由（round-19 失败链闭合）：A 批推完对话后玩家若未按 DOWN 下床 → 剧情
# 自动瞬移（黑屏）到 2F 楼梯口 + 自动弹出剧情对话 → 残余 A 推进 7 句后停在
# 等待 → 冻结。录制玩家 106.85s 手动 DOWN 打断瞬移。DOWN 入 A 批后帧轴与
# A 批统一（F_dlg1 锚定），walk 首键帧 = DOWN up + 69 帧（录制 1.156s gap）。
WALK_KEY_START = 109438
# 起床段帧表整体平移（第 11 轮 v4，2026-08-08）：round-11d/e 实证回放睡眠
# 场景晚到 ~5-9s（妈妈对话关后过场 ~13-16s vs 录制 6.5s，根因未明）→ 帧表
# RIGHT（84.25s=录制位）打在睡眠早期无效（唤醒需睡眠 ≥~11s：fix14 时代
# 84.5-90s RIGHT 重试全打空、90s 处睡眠 12-15s 才醒；round-11e 84.4-87.4s
# 帧 mean 22.3-22.6 恒定 + 106s 仍 mean 24 实证未醒）→ 后续 A 全打睡眠
# 场景弹「再睡」框 → 永久卡睡 → 开闸后 walk 批打在锁死状态 → 冻结中止。
# +9000ms 平移：RIGHT→93.25s（睡眠起点 ∈[77.1,81.9]s ⇒ 睡眠 10.3-16.2s 处，
# 覆盖唤醒阈值）；A 最早 98.62s ≥ 睡眠起点+12.5+3.5=97.9s 上界（自动唤醒
# + 起床场景 3.5s）——对话等 A 不赶时间，整体顺延由 walk_offset 吸收。
WAKE_SHIFT_MS = 9000
# v10.4（2026-08-08）：睡眠起点锚定 RIGHT——唤醒相位根治（round-19/20 失败链
# 闭合）。录制证据（快照 mean 扫描）：66547ms 首次暗场景（mean 9.2；前帧 66047
# 妈妈对话中 mean 52.3）⇒ 睡眠起点 66.5s；RIGHT 84250 ⇒ 录制睡眠相位 17.7s。
# round-19/20 的 F_wake 锚定相位 ~21.6-21.9s 恰好压在 386 hack 起床站位分支
# 边界上（round-19 相位 → (120,112) ✅ / round-20 相位 +0.2s → (136,112) ✗ →
# 第二对话截断 → 提前瞬移 2F 楼梯口 → 冻结）。录制相位离边界 ~4s，安全——
# RIGHT 改锚定「检测到的睡眠起点帧 F_sleep + 1122 帧（录制相位）」→ 回放相位
# 恒定 17.7s。fps_rec 自洽验证：录制睡眠→弹出 = 22453ms × 63.4fps = 1423 帧 =
# K 1122 + 唤醒流 301 帧（4.75s×63.4 ✓）；60fps 则唤醒流仅 3.75s ≠ 实测 4.75s。
S_SLEEP_MS = 66547    # 录制暗场景首帧（快照 66547ms，mean<30 判定同 F_sleep 检测）
RIGHT_MS = 84250      # 录制 RIGHT down（睡眠相位 17703ms = 1122 帧 @63.4fps）
FPS_REC = 63.4        # 录制帧率（同机器实测；fps 误差 ±1.2s 相位仍离边界 3s+）


def _all_mgba_hwnds() -> list[int]:
    """所有可见的 mGBA 窗口（--launch 时区分新旧实例）。"""
    import win32gui
    out = []
    def cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if title and "mGBA" in title:
                out.append(hwnd)
    win32gui.EnumWindows(cb, None)
    return out


class LuaInjector:
    """mGBA「脚本」控制台直注入（键盘屏段替代 PostMessage）。

    打开 Tools→脚本...（PostMessage 点菜单栏 + 物理鼠标点菜单项 + 物理点 prompt），
    然后 PostMessage WM_CHAR 向 prompt 输入 emu:addKey(N)/emu:clearKey(N) + Enter。
    Lua 环境直注入 core，绕过 Qt 键盘系统（键盘屏期间 Qt 焦点对象偏离）。
    """

    def __init__(self, hwnd: int, pid: int | None):
        import win32gui
        import win32process
        self.hwnd = hwnd
        self.pid = pid
        self.sv: int | None = None
        self.ready = False
        self._win32gui = win32gui
        self._win32process = win32process

    def _visible_set(self) -> set[int]:
        out = set()
        self._win32gui.EnumWindows(lambda h, _: out.add(h)
                                   if self._win32gui.IsWindowVisible(h) else None, None)
        return out

    def _mgba_windows(self) -> list[tuple[int, str, str]]:
        out = []
        def cb(h, _):
            pid = self._win32process.GetWindowThreadProcessId(h)[1]
            if pid == self.pid:
                out.append((h, self._win32gui.GetWindowText(h),
                            self._win32gui.GetClassName(h)))
        self._win32gui.EnumWindows(cb, None)
        return out

    def prepare(self) -> bool:
        """打开「脚本」窗口并聚焦 prompt（一次性，约 3.5s）。"""
        import ctypes
        import win32con
        if self.ready:
            return True
        win32gui = self._win32gui
        user32 = ctypes.windll.user32

        def click_client(h, x, y):
            lparam = ((y & 0xFFFF) << 16) | (x & 0xFFFF)
            win32gui.PostMessage(h, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lparam)
            time.sleep(0.08)
            win32gui.PostMessage(h, win32con.WM_LBUTTONUP, 0, lparam)
            time.sleep(0.5)

        def pclick(x, y):
            user32.SetCursorPos(x, y)
            time.sleep(0.12)
            user32.mouse_event(0x0002, 0, 0, 0, 0)
            time.sleep(0.1)
            user32.mouse_event(0x0004, 0, 0, 0, 0)
            time.sleep(0.8)

        def outside_click():
            user32.SetCursorPos(100, 400)
            time.sleep(0.12)
            user32.mouse_event(0x0002, 0, 0, 0, 0)
            time.sleep(0.1)
            user32.mouse_event(0x0004, 0, 0, 0, 0)
            time.sleep(0.7)

        print(f"  [Lua] 打开「脚本」窗口...", flush=True)
        # 2026-08-08 菜单扫描实证（tools/tmp_menu_probe.py 干净扫描）：
        #   1. 菜单布局稳定：y=15 游戏替代/37 传感器/58 作弊码/81 脚本/104 设置/
        #      125 便携化/148 调试器——81=脚本 从未变过
        #   2. 之前「布局变了」的判断是假象：Qt 菜单是 toggle，上一轮点偏
        #      （菜单保持打开）→ 下一轮 PostMessage 点 Tools 按钮变成「关闭」
        #      → 所有后续点击全部错位。点中=菜单关闭+目标窗口出现；点偏=菜单
        #      保持打开——这是唯一可靠的判定
        # 因此每轮先物理点击外部强制菜单关闭态，再开菜单、点 81、按窗口标题
        # 确认「脚本」出现；点偏则关闭误开窗口后整轮重试
        for attempt in range(3):
            outside_click()
            click_client(self.hwnd, MENU_TOOLS_X, 15)      # Tools 菜单
            time.sleep(0.5)
            popup = None
            for h in self._visible_set():
                if 'QWindowPopup' in win32gui.GetClassName(h):
                    popup = h
                    break
            if not popup:
                print(f"  ⚠️ Tools 菜单未弹出（尝试 {attempt + 1}/3）", flush=True)
                continue
            pr = win32gui.GetWindowRect(popup)
            # QMenu popup：内容区相对窗口偏移 31px（337-275 阴影），菜单项客户区 y=81
            pclick(pr[0] + 137, pr[1] + 31 + MENU_SCRIPTING_Y)
            # 轮询确认「脚本」窗口出现（最 2s；点中菜单项 → 菜单关 + 窗口开）
            for _ in range(10):
                time.sleep(0.2)
                for h, t, c in self._mgba_windows():
                    if '脚本' in t:
                        self.sv = h
                        break
                if self.sv:
                    break
            if self.sv:
                break
            # 点偏：关掉误开的窗口（便携化确认框/设置等），整轮重试
            print(f"  ⚠️ 菜单项点击未中（尝试 {attempt + 1}/3），关闭误开窗口重试",
                  flush=True)
            for h, t, c in self._mgba_windows():
                if h != self.hwnd and 'QWindowPopup' not in c:
                    try:
                        win32gui.PostMessage(h, win32con.WM_CLOSE, 0, 0)
                    except Exception:
                        pass
            time.sleep(0.6)
        if not self.sv:
            print("  ✗ 未找到「脚本」窗口", flush=True)
            return False
        # 移到右侧避免遮挡游戏画面（游戏窗口 1147-2441）
        user32.SetWindowPos(self.sv, 0, 1900, 550, 859, 676, 0x0040)
        time.sleep(0.5)
        pclick(1900 + 500, 550 + PROMPT_WIN_Y)             # 聚焦 prompt
        time.sleep(0.3)
        self.ready = True
        print(f"  [Lua] 「脚本」窗口 {self.sv:#x} 就绪", flush=True)
        return True

    def _ensure_prompt(self, force: bool = False) -> bool:
        """物理点击聚焦 prompt（关键注入点前调用）。

        2026-08-08 实证：REPL burst（A×8/A×9 快路径连发）执行期间/之后 prompt
        会失焦，后续 WM_CHAR 被 Qt 忽略（fix2 运行：窗口活着但 58.8s/60.0s
        Lua A 无效——画面仍匹配录制 60.0s）；极端情况下 Enter 打在失焦控件
        上还可能触发窗口关闭（fix1 运行 58.7s 脚本窗口神秘消失的嫌疑根因）。
        Qt 内部焦点 ≠ OS 焦点（GetGUIThreadInfo 不可靠），物理点击（mouse_event）
        同时更新两者，是 prepare 实测最可靠的方式。带 2s 时间缓存避免重复点击。
        """
        import ctypes
        if not self.sv or not self._win32gui.IsWindow(self.sv):
            return False
        if not force and time.time() - getattr(self, "_last_click", 0.0) < 2.0:
            return True
        try:
            user32 = ctypes.windll.user32
            user32.SetCursorPos(1900 + 500, 550 + PROMPT_WIN_Y)
            time.sleep(0.12)
            user32.mouse_event(0x0002, 0, 0, 0, 0)
            time.sleep(0.1)
            user32.mouse_event(0x0004, 0, 0, 0, 0)
            time.sleep(0.3)
            self._last_click = time.time()
            return True
        except Exception:
            return False

    def inject(self, code: str):
        """WM_CHAR 输入一行 Lua 并 Enter（0.54s/命令）。

        0.008s/字符 + 0.05s wait 的"快路径"会导致 REPL 命令堆积（执行延迟
        > 注入间隔 → 按键时刻整体推迟 ~8s → 键盘屏转场延迟）。矩阵实验
        （2026-08-08 hold 100-500ms）证实 0.02s/字符 + 0.15s wait 下
        每命令立即执行、A 单次确认有效。
        """
        import ctypes
        import win32con
        if not self.sv or not self._win32gui.IsWindow(self.sv):
            print(f"  ⚠️ 脚本窗口已失效，Lua 注入丢弃: {code}", flush=True)
            return
        for ch in code:
            self._win32gui.PostMessage(self.sv, win32con.WM_CHAR, ord(ch), 1)
            time.sleep(0.02)
        time.sleep(0.1)
        scan = ctypes.windll.user32.MapVirtualKeyW(0x0D, 0)
        self._win32gui.PostMessage(self.sv, win32con.WM_KEYDOWN, 0x0D, (scan << 16) | 1)
        time.sleep(0.03)
        self._win32gui.PostMessage(self.sv, win32con.WM_KEYUP, 0x0D, (scan << 16) | 0xC0000001)
        time.sleep(0.15)

    def inject_fast(self, code: str):
        """快路径连发：WM_CHAR 逐字符 + Enter（不等 REPL 执行，靠消息队列 FIFO）。

        连发实验（2026-08-08 data/tmp_burst.py）证实：REPL 每命令执行 ~250ms
        （runCode 被 CoreController::Interrupter 包裹——执行期间核心冻结，
        src/platform/qt/scripting/ScriptingController.cpp load()），连发注入
        16 命令仅 ~3.6s，执行完 ~3.7s（执行间隙 250ms 恰好构成按住窗口，
        ≈ 录制 hold 93-234ms，A 单次确认有效）。转场键在最后命令执行后
        （核心恢复）立即发生。
        """
        import ctypes
        import win32con
        if not self.sv or not self._win32gui.IsWindow(self.sv):
            print(f"  ⚠️ 脚本窗口已失效，Lua 快路径注入丢弃: {code}", flush=True)
            return
        for ch in code:
            self._win32gui.PostMessage(self.sv, win32con.WM_CHAR, ord(ch), 1)
            time.sleep(0.008)
        time.sleep(0.05)
        scan = ctypes.windll.user32.MapVirtualKeyW(0x0D, 0)
        self._win32gui.PostMessage(self.sv, win32con.WM_KEYDOWN, 0x0D, (scan << 16) | 1)
        time.sleep(0.01)
        self._win32gui.PostMessage(self.sv, win32con.WM_KEYUP, 0x0D, (scan << 16) | 0xC0000001)
        time.sleep(0.05)

    def burst_presses(self, names: list[str]):
        """连发按住序列：每键 addKey+clearKey 两条命令，快路径连续注入。

        只用于键盘屏段（名字确认）：A×8 已验证转场（burst 实验）。命令间隙
        （REPL 执行 ~250ms）即按住窗口，顺序由消息队列 FIFO 保证。
        """
        for name in names:
            idx = VK2LUA.get(name)
            if idx is None:
                continue
            self.inject_fast(f"emu:addKey({idx})")
            self.inject_fast(f"emu:clearKey({idx})")

    def send(self, k: dict) -> bool:
        """按事件注入（down→emu:addKey / up→emu:clearKey）。返回是否成功发送。"""
        idx = VK2LUA.get(k["name"])
        if idx is None:
            return False
        cmd = "addKey" if k["down"] else "clearKey"
        self.inject(f"emu:{cmd}({idx})")
        return True

    def close_window(self):
        """关闭「脚本」窗口（键盘屏段结束后调用）。

        2026-08-08 全段回放实证：脚本窗口打开期间 Qt 键盘事件焦点偏离，恢复
        PostMessage 后按键完全无效（62-90s 画面冻结 28s，直到 90s 进度报告的
        SetForegroundWindow 才恢复）。关闭脚本窗口把焦点还给主窗口。
        """
        import win32con
        if not self.sv:
            return
        try:
            self._win32gui.PostMessage(self.sv, win32con.WM_CLOSE, 0, 0)
            t0 = time.time()
            while time.time() - t0 < 3:
                if not self._win32gui.IsWindow(self.sv):
                    break
                time.sleep(0.1)
        except Exception:
            pass
        self.sv = None
        self.ready = False

    def send_pressed(self, k: dict, hold_ms: float) -> bool:
        """按住并保持录制时长后释放（down+up 一次完成）。

        键盘屏 A 按住 ~93-234ms 选字；逐行注入速度（~0.5s）会让 A 变成
        长按连选 → 名字分叉 → 全局发散（2026-08-08 全段验证实证）。保持
        时长必须复刻录制，否则状态不同。
        """
        idx = VK2LUA.get(k["name"])
        if idx is None:
            return False
        self.inject(f"emu:addKey({idx})")
        time.sleep(hold_ms / 1000.0)
        self.inject(f"emu:clearKey({idx})")
        return True


def _force_foreground(hwnd: int) -> None:
    """SetForegroundWindow 加固 + 强制 Qt 焦点回主窗口。

    Python 后台进程直接 SetForegroundWindow 常被 Windows 前台锁定拒绝
    （2026-08-08 全段回放实证：90s 进度报告的置前才恢复冻结的输入）。绑定
    前台线程输入队列后置前成功率显著提高。

    2026-08-08 诊断实证：62-90s 期间 GetForegroundWindow 恒为主窗口（fg==hwnd，
    窗口未失焦/未最小化/核心 60fps 在跑），但 PostMessage 全灭——Qt 键盘焦点
    停在「偏离对象」（键盘屏/脚本窗口遗留），SetForegroundWindow 对已前台窗口
    是 no-op（不发 WM_ACTIVATE），Qt 永远收不到 activate 事件。因此置前后
    直接补发 WM_ACTIVATE(WA_ACTIVE) 给主窗口，强制 Qt 处理 activate →
    键盘焦点还给游戏画面（89.33s 前 PostMessage 才恢复的实证依据）。
    """
    import win32api
    import win32con
    import win32gui
    import win32process
    try:
        fg = win32gui.GetForegroundWindow()
        fg_tid = win32process.GetWindowThreadProcessId(fg)[0] if fg else 0
        my_tid = win32api.GetCurrentThreadId()
        attached = False
        if fg_tid and fg_tid != my_tid:
            win32process.AttachThreadInput(my_tid, fg_tid, True)
            attached = True
        win32gui.ShowWindow(hwnd, 9)  # SW_RESTORE
        win32gui.SetForegroundWindow(hwnd)
        win32gui.PostMessage(hwnd, win32con.WM_ACTIVATE, win32con.WA_ACTIVE, 0)
        if attached:
            win32process.AttachThreadInput(my_tid, fg_tid, False)
    except Exception:
        pass


def _kb_phase(lua: LuaInjector, hwnd: int, keys: list[dict], t_start: float,
              t_base: float, run_dir: Path | None, kb_advance: int = 6) -> int:
    """键盘屏段一次性接管：A×2 推进 → 检测键盘屏 → 连发 A×8 转场 →
    等转场 → 连发 A×kb_advance 对话推进 → 定位 i。

    连发模型（2026-08-08 实验实证）：
    - 逐命令慢速注入 1.3s/键 → 转场晚 ~6s；连发（0.008s/字符快路径）16 命令
      ~3.6s 注入完，REPL 队列 FIFO ~4s 执行完（每命令 ~250ms：runCode 被
      Interrupter 包裹，执行期间核心冻结；执行间隙 250ms 即按住窗口）
    - tmp_burst/tmp_burst3/tmp_burst4 三次复现：A×8 连发 → 转场黑屏
      （检测后 3.7-3.9s）→ 转场后画面 mean≈83-100
    - B1=[A,LEFT,DOWN,A]（录制键盘屏真实 4 键）连发/慢速均不转场
      （tmp_kb_dir 实证，方向键有效但键序语义不匹配回放键盘屏变体）
    - 录制 45.2-47.1s 的 UP+A×3 打在对话/过渡屏（UP 在 Lua 路径实测无效）
      → 用 A×2 慢速注入等价代替（A×2 后键盘屏出现，实测）
    - 转场后对话 A（录制 50.875-60.04s 共 7 次推进）由连发 A×N 代替
      （对话屏 A 短按单次推进，连发 250ms 间隙=单次确认）；主循环恢复点
      定位在 Lua 段之后（bisect 跳过全部被代替的键）
    - 名字：回放键盘屏为「默认名字确认」变体（mean 160.7 vs 录制输入屏
      150.2），A 连按=选是转场，默认名字为游戏内置（用户规则名字 A 由
      录制操作满足；回放依赖默认名字=A，转场后对话可验证）

    返回定位后的 i（第一个 t > 恢复时刻的键索引）。
    """
    import numpy as np
    # 1) A×2 推进对话（慢速注入：对话屏 A 长按会连推进多行，必须单次确认。
    #    实测：回放 45.19s 对话位置离键盘屏差 2 次推进，A×1 停在对话屏、
    #    A×2 推进到键盘屏。第 2 键 clearKey 执行 ~48.3s、键盘屏 ~50.2s，
    #    安全）
    print("  🔧 键盘屏段：A×2 推进 → 检测键盘屏 → A×8 转场 → A×N 对话推进", flush=True)
    # burst 执行期间/之后 prompt 会失焦，后续 WM_CHAR 被 Qt 忽略（2026-08-08
    # fix2 实证：58.8s/60.0s Lua A 无效）。每个注入阶段前物理点击聚焦 prompt
    # （mouse_event 同时更新 OS 焦点与 Qt 内部焦点，prepare 实测最可靠）
    lua._ensure_prompt(force=True)
    lua.send_pressed({"name": "A", "down": True}, 150)
    lua.send_pressed({"name": "A", "down": True}, 150)
    # 2) 检测键盘屏（mean>140 持续 2 帧，≤10s 超时）；期间照常存 verify 快照
    t_det = None
    hi = 0
    last_cap = 0.0
    t0 = time.monotonic()
    while time.monotonic() - t0 < 10:
        img = window_backend.capture_hwnd(hwnd)
        if img is not None:
            m = float(np.asarray(img).mean())
            if run_dir is not None:
                now_ms = int((time.monotonic() - t_start) * 1000) + t_base
                if now_ms - last_cap >= CAP_INTERVAL_MS:
                    last_cap = now_ms
                    Image.fromarray(img).save(run_dir / f"t{now_ms:07d}.png")
            if m > 140:
                hi += 1
                if hi >= 2:
                    t_det = time.monotonic()
                    print(f"    键盘屏检测到 mean={m:.1f}", flush=True)
                    break
            else:
                hi = 0
        time.sleep(0.1)
    if t_det is None:
        print("  ⚠️ 键盘屏 10s 超时未检测到——照发键序（可能打在对话屏）", flush=True)
        t_det = time.monotonic()
    # 3) 连发 A×8 转场（默认名字确认屏：A 连按=确认 → 转场黑屏）
    lua._ensure_prompt(force=True)
    lua.burst_presses(["A"] * 8)
    # 4) 等转场（检测黑屏 mean<50 → 转场后画面 mean>60，≤14s 超时）
    t_trans = None
    t_w0 = time.monotonic()
    while time.monotonic() - t_w0 < 14:
        img = window_backend.capture_hwnd(hwnd)
        if img is not None:
            m = float(np.asarray(img).mean())
            if m < 50 and t_trans is None:
                t_trans = time.monotonic()
                print(f"    转场黑屏 t={t_trans - t_det:.2f}s mean={m:.1f}", flush=True)
            if t_trans is not None and m > 60:
                print(f"    转场后画面 t={time.monotonic() - t_det:.2f}s mean={m:.1f}", flush=True)
                break
        time.sleep(0.1)
    if t_trans is None:
        print("  ⚠️ 转场 14s 超时未检测到——仍发对话推进 A×N", flush=True)
    # 5) 连发 A×kb_advance 对话推进（录制 50.875-60.04s 共 7 次；A×8 残余按键
    #    在转场黑屏期间被吞（2026-08-08 块级 diff 实证：A×6 推进后停在录制
    #    53.5s 状态，落后 ~2-3 行），等 0.8s 转场画面稳定后再推进）
    time.sleep(0.8)
    lua._ensure_prompt(force=True)
    lua.burst_presses(["A"] * kb_advance)
    # 6) i 定位到恢复时刻后的下一个键（Lua 段之后的键按录制时刻继续注入）
    time.sleep(0.8)
    # 逐键注入恢复前的最后一次聚焦（58.8s/60.0s 的 Lua A 依赖 prompt 焦点）
    lua._ensure_prompt(force=True)
    resume_ms = int((time.monotonic() - t_start) * 1000) + t_base
    j = 0
    while j < len(keys) and keys[j]["t"] <= resume_ms:
        j += 1
    print(f"    键盘屏段接管完成，恢复逐键注入（i→{j}，resume={resume_ms - t_base}ms）",
          flush=True)
    return j


def wait_new_hwnd(existing: list[int], timeout: float = 20.0) -> int | None:
    """等新启动的 mGBA 窗口（不在 existing 集合里的 hwnd）。"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        for h in _all_mgba_hwnds():
            if h not in existing:
                return h
        time.sleep(0.5)
    return None


def verify_report(demo_path: Path, run_dir: Path, to_sec: float | None) -> str:
    """回放快照 vs 录制快照对比 → 报告文本。"""
    events = [json.loads(l) for l in open(demo_path, encoding="utf-8") if l.strip()]
    rec_evs = [e for e in events if e["ev"] == "snap"]
    print("  载入录制快照...")
    rec = {s["t"]: np.asarray(Image.open(IMG_DIR / s["img"]).convert("RGB"))
           for s in rec_evs}
    rec_ts = sorted(rec)
    rp_files = sorted(run_dir.glob("t*.png"))
    rows = []
    for p in rp_files:
        t_r = int(p.stem[1:])
        img_r = np.asarray(Image.open(p).convert("RGB"))
        lo = bisect_left(rec_ts, t_r - MATCH_WINDOW_MS)
        hi = bisect_right(rec_ts, t_r + MATCH_WINDOW_MS)
        if lo == hi:
            rows.append((t_r, 1.0, None))
            continue
        best = min((diff_ratio(img_r, rec[rec_ts[i]]), rec_ts[i])
                   for i in range(lo, hi))
        rows.append((t_r, best[0], best[1]))
    if not rows:
        return "✗ 回放快照为空，无法对比"

    diffs = [r[1] for r in rows]
    med = float(np.median(diffs))
    p90 = float(np.percentile(diffs, 90))
    aligned = sum(1 for d in diffs if d < ALIGNED_DIFF) / len(diffs)
    diverged = sum(1 for d in diffs if d > DIVERGED_DIFF) / len(diffs)
    drift = [r[2] - r[0] for r in rows if r[2] is not None]
    drift_med = int(np.median(drift)) if drift else 0
    ok = med < VERDICT_MED_MAX and diverged < VERDICT_DIV_MAX
    # 发散点 TOP5
    top = sorted(rows, key=lambda r: -r[1])[:5]

    # 键盘屏段专项统计（±5s 匹配窗口会把恒定键盘屏画面误配为「对齐」——
    # 2026-08-08 实测：转场差 6s 仍报 ✅。逐帧看匹配时刻连续性与转场前后
    # 漂移，才能确认转场真实对齐）
    kb_rows = [(t_r, d, t_m) for t_r, d, t_m in rows
               if LUA_ZONE_MS[0] - 1000 <= t_r <= LUA_ZONE_MS[1] + 1000]
    kb_trans = [(t_r, d, t_m) for t_r, d, t_m in kb_rows if t_m is not None]
    kb_lines = []
    if kb_rows:
        kb_aligned = sum(1 for _, d, _ in kb_rows if d < ALIGNED_DIFF) / len(kb_rows)
        kb_drift = [t_m - t_r for _, _, t_m in kb_trans]
        kb_drift_med = int(np.median(kb_drift)) if kb_drift else 0
        kb_drift_min = min(kb_drift) if kb_drift else 0
        kb_drift_max = max(kb_drift) if kb_drift else 0
        kb_lines.append(f"键盘屏段 {len(kb_rows)} 张: 对齐帧 {kb_aligned * 100:.0f}% "
                        f"| 漂移中位 {kb_drift_med:+d}ms [{kb_drift_min:+d}..{kb_drift_max:+d}]")
        # 转场段时间线（45-55s 每张的匹配时刻，人工核对转场对齐）
        kb_lines.append("  键盘屏段时间线（回放t → diff → 最优匹配t）：")
        for t_r, d, t_m in kb_rows:
            m = f"{t_m}ms" if t_m is not None else "无匹配"
            kb_lines.append(f"    t={t_r}ms diff={d:.2f} → {m}")

    L = []
    L.append(f"回放验证: {demo_path.name}（{to_sec}s 限定）" if to_sec else
             f"回放验证: {demo_path.name}（全段）")
    L.append(f"回放快照 {len(rows)} 张 | 录制快照 {len(rec_evs)} 张 | 匹配窗口 ±{MATCH_WINDOW_MS}ms")
    L.append(f"最优 diff: 中位={med:.2f} p90={p90:.2f} max={max(diffs):.2f}")
    L.append(f"对齐帧(<{ALIGNED_DIFF}): {aligned * 100:.1f}% | 发散帧(>{DIVERGED_DIFF}): {diverged * 100:.1f}%")
    L.append(f"时间漂移(最优匹配-回放): 中位 {drift_med:+d}ms")
    verdict = "✅ 对齐 —— 回放与录制一致，录制质量可靠" if ok else \
        "✗ 发散 —— 回放与录制分叉，需排查（见发散点）"
    L.append(f"结论: {verdict}")
    L.append("")
    if kb_lines:
        L.extend(kb_lines)
        L.append("")
    if top and not ok:
        L.append("发散点 TOP5（回放t → 最优diff，最优匹配t）：")
        for t_r, d, t_m in top:
            L.append(f"  t={t_r}ms diff={d:.2f} (匹配 {t_m}ms)")
        L.append("")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description="窗口回放")
    ap.add_argument("demo", help="demo jsonl 文件名或路径")
    ap.add_argument("--launch", action="store_true", help="自动启动 mGBA")
    ap.add_argument("--verify", action="store_true",
                    help="回放+抓屏对比验证（需 --launch，--speed 1.0）")
    ap.add_argument("--speed", type=float, default=1.0, help="回放倍速（验证必须 1.0）")
    ap.add_argument("--to", type=float, default=None, help="只回放前 N 秒")
    ap.add_argument("--clean-sav", action="store_true",
                    help="回放前备份并删除电池存档 .sav，结束后恢复"
                         "（录制从无存档冷启动走新游戏流程时，回放必须同样无 .sav，"
                         "2026-08-08 实测：带 .sav 回放会在开场动画结束的存档检查点分叉）")
    ap.add_argument("--no-lua-kb", action="store_true",
                    help="禁用键盘屏段 Lua 注入（默认启用：键盘屏 PostMessage 无效，"
                         "2026-08-08 实证，仅对比实验用）")
    ap.add_argument("--kb-advance", type=int, default=9,
                    help="键盘屏段转场后的对话推进 A 次数（录制 50.875-60.04s 共 7 次；"
                         "A×8 残余在转场黑屏被吞（块级 diff 实证落后 2-3 行），"
                         "默认 9 补足；迭代调优用）")
    ap.add_argument("--walk-lua", action="store_true",
                    help="走路段全部按键走 Lua 帧级调度（sched_server.lua socket "
                         "8890，根治 PostMessage 帧相位抖动分叉；2026-08-08 方案）")
    ap.add_argument("--probe-walk", action="store_true",
                    help="走路段探针模式：开闸后跑通道/帧/20 键位移探针并中止"
                         "（诊断用；含 --walk-lua 的脚本加载逻辑）")
    ap.add_argument("--probe-freeze", action="store_true",
                    help="(120,112) 冻结诊断探针模式：开闸后只发录制首个方向键"
                         "hold → 观察坐标 → 冻结后逐方向 14 帧探针键（墙 vs 锁）"
                         "并中止（诊断用；含 --walk-lua 的脚本加载逻辑）")
    args = ap.parse_args()

    # ---- .sav 起点状态（--clean-sav：备份→删除→结束后恢复）----
    import shutil
    sav_path = Path(ROM_PATH).with_suffix(".sav")
    sav_bak = None
    if args.clean_sav and sav_path.exists():
        sav_bak = sav_path.with_name(sav_path.name + ".bak-clean")
        shutil.copy2(sav_path, sav_bak)
        sav_path.unlink()
        print(f"🧹 已备份并删除 .sav（{sav_bak.name}），回放起点=无存档冷启动")

    if args.verify and not args.launch:
        print("✗ --verify 需要 --launch（回放起点须与录制一致：从冷启动开始）")
        return 1
    if args.verify and args.speed != 1.0:
        print("✗ --verify 需要 --speed 1.0（快照对比在同一时间轴上才有意义）")
        return 1

    demo_path = DEMO_DIR / args.demo if not Path(args.demo).exists() else Path(args.demo)
    assert demo_path.exists(), f"demo 不存在: {demo_path}"
    # 走路段帧调度组件（lazy：probe 模块顶层 import 本模块的常量——main() 运行时
    # 本模块已完整加载，无循环导入）
    from tools.probe_lua_walk import (MAP_BANK, MAP_ID, PLAYER_X, PLAYER_Y,
                                      SCHED_PORT, DIRVEC, _plan_walk,
                                      load_sched_channel, run_freeze_probe,
                                      run_probe, sched_frame)
    events = [json.loads(l) for l in open(demo_path, encoding="utf-8") if l.strip()]
    keys = [e for e in events if e["ev"] == "key"]
    if not keys:
        print("demo 无按键事件")
        return 1
    t_base = keys[0]["t"]
    if args.to is not None:
        keys = [k for k in keys if k["t"] - t_base <= args.to * 1000]
    # 命名界面段方向键短点按缩短（录制轴拨动 0 格 vs 键盘 1 格补偿）
    keys, n_shorten = stretch_dir_taps(keys)
    # 第 11 轮：完整键副本（含 A×8）供起床段帧表使用——帧表 RIGHT 由 Lua
    # 精确唤醒（无焦点抖动），A×8 打在录制同刻的第一对话上（round-11 实证：
    # drop 后帧表 20 键只推完第一对话残余，第二对话卡死不开闸）。
    # keys（drop 版）继续给 PostMessage 逐键路径用（fix14 旧语义）。
    keys_full = keys
    keys = drop_first_wake_a(keys)  # fix14：drop 整个 A×8（睡眠「再睡」对话框污染源）
    if n_shorten:
        print(f"🔧 命名界面段方向键短点按缩短: {n_shorten} 个 up 事件提前到 down+{SHORTEN_HOLD_MS}ms"
              f"（录制轴拨动 0 格 vs 键盘 1 格补偿）")
    # 按键保持时长（Lua 注入需要复刻录制按住时长）
    holds: dict[tuple[str, int], int] = {}
    pending_down: dict[str, int] = {}
    for k in keys:
        if k["down"]:
            pending_down[k["name"]] = k["t"]
        else:
            dt = pending_down.pop(k["name"], None)
            if dt is not None:
                holds[(k["name"], dt)] = k["t"] - dt
    total_s = (keys[-1]["t"] - t_base) / 1000.0 if keys else 0.0

    # ---- 窗口 ----
    proc = None
    if args.launch:
        existing = _all_mgba_hwnds()
        if existing:
            print(f"✗ 已有 {len(existing)} 个 mGBA 实例在运行——回放/验证必须独占实例"
                  f"（否则按键和抓屏可能落到不同窗口，2026-08-08 实测事故）。")
            print("  请先关闭所有 mGBA 窗口再重试。")
            return 1
        print(f"🚀 启动 mGBA: {MGBA_EXE.name}")
        proc = subprocess.Popen([str(MGBA_EXE.resolve()), ROM_PATH],
                                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
        hwnd = wait_new_hwnd(existing)
        if not hwnd:
            print("✗ 新 mGBA 窗口未出现")
            return 1
        time.sleep(1.0)  # 等首帧渲染
    else:
        hwnd = window_backend.find_window(ROM_NAME)
        if not hwnd:
            print("✗ 未找到 mGBA 窗口。先开 mGBA + ROM，或 --launch")
            return 1
    try:
        import win32con
        import win32gui
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        pass
    time.sleep(0.3)

    # 窗口内容自检：抓 3 帧，若全是纯白/纯黑 → 抓到错误窗口/游戏未渲染，中止
    bad = 0
    for _ in range(3):
        img = window_backend.capture_hwnd(hwnd)
        if img is None:
            bad += 1
        else:
            m = float(np.asarray(img).mean())
            if m > 240 or m < 2:
                bad += 1
    if bad >= 2:
        print(f"✗ 窗口内容异常（{bad}/3 帧纯白/纯黑）——抓到错误窗口或游戏未渲染，中止")
        if proc:
            proc.terminate()
        return 1
    print("✓ 窗口内容正常，开始回放")

    # ---- 回放 ----
    run_dir = REPLAY_DIR / demo_path.stem
    if args.verify:
        run_dir.mkdir(parents=True, exist_ok=True)
        for p in run_dir.glob("t*.png"):
            p.unlink()  # 清掉上一次验证的快照
    known = skipped = 0
    last_cap_ms = -10**9
    last_prog = 0.0
    last_focus_chk = 0.0
    last_wake_retry = 0.0   # fix9：RIGHT 唤醒重试节流
    last_a8_retry = 0.0     # fix9：A×8 差盒自愈节流
    a8_black_seen = False   # fix11（四轮）：起床对话段转场黑屏已见 → 停
                            #（防第二对话被 fix11 双推，双推会让对话提前结束
                            # → 录制 A 剩余打在床边 → 上床卡死）
    a8_spam = 0             # fix11/fix14c 注入 A 总数（第八轮：2F 剧情锁
                            # watchdog 兜底——录制 2F 总 A=17（起床 8+第二
                            # 9）未锁；回放第七轮 ~43 锁。软上限保守给 24，
                            # 达上限两自愈块同时停注入）
    # 出门段帧调度（第六轮）已废弃（2026-08-08 round-11f）：录制出门段方向
    # 键实际在 106.84-115.27s（DOWN 1.44s 长按→RIGHT→DOWN+A 并发→A×4→
    # DOWN→RIGHT 0.85s），不在 91.5-100s——全部落入 walk 批（WALK_KEY_ABS
    # 106.5s+），由走路段帧锚定处理。旧窗口（91500-100000）内只有起床 A 键，
    # 永不触发，删。
    gate_wait_dark = False  # v10：上床剧情变暗确认（开闸信号）——round-16 全谱
                            # 匹配实证：出门 warp 目标由出门瞬间站位决定（CLAUDE.md
                            # 已知问题 2）。录制出门 = 推完对话 → 变暗（≤106.55s，
                            # mean 57.6）→ 0.3s 后 DOWN（106.847s）从床边途中出门
                            # → warp 走路场景。v9 帧阈值开闸（推完+0.33s）在变暗前
                            # 从门口 (120,112) 出门 → warp 到录制 154s 房间（错误
                            # 地图）→ 走路段全错。v10：等变暗（dlg<30 且 mean<65）
                            # → 0.3s 后发批，复刻录制相位。
    dark_at = None          # 变暗确认时刻（v10.3 帧门控取代后已弃用，保留声明
                            # 避免回退分支引用错误——帧门控块见主循环 v10.3 注释）
    last_dark_chk = 0.0     # 帧门控检测节流（0.1s；v10 时代是变暗检测节流）
    last_dlg2_retry = 0.0   # 开闸检查节流（已弃用——v10 改 last_dark_chk 变暗开闸）
    last_fix14c_retry = -10**9  # fix14c 自愈节流（1.2s）——v8：round-14 实证
                                # 与 last_dlg2_retry 共享时被开闸检查（1.0s 周期）
                                # 饿死——开闸检查每 1.0s 重置 last_dlg2_retry，
                                # fix14c 的 >1.2s 需求永远凑不齐 → 104-116s
                                # 从未执行（第一对话残留 dlg=129.5 未被推 →
                                # 第二对话晚弹 3.5s → A 批打空 → 冻结）
    last_dlg_residual = False   # fix14c 最近判定：对话残留中（v8：开闸门控——
                                # 残留未清时帧表开闸会放 walk 批打在对话上
                                # 全部无效，round-12/13/14 冻结路径）
    residual_clear_at = None    # last_dlg_residual 置 False 的延迟时刻（v8：
                                # 实时捕获 PrintWindow 偶发偏小（round-14
                                # 实测第二对话残留 top 102.1→96.0）漏检 →
                                # 判定非残留 → 误开闸 → walk 打空；延迟 3s
                                # 期间 fix14c 每 1.2s 重试，dlg 波动命中续锁）
    dark_try_i = 0          # 暗场景（上床/错房间 mean 40-60）键轮换指针（A/START/RIGHT）
    dark_last_key = None    # 暗场景上次试探的键（防残留：生效后 B 关菜单/框）
    last_coord_diag = -10**9  # 开闸前坐标诊断节流（~2s）
    walk_offset = None      # fix14e：走路段键动态偏移（None=未门控，走路键不发）
    # 起床段帧调度（第 11 轮，2026-08-08）：键盘屏段后不关窗保持 Lua 通道，
    # 84.25s RIGHT 起起床段键（RIGHT→第一对话 A×8→转场→第二对话 A×9）批量
    # 入队帧表——PostMessage 焦点养焦抖动 15-25s（fix13 实测）导致 RIGHT 唤醒
    # 晚 ~6s（第 10/11 轮实证：RIGHT×5 mean 22.9 恒定打空到 90s）→ 起床/第一
    # 对话/第二对话整体顺延 → 开闸 (120,96)（录制 (120,112)）→ DOWN 1 格撞
    # 2F 剧情锁全方向锁死（探针实证 Δ0×4）。Lua 核心注入无焦点依赖，帧表
    # 复刻录制键序 → 对话推进与录制同步 → 开闸站位/剧情锁状态与录制一致。
    # v5（round-11g，2026-08-08）：RIGHT 批（84.2-89s）帧表照旧；对话 A 批
    # 改为锚定「第一对话弹出画面确认」——RIGHT 唤醒响应波动 ~1.5-1.9s
    # （round-11f 实测 93.25s RIGHT → 95.2s 起床场景）→ 对话弹出时刻浮动
    # （回放 99s vs 录制 89.0s+9=98s，差 ~1s）→ 按 RIGHT 帧表排 A 键会打在
    # 弹出前（round-11f：第一 A 98.62s 打在 99s 弹出前无效 → 对话滞后 3.7s
    # → 第二对话 A 键不足 → 开闸时对话中 → walk 批方向键全打对话 → 冻结）。
    # A 批锚定弹出确认（top[6:58]>55 + dlg[110:140]>90 + mean≥60 连续 2 帧）
    # → F_dlg1 读帧 → A 键按录制相对时刻（89.625s 第一 A = 弹出+0.6s）入队。
    F_wake = None           # 起床段帧锚（84.25s RIGHT 前读 currentFrame）
    F_wake_at_ms = 0        # F_wake 读取时的墙钟 game_ms（帧换算基准）
    F_sleep = None          # v10.4：睡眠起点帧锚（暗场景首帧 mean<30，RIGHT 批新锚）
    last_sleep_chk = 0.0    # v10.4：睡眠起点检测节流（~0.15s）
    right_batch_sent = False  # RIGHT 唤醒批已按帧表驱动（84-89s）
    a_batch_sent = False      # 对话 A 批已按帧表驱动（89-106.5s，弹出确认后）
    F_dlg1 = None             # 第一对话弹出确认帧（A 批锚点）
    dlg1_conf = 0             # 弹出确认连续帧计数（2 帧确认）
    last_dlg1_chk = 0.0       # 弹出检测节流（~0.4s）
    last_wake_frame = 0       # RIGHT 批末键目标帧（诊断用）
    last_a_frame = 0          # A 批末键目标帧（v6：开闸判定基准——round-11g
                              # 误用 last_wake_frame（6594+30=6624）开闸过早：
                              # f=7173 时 A 批才推到录制 94.6s，第二对话 A×9
                              # 未推 → walk 批与 A 批 sched 重叠 + 对话中方向
                              # 键无效 → 玩家冻结 96→176px 中止）
    dlg2_seen = False       # fix14e：第二对话曾出现（自愈触发过）
    dlg2_clear = 0          # fix14e：连续判定「不在对话」计数（3 次→走路段开始）
    last_frame_mean = 0.0   # 最近抓屏整帧亮度（开闸亮度门控用）
    # 走路段帧调度状态（--walk-lua/--probe-walk，2026-08-08 socket 方案）
    chan = None             # SchedChannel（None=通道未建/失败 → 走路段回退 PostMessage）
    F_gate = None           # 开闸时刻游戏帧锚点（None=未锚定）
    pred_x = pred_y = 0     # 键积分预测坐标（每次地图变化重锚）
    last_map = (-1, -1)     # 上次坐标反馈时的地图 (bank, id)
    held = 0                # 帧调度累计 held 掩码
    last_coord_chk = -10**9  # 坐标反馈节流（~1s）
    # 走路段批量调度状态（2026-08-08 探针后推演：逐键到期调度必然迟到 1 帧
    # → 键永不生效；开闸时一次性入队整个走路段，帧表驱动）
    walk_batch_sent = False
    walk_traj = []          # 批量计划轨迹 [(up帧, dx, dy)]——坐标反馈按帧推进
    traj_idx = 0            # walk_traj 已计入位移的条目数
    anchor_x = anchor_y = 0  # 坐标反馈锚点（地图变化重锚）
    warp_waiting = False    # 第九轮：坐标误差>阈值但画面黑屏 = 楼梯 warp 转场
                            # 中（坐标冻结在触发位置是转场特征，见 1520 行重锚
                            # 分支注释）——豁免报警，等落点加载（画面恢复/坐标
                            # 跳变/地图变化）后重锚；黑屏 >6s = 真锁中止
    warp_since = 0.0        # warp_waiting 起始墙钟（黑屏超时判定）
    alarm_observe = False   # 第十轮：非黑屏坐标误差的 2s 转场观察期——第九轮
                            # 实测 abort 掐在转场尾巴（误差报警时画面恰好回升
                            # 到亮，mean<40 判据错过）；观察期坐标跳变=转场
                            # 完成重锚继续，2s 仍冻结=真锁中止
    alarm_observe_since = 0.0
    alarm_observe_pos = (-1, -1)
    lua = LuaInjector(hwnd, proc.pid if proc else None)
    lua_active = False
    kb_done = False   # 键盘屏段状态机已接管
    kb_det_ms = 0.0   # 键盘屏检测墙钟（monotonic）

    # 走路段帧调度预载（--walk-lua/--probe-walk）：把 load_sched_channel 的
    # ~3-5s 阻塞从 45.19s 键盘屏段起点挪到启动空闲期（0-45.18s 无键，游戏在
    # 命名屏等待，延迟被吸收无漂移）。2026-08-08 探针实证：45.19s 处阻塞 →
    # 键盘屏段推后 ~3s → fix7 焦点沉淀链（66-84s 空闲期）被压缩 → 焦点恢复
    # （实测 15-25s 抖动）越过 95.5s 唤醒重试窗口 → 录制 RIGHT 84.25s 无效
    # + 重试 ×3 无效（mean 22.8 黑屏）→ 唤醒永不触发 → 走路段门控不开 →
    # 301s mGBA 崩溃。预载后 45.19s 零阻塞，键盘屏段节奏与 fix14f 时代一致
    if (args.walk_lua or args.probe_walk or args.probe_freeze) and chan is None:
        # 必须先 prepare()（开「脚本」窗口）再粘贴——2026-08-08 实证：漏调
        # prepare 时 lua.sv 为空 → _paste_clipboard 立即 False → 预载全败
        try:
            if lua.prepare():
                chan = load_sched_channel(lua)
            else:
                print("  ⚠️ 走路段调度通道预载：脚本窗口打开失败", flush=True)
        except Exception as e:
            print(f"  ✗ 走路段调度通道预载异常: {e}", flush=True)
            chan = None
        if chan is None:
            # 预载失败不中止：41.2s 的 LUA_PREPARE 分支（lua.ready=False 时）
            # 会重试 prepare，45.19s 键盘屏段起点再兜底加载（两次探针实证
            # 45.19s 处加载成功过——启动期菜单/窗口未稳定可能是暂时性）
            print("  ⚠️ 走路段调度通道预载失败——45.19s 键盘屏段起点重试",
                  flush=True)

    def safe_send(vk: int, up: bool) -> bool:
        """PostMessage 发送 + 句柄失效自愈。False = 无法恢复（调用方应中止）。

        2026-08-08 全段实证：301s 处 mGBA 窗口销毁 → send_vk 抛 1400 无效句柄
        → 整段崩溃。恢复策略：进程已死 → 报错中止；进程活着 → FindWindow 重找
        （mGBA 崩溃重启/窗口重建场景），新句柄则更新并重试一次；都失败 → 报错
        中止。capture_hwnd 已自愈（异常返回 None），无需此防护。
        """
        nonlocal hwnd
        try:
            window_backend.send_vk(vk, up, hwnd=hwnd)
            return True
        except Exception as e:
            if not (getattr(e, "args", None) and e.args[0] == 1400):
                raise
        # 1400：窗口句柄失效（mGBA 崩溃/窗口销毁）
        if proc is not None and proc.poll() is not None:
            print(f"✗ mGBA 进程已退出（code={proc.poll()}）——回放中止",
                  flush=True)
            return False
        new = window_backend.find_window(ROM_NAME)
        if new and new != hwnd:
            hwnd = new
            print(f"  ↺ 窗口句柄重找: {hwnd:#x}，重试发送", flush=True)
            window_backend.send_vk(vk, up, hwnd=hwnd)
            return True
        print(f"✗ 窗口句柄失效且重找失败（hwnd={hwnd:#x}）——回放中止",
              flush=True)
        return False

    def _open_gate():
        """对话关闭确认后立即开闸（fix14e 3 次判定 & fix14c 补 A 复查共用）：
        设 walk_offset + 帧锚定 + 走路段批量入队。返回 "probe_break" 时调用方
        break（探针模式诊断完即止）。"""
        nonlocal walk_offset, F_gate, pred_x, pred_y, anchor_x, anchor_y
        nonlocal traj_idx, walk_batch_sent, last_map, chan, walk_traj
        walk_offset = int(game_ms) - WALK_KEY_ABS
        print(f"  🚪 走路段开闸（{game_ms - t_base}ms，walk_offset={walk_offset}ms）",
              flush=True)
        if (args.walk_lua or args.probe_walk or args.probe_freeze) and chan is not None:
            F_gate = chan.read_frame()
            gx = chan.read_u16(PLAYER_X)
            gy = chan.read_u16(PLAYER_Y)
            if F_gate is not None and gx is not None and gy is not None:
                pred_x, pred_y = gx, gy
                bnk = chan.read_u16(MAP_BANK)
                mid = chan.read_u16(MAP_ID)
                last_map = (bnk & 0xFF, mid & 0xFF) if bnk and mid else (-1, -1)
                print(f"  🔗 走路段帧锚定 F_gate={F_gate} pos=({gx},{gy}) "
                      f"map={last_map}", flush=True)
                if args.probe_walk:
                    report, ok = run_probe(chan, keys, F_gate, gx, gy)
                    print(report)
                    print(f"⏹ 探针模式：{'✅ 通过' if ok else '✗ 未通过'}"
                          f"——中止回放（诊断）", flush=True)
                    return "probe_break"
                if args.probe_freeze:
                    # cap 回调：每次坐标读取后抓屏，帧名沿用 game_ms 轴
                    # （t{abs:07d}，含 t_base 偏移）——坐标与画面同帧存档，
                    # 事后可标定相机/精灵偏移
                    def probe_cap(_f=None):
                        img_f = window_backend.capture_hwnd(hwnd)
                        if img_f is not None and run_dir is not None:
                            now_ms = int((time.monotonic() - t_start)
                                         * 1000 * args.speed) + t_base
                            Image.fromarray(img_f).save(
                                run_dir / f"t{now_ms:07d}.png")
                    report, ok = run_freeze_probe(chan, keys, F_gate, gx, gy,
                                                  cap=probe_cap)
                    print(report)
                    print("⏹ 冻结探针完成——中止回放（诊断）", flush=True)
                    return "probe_break"
                # --walk-lua：整个走路段批量提前入队（探针 _plan_walk 同款逻辑）
                # v10.3：walk_keys 从 WALK_KEY_START（出门后第一 RIGHT）起——
                # 下床 DOWN（106844-108282）已并入 A 批帧表，不在走路段重复；
                # 帧锚定 F_dlg1（与 A 批同轴，anchor_ms=89000）→ walk 首键帧
                # = F_dlg1+1225 = DOWN up（F_dlg1+1156）+ 69 帧，精确复刻录制
                # 108282→109438 的 1.156s gap。F_dlg1 缺失（非 A 批回退路径）
                # 时回退旧锚定（F_gate + 首键即发）。
                walk_keys = [k for k in keys if k["t"] >= WALK_KEY_START]
                if F_dlg1 is not None:
                    events, (px, py), walk_traj = _plan_walk(
                        walk_keys, F_dlg1, gx, gy, anchor_ms=89000)
                else:
                    events, (px, py), walk_traj = _plan_walk(
                        walk_keys, F_gate, gx, gy)
                batch_ok = True
                for f_ev, m, _n, _k in events:
                    if not chan.schedule(f_ev, m):
                        batch_ok = False
                        break
                if not batch_ok:
                    print("  ✗ 走路段批量入队失败（通道中断）——中止", flush=True)
                    raise ReplayWindowLost()
                pred_x, pred_y = px, py
                anchor_x, anchor_y = gx, gy
                traj_idx = 0
                walk_batch_sent = True
                print(f"  🚶 走路段批量入队 {len(events)} 事件（{len(walk_keys)} "
                      f"键，帧跨度 {events[0][0] - F_gate}.."
                      f"{events[-1][0] - F_gate}，轨迹 {len(walk_traj)} 步，"
                      f"终点预测 ({px},{py})）", flush=True)
                # 第六轮诊断：批量事件前段详情（帧偏移/掩码/键名/类型）——
                # 第一段 DOWN 出门键的按下/释放帧是否与预期一致
                first8 = [(ev[0] - F_gate, ev[1], ev[2], ev[3]) for ev in events[:8]]
                print(f"  🧾 批量事件前 8: {first8}", flush=True)
                traj0 = [(tf - F_gate, dx, dy) for tf, dx, dy in walk_traj[:4]]
                print(f"  🧾 轨迹前 4: {traj0}", flush=True)
            else:
                print("  ⚠️ 帧锚定失败（通道异常）——走路段回退 PostMessage",
                      flush=True)
                chan = None
        return None

    try:
        t_start = time.monotonic()
        i = 0
        while True:
            # 进程存活监控：mGBA 退出（崩溃/被关）→ 立即中止，避免无效句柄
            # 打键/抓屏空转整段（301s 崩溃前画面已冻结 4.6s，此处可提前发现）
            if proc is not None and proc.poll() is not None:
                print(f"✗ mGBA 进程已退出（code={proc.poll()}）——回放中止于 "
                      f"{int((time.monotonic() - t_start) * 1000) + t_base - t_base}ms",
                      flush=True)
                break
            game_ms = int((time.monotonic() - t_start) * 1000 * args.speed) + t_base
            now = time.monotonic()  # v5：循环顶部定义（A 批弹出确认块在其后使用）
            if args.to is not None and game_ms - t_base > args.to * 1000:
                break
            # v10.4（2026-08-08）：睡眠起点检测 + RIGHT 批入队（唤醒相位根治）。
            # round-19/20 证据链：F_wake 锚定 RIGHT 相位 ~21.6-21.9s，压在 386
            # hack 起床站位分支边界（round-20 差 0.2s → (136,112) → 第二对话截断
            # → 提前瞬移 2F 楼梯口）。改锚定检测到的睡眠起点（暗场景首帧 mean<30
            # → F_sleep）+ 录制相位（RIGHT 84250 − 睡眠 66547 = 17.7s = 1122 帧
            # @63.4fps）→ 回放相位恒定 17.7s，离边界 ~4s。检测到即入队（不等
            # 83s 窗口——目标帧按 fps 可能早到被丢）。检测窗口 66000-83000：
            # 下界 = 妈妈对话末键（65.8s）后，上界 < F_wake 读窗（83000）；
            # mean<30 判定：睡眠场景 8-24、妈妈对话 52.3、唤醒场景 80.9。
            if (not right_batch_sent and F_sleep is None and chan is not None
                    and 66000 <= game_ms <= 83000
                    and now - last_sleep_chk > 0.15):
                last_sleep_chk = now
                img_s = window_backend.capture_hwnd(hwnd)
                if img_s is not None and float(np.asarray(img_s).mean()) < 30:
                    F_sleep = chan.read_frame()
                    if F_sleep is not None:
                        right_keys = [k for k in keys_full
                                      if 84000 <= k["t"] < 89000
                                      and k["name"] in VK2LUA]
                        held_w = 0
                        batch_ok = True
                        last_wake_frame = 0
                        for kk in right_keys:
                            bit = 1 << VK2LUA[kk["name"]]
                            if kk["down"]:
                                held_w |= bit
                            else:
                                held_w &= ~bit
                            # 相位 = 录制 RIGHT 相对睡眠起点（无 WAKE_SHIFT——
                            # 锚定吸收键盘屏段冻结/帧率波动）
                            tgt = F_sleep + round(
                                (kk["t"] - S_SLEEP_MS) * FPS_REC / 1000.0) - 1
                            last_wake_frame = tgt
                            if not chan.schedule(tgt, held_w):
                                batch_ok = False
                                break
                        if batch_ok:
                            right_batch_sent = True
                            lua_active = False  # 键盘屏段语义补位（同 F_wake 块）
                            print(f"  🌙 睡眠起点检测 → RIGHT 批入队："
                                  f"F_sleep={F_sleep}（{game_ms - t_base}ms），"
                                  f"{len(right_keys)} 键（相位 "
                                  f"{((RIGHT_MS - S_SLEEP_MS) * FPS_REC / 1000):.0f}"
                                  f" 帧，末键 +{last_wake_frame - F_sleep}）",
                                  flush=True)
                        else:
                            F_sleep = None  # 入队失败：回退 F_wake 路径
                            print("  ⚠️ F_sleep RIGHT 批入队失败——回退 F_wake",
                                  flush=True)
            # 起床段帧调度（第 11 轮，2026-08-08）：84.25s RIGHT 起批量入队
            # 起床段键（RIGHT hold → 第一对话 A×8 → 转场 → 第二对话 A×9）。
            # 根因链：PostMessage 焦点养焦抖动 15-25s（fix13 实测）→ RIGHT
            # 唤醒晚 ~6s（RIGHT×5 mean 22.9 恒定打空到 90s）→ 起床/对话整体
            # 顺延 → 开闸 (120,96)（录制 (120,112)）→ DOWN 1 格撞 2F 剧情锁
            # 全方向锁死（探针实证 Δ0×4）。帧表复刻录制键序（Lua 核心注入，
            # 无焦点依赖）→ 对话推进与录制同步 → 开闸站位/剧情锁与录制一致。
            # 帧锚 F_wake 读于 RIGHT 前；后续键按录制 t 差换算帧（同走路段
            # sched_frame 机制——目标激活帧 G 的 G−1，锚定误差不累积）。
            # 锚定窗口 = 83000-84200：上界必须 ≤84250-1/0.06≈84234（否则
            # RIGHT 目标帧落在锚点之前被丢——round-11d 读于 84010 刚够，
            # 主循环延迟大时必挂）；下界 83000 时睡眠场景已激活（round-11d
            # 82.1s 帧已验证睡眠 mean 22.3）。
            if (not right_batch_sent and F_wake is None and chan is not None
                    and 83000 <= game_ms <= 84200):
                F_wake = chan.read_frame()
                if F_wake is not None:
                    F_wake_at_ms = game_ms
                    # v5：RIGHT 批 = 84.2-89s（RIGHT 84.25s down→85.375s up，
                    # 平移 +9000 → 93.25s 长按 1.125s 唤醒）；对话 A 批（89.6-
                    # 106.4s）在弹出确认后单独入队（见下块）
                    right_keys = [k for k in keys_full
                                  if 84000 <= k["t"] < 89000
                                  and k["name"] in VK2LUA]
                    held_w = 0
                    batch_ok = True
                    last_wake_frame = 0
                    for kk in right_keys:
                        bit = 1 << VK2LUA[kk["name"]]
                        if kk["down"]:
                            held_w |= bit
                        else:
                            held_w &= ~bit
                        # 第 11 轮 v4：录制时间 + WAKE_SHIFT_MS（见常量注释——
                        # 回放睡眠晚到，RIGHT/对话键必须整体后移落在正确状态上）
                        tgt = (F_wake
                               + round((kk["t"] + WAKE_SHIFT_MS
                                        - F_wake_at_ms) * 0.06) - 1)
                        last_wake_frame = tgt
                        if not chan.schedule(tgt, held_w):
                            batch_ok = False
                            break
                    if batch_ok:
                        right_batch_sent = True
                        lua_active = False  # 键盘屏段正式结束（恢复块被键循环
                                            # break 跳过，这里补上语义）
                        print(f"  🚪 起床段 RIGHT 批入队：F_wake={F_wake}，"
                              f"{len(right_keys)} 键"
                              f"（{right_keys[0]['t'] / 1000:.1f}-"
                              f"{right_keys[-1]['t'] / 1000:.1f}s，"
                              f"末键帧 +{last_wake_frame - F_wake}）", flush=True)
                    else:
                        F_wake = None  # 入队失败：回退 PostMessage 逐键
                        print("  ⚠️ RIGHT 批入队失败——回退 PostMessage",
                              flush=True)
            # 第一对话弹出确认 + A 批动态入队（第 11 轮 v5，2026-08-08）：
            # RIGHT 唤醒响应波动（round-11f 实测 +1.5-1.9s）→ 对话弹出浮动
            # → 帧表 A 键按 RIGHT 锚排会打在弹出前（round-11f：98.62s A 打在
            # 99s 弹出前 → 对话滞后 3.7s → 第二对话 A 键不足 → 开闸时对话中
            # → walk 批全打对话 → 冻结）。弹出特征 = top[6:58]>55（卧室场景，
            # 睡眠/再睡框暗 top 不满足）+ dlg[110:140]>150（对话框白底）+
            # mean≥60，连续 2 帧确认 → F_dlg1 读帧 → A 键按录制相对时刻
            # v10.6（round-22 根因修复）：判定条带 dlg[110:140] → y[124:158]。
            # v10.5 把阈值 90→150 修过头：round-22 实锤白盒 dlg[110:140] 只有
            # 137.8-146.3——y110-124 的 14 行房间条带（~90）混入拉低，阈值 150
            # 永远达不到 → A 批从未入队 → 对话 1 靠 fix14c 慢推晚关 19s →
            # 自动瞬移 2F 楼梯口 → 第二对话锁 → walk 冻结 (120,112) 中止。
            # 改用 y[124:158] 白盒核心条带（round-22 实测）：盒期 179.7-192.5
            # （对话 1）/182.5-189.9（对话 2），无盒卧室 87.6-90.2——阈值 150
            # 分离余量 ~90，是 dlg[110:140] 的 2 倍。round-21 误触发（92.9）与
            # 真盒（137.8）在旧条带的缝隙被新条带完全拉开。
            # （89.625s 第一 A = 弹出 +0.6s，录制 89.0s 弹出实测）入队——
            # 锚定误差不累积（每键都是相对偏移），句边界与录制对齐。
            if (right_batch_sent and not a_batch_sent and chan is not None
                    # v10.4：下界 98000 → 87500——F_sleep 锚定后弹出回到录制同轴
                    # （~89.05s：RIGHT 84.3s + 唤醒流 301 帧；录制弹出 89.0s）。
                    # F_wake 回退路径弹出 ~98s 仍被覆盖（上界 115s 足够）。
                    and 87500 <= game_ms <= 115000
                    and now - last_dlg1_chk > 0.4):
                last_dlg1_chk = now
                img_d1 = window_backend.capture_hwnd(hwnd)
                if img_d1 is not None:
                    a1 = np.asarray(img_d1)
                    t_top = float(a1[6:58].mean())
                    t_dlg = float(a1[124:158].mean())  # v10.6：白盒核心条带
                    m1 = float(a1.mean())
                    if t_top > 55 and t_dlg > 150 and m1 >= 60:
                        dlg1_conf += 1
                        if dlg1_conf >= 2 and F_dlg1 is None:
                            F_dlg1 = chan.read_frame()
                            # v10.3：上界 WALK_KEY_ABS → WALK_KEY_START——A 批
                            # 扩展纳入下床 DOWN（106844 down / 108282 up，hold
                            # 86 帧 = 1.43s 复刻录制 1.44s）。round-19 失败链：
                            # A 批推完对话（末键 106.4s）后无 DOWN → 剧情自动
                            # 瞬移 2F 楼梯口 → 冻结。帧表 DOWN 打断瞬移，玩家
                            # 下床节奏与录制帧轴一致（walk 批锚定同轴衔接）。
                            a_keys = [k for k in keys_full
                                      if 89000 <= k["t"] < WALK_KEY_START
                                      and k["name"] in VK2LUA]
                            held_a = 0
                            last_a = 0
                            ok = True
                            for kk in a_keys:
                                bit = 1 << VK2LUA[kk["name"]]
                                if kk["down"]:
                                    held_a |= bit
                                else:
                                    held_a &= ~bit
                                tgt = F_dlg1 + round(
                                    (kk["t"] - 89000) * 0.06) - 1
                                last_a = tgt
                                last_a_frame = tgt
                                if not chan.schedule(tgt, held_a):
                                    ok = False
                                    break
                            if ok:
                                a_batch_sent = True
                                print(f"  💬 第一对话弹出确认（"
                                      f"{game_ms - t_base}ms，top={t_top:.1f} "
                                      f"dlg={t_dlg:.1f} mean={m1:.1f}）→ "
                                      f"A 批入队：F_dlg1={F_dlg1}，"
                                      f"{len(a_keys)} 键（末键帧 "
                                      f"+{last_a - F_dlg1}）", flush=True)
                            else:
                                print("  ⚠️ A 批入队失败——回退 fix11/fix14c 自愈",
                                      flush=True)
                    else:
                        dlg1_conf = 0
            while i < len(keys):
                k = keys[i]
                # 起床段 RIGHT 批：84-89s 键已按帧表驱动，跳过逐键发送
                if right_batch_sent and 84000 <= k["t"] < 89000:
                    i += 1
                    continue
                # 对话 A 批：89-109.4s 键（含下床 DOWN，v10.3）在弹出确认
                # （a_batch_sent）前挂起（break 等确认，POST 不可靠不逐键
                # 发）；入队后跳过逐键发送（帧表已调度，勿重复 PostMessage）
                if 89000 <= k["t"] < WALK_KEY_START:
                    if not a_batch_sent:
                        break
                    i += 1
                    continue
                # fix14e：走路段键动态门控——RIGHT 唤醒晚（焦点养好 ~90s）→
                # 起床/第二对话顺延 → 走路段开始时刻浮动。走路键（abs≥
                # WALK_KEY_ABS）在第二对话自愈确认「对话框稳定消失」前不发
                # （walk_offset=None）；确认后 eff_t = t + walk_offset，与
                # 录制节奏同步（walk_offset = 回放走路开始 - 录制走路开始，
                # 首键 eff_t≈当前 game_ms，不堆积）。
                if k["t"] >= WALK_KEY_ABS:
                    if walk_offset is None:
                        break  # 走路段门控中：等第二对话结束再开闸
                    eff_t = k["t"] + walk_offset
                else:
                    eff_t = k["t"]
                if eff_t > game_ms:
                    break
                # 键盘屏段：切 Lua 注入（PostMessage 无效，2026-08-08 实证）。
                # Lua 区间上界用 LUA_HOLD_MS（66s）而非 LUA_ZONE_MS[1]（62s）：
                # 62-66s 的妈妈对话推进 A×3 走 Lua 连发（PostMessage 在
                # 62.03s 刚关窗恢复后只稳定 ~2 键、65.48s 失效——fix4/5 实证），
                # 66s 后时间驱动关窗恢复 PostMessage（见主循环 restore 块）
                in_lua_zone = not args.no_lua_kb and LUA_ZONE_MS[0] <= k["t"] <= LUA_HOLD_MS
                # 提前准备 Lua 窗口（开窗+聚焦 ~3.5s，避免段内阻塞）。
                # 必须同时查上界：恢复点（LUA_HOLD_MS 后第一键）已 close_window
                # 并置 ready=False，若无上界，恢复后的下一个键会重新打开脚本窗口抢
                # 焦点 → PostMessage 再次全灭 → 62-90s 画面冻结 28s（2026-08-08
                # 全段回放实证；0-115s 验证复现：日志「[Lua] 打开「脚本」窗口...」
                # 出现在「↩ 恢复 PostMessage」之后）。
                if (not args.no_lua_kb and not lua.ready
                        and LUA_ZONE_MS[0] - LUA_PREPARE_MS <= k["t"] <= LUA_HOLD_MS):
                    if not lua.prepare():
                        print("  ✗ Lua 注入窗口准备失败——键盘屏段将无输入", flush=True)
                        lua.ready = True  # 防止每事件重试刷屏（保持 PostMessage 静默失效）
                if in_lua_zone and not lua_active:
                    lua_active = True
                    print(f"  🔧 键盘屏段：切换到 Lua 直注入（t={k['t'] - t_base}ms）",
                          flush=True)
                elif not in_lua_zone and lua_active:
                    lua_active = False
                    if (args.walk_lua and chan is not None
                            and not args.no_lua_kb):
                        # 第 11 轮：起床段帧调度——不关窗保持 Lua 通道，
                        # 84.25s 起床段帧表直接复用 chan。PostMessage 焦点
                        # 养焦抖动（15-25s）导致 RIGHT 唤醒晚 → 起床/对话
                        # 错位 → 剧情锁未解 → DOWN 撞锁（探针实证）；
                        # Lua 核心注入无焦点依赖，帧表复刻录制键序根治。
                        print(f"  ↩ 键盘屏段结束：保持 Lua 通道"
                              f"（起床段帧调度，t={k['t'] - t_base}ms）",
                              flush=True)
                    else:
                        # 关闭「脚本」窗口把焦点还给主窗口。2026-08-08 诊断
                        # 实证：脚本窗口关闭后 Qt 键盘焦点停在「偏离对象」
                        # （OS 前台窗口一直是主窗口，GetForegroundWindow
                        # 检查看不出问题，但 PostMessage 全灭）——立即
                        # SetForegroundWindow 不生效。必须：延时等 Qt 焦点
                        # 迁移 → 置前（触发 WM_ACTIVATE 让 Qt 把焦点还给
                        # 主窗口）→ 再延时，才能恢复 PostMessage。
                        # fix6：此点从 62.03s 移到 90.89s（LUA_HOLD_MS=
                        # 90000），让 62-90s 的键全部走 Lua（无焦点依赖）
                        # ——fix4/fix5 实证 62.03s 刚关窗口的 restore 只
                        # 稳定 ~3 键，90s 处的恢复则长期稳定，故把脆弱切换
                        # 推迟到 90s 再吃稳定窗口。
                        lua.close_window()
                        time.sleep(1.0)
                        _force_foreground(hwnd)
                        time.sleep(0.5)
                        print(f"  ↩ 键盘屏段结束：恢复 PostMessage"
                              f"（t={k['t'] - t_base}ms）", flush=True)
                if in_lua_zone:
                    if not kb_done:
                        kb_done = True
                        if (args.walk_lua or args.probe_walk or args.probe_freeze) and chan is None:
                            # 走路段帧调度前置：剪贴板粘贴加载 sched_server.lua
                            # + TCP 连接（~2.5s）。失败 = 走路段无法帧调度
                            # （回到 PostMessage 分叉状态）→ 立即中止提示重跑
                            chan = load_sched_channel(lua)
                            if chan is None:
                                print(f"✗ 走路段帧调度通道建立失败"
                                      f"（{'探针' if (args.probe_walk or args.probe_freeze) else '--walk-lua'}"
                                      f"模式）——中止回放，请重试", flush=True)
                                raise ReplayWindowLost()
                        i = _kb_phase(lua, hwnd, keys, t_start, t_base,
                                      run_dir if args.verify else None,
                                      kb_advance=args.kb_advance)
                        # 键盘屏段接管完成：i 已定位到恢复时刻后的下一个键
                        continue
                    # 注入前确保 prompt 聚焦（物理点击，2s 缓存，fix4 版——
                    # 不逐命令点击，仅关键点+缓存）。62-66s 期间脚本窗口空闲
                    # 数秒，Qt 焦点可能漂走，Lua 打字会落空
                    lua._ensure_prompt()
                    t0 = time.monotonic()
                    if k["down"]:
                        # down+up 一次完成。fix7：对话 A 短按（<400ms）走连发
                        # 快路径（0.008s/字符，REPL FIFO 250ms/命令执行，执行
                        # 间隙即按住窗口 ≈ 录制 93-234ms 按住）——fix6 实证
                        # 慢路径 1.3s/键序列化交付累积落后 3-4s（对话未完成先
                        # 断流 → 冻结）；方向键等长按住（RIGHT 1.12s）才走
                        # send_pressed 复刻录制时长
                        hold = holds.get((k["name"], k["t"]), 0.15)
                        if hold >= 400:
                            sent = lua.send_pressed(k, hold)
                        else:
                            lua.burst_presses([k["name"]])
                            sent = True
                        # 跳过配对的 up（下一个同名 up 事件）
                        j = i + 1
                        while (j < len(keys) and keys[j]["name"] == k["name"]
                               and not keys[j]["down"]):
                            j += 1
                        i = j
                    else:
                        sent = lua.send(k)  # 孤儿 up（未配对）照发
                        i += 1
                    dt = (time.monotonic() - t0) * 1000
                    if lua_active and dt > 50:
                        print(f"    按键 t={k['t'] - t_base}ms {k['name']:6s} "
                              f"{'down' if k['down'] else 'up'  } Lua注入耗时{dt:.0f}ms",
                              flush=True)
                    if sent:
                        known += 1
                    else:
                        skipped += 1
                    continue
                if chan is not None and F_gate is not None and k["t"] >= WALK_KEY_ABS:
                    if walk_batch_sent:
                        # 走路段已整体提前入队（2026-08-08 批量调度）——全部
                        # 剩余键由帧表驱动，主循环不再逐键发送（逐键到期调度
                        # 目标帧 = 到期帧−1，必然迟到 → 键永不生效的 bug）
                        i = len(keys)
                        continue
                    # 走路段帧级调度（2026-08-08 socket 方案）：down/up 配对按
                    # 帧入队，掩码 = 事件后累计 held 状态；PostMessage 不再参与
                    name = k["name"]
                    bit = 1 << VK2LUA.get(name, -1)
                    if bit < 0:
                        skipped += 1
                        i += 1
                        continue
                    if k["down"]:
                        held |= bit
                        if not chan.schedule(sched_frame(F_gate, k["t"]), held):
                            print(f"  ✗ 调度通道写入失败（走路段 "
                                  f"{k['t'] - t_base}ms {name} down）——中止",
                                  flush=True)
                            break
                        j = i + 1
                        while j < len(keys) and (keys[j]["name"] != name
                                                 or keys[j]["down"]):
                            j += 1
                        if j < len(keys):
                            held &= ~bit
                            if not chan.schedule(sched_frame(F_gate, keys[j]["t"]),
                                                 held):
                                print(f"  ✗ 调度通道写入失败（{name} up）——中止",
                                      flush=True)
                                break
                            i = j + 1
                        else:
                            i += 1
                    else:
                        held &= ~bit
                        if not chan.schedule(sched_frame(F_gate, k["t"]), held):
                            print(f"  ✗ 调度通道写入失败（{name} up）——中止",
                                  flush=True)
                            break
                    known += 1
                    continue
                try:
                    key = Key(k["name"])
                except ValueError:
                    skipped += 1  # 原始标签（BTN<i>/AX<i>±）无法用键盘回放
                    i += 1
                    continue
                # fix16（2026-08-08 第七轮）：第二对话尾段录制 A 键状态门控
                # ——fix11 把起床对话提前推完（103.7s vs 录制 106.4s）后，
                # 录制自身 A 键（104.0-106.4s）落在「对话已关、第二对话未
                # 现」的床边空闲场景 → 386 hack watchdog「A 连按过久」触发
                # 2F 剧情锁 (120,112)（第五/六轮实证：DOWN 只走 1 格即四
                # 方向全锁卡死，录制 A 全打在对话上无锁）。门控：对话盒
                # 可见（fix14e 判定 top∈[75,110] && dlg>90）才发，否则跳过
                # 该 A 及其配对 up（fix11/fix14c 状态驱动自愈已覆盖推进）
                if (key is Key.A and k["down"]
                        and WALK_KEY_ABS - 11000 <= k["t"] < WALK_KEY_ABS):
                    img_g = window_backend.capture_hwnd(hwnd)
                    if img_g is not None:
                        a2g = np.asarray(img_g)
                        g_top = float(a2g[6:58].mean())
                        g_dlg = float(a2g[110:140].mean())
                        if not (75 <= g_top <= 110 and g_dlg > 90):
                            j = i + 1
                            while (j < len(keys) and keys[j]["name"] == "A"
                                   and not keys[j]["down"]):
                                j += 1
                            i = j  # 跳过该 A 及其配对 up，停在下一事件
                            skipped += 1
                            print(f"  ⛔ 床边 A 门控跳过（{k['t'] - t_base}ms，"
                                  f"top={g_top:.1f} dlg={g_dlg:.1f}）", flush=True)
                            continue
                vk = window_backend.VK[key]
                t0 = time.monotonic()
                if not safe_send(vk, up=not k["down"]):
                    raise ReplayWindowLost()
                dt = (time.monotonic() - t0) * 1000
                if 46000 <= k["t"] - t_base <= 52000:
                    print(f"    按键 t={k['t'] - t_base}ms {k['name']:6s} "
                          f"{'down' if k['down'] else 'up'  } game_ms={game_ms} 发送耗时{dt:.0f}ms",
                          flush=True)
                known += 1
                i += 1
                # 追赶模式限速：restore 点（关窗口+WM_ACTIVATE 耗时 ~2.5s）
                # 后堆积的键若瞬间连发，同一帧内多个 A 按下会合并丢键（对话
                # 推进次数缺失 → 后续状态级联错位）——迟到键每发一个等 0.2s，
                # 保证每键落独立帧（A 连按 0.2s 间隙足够）
                if eff_t < game_ms - 300:
                    time.sleep(0.2)
            # fix7：Lua 段结束（LUA_HOLD_MS 后）时间驱动关窗恢复 PostMessage
            # ——在长空闲期（66-84s 无键）完成关窗+WM_ACTIVATE，让 Qt 焦点在
            # 首个 PostMessage 键（83.95s RIGHT）前充分沉淀。fix5 实证：62.03s
            # 刚关窗的恢复只稳定 ~2 键（65.48s A 失效），90s 长沉淀恢复则长期
            # 稳定（89.33-94.81 A×8 全生效）——恢复点必须赶在长空闲期。
            if lua_active and game_ms > LUA_HOLD_MS and i < len(keys):
                lua_active = False
                # fix14b 自愈推进（kb_phase 失败兜底）：画面 mean>60（键盘屏/
                # 妈妈对话）→ Lua 补 A×2（1.3s 间隔）直到连续 4 次抓帧黑屏
                # （转场/睡眠 <60 稳定 8s）——键盘屏 A=确认、对话 A=推进，均
                # 无害推进；黑屏中不注入（A 打黑屏浪费）。睡眠场景 22.9 稳定
                # 黑屏 → 8s 后停；妈妈对话完成 → 转场黑屏 → 睡眠 → 停。
                # fix14 实证：kb_phase 失败时 74.3s 画面黑屏（名字确认转场中），
                # 原 4 轮循环立即 break → 转场后妈妈对话（80.1）无人推进 →
                # RIGHT 重试被 80.1 挡住（条件 <60/66-70 不满足）→ 唤醒永远
                # 不触发。计数 4 次（8s）防止长转场（fix13 参考 4.1s）误 break。
                # 第 11 轮 v3：round-11 实证 kb_phase 的 A×6 落后 ~2-3 行
                # （模块注释早有记录），录制 60.3-65.8s 的 4 次 A 不够关对话
                # → 妈妈对话停在 P-2/P-3 → 睡眠场景晚到 ~100s（回放 105.1s
                # 帧与录制 81.0s 帧 diff 0.003 像素级吻合）→ 帧表 RIGHT
                # （84.25s）打在妈妈对话上无效 → 起床/走路全链 23s 顺延全废。
                # fix14b 补 A×2 正是缺口（fix14 实证 74.3s 推过）；walk-lua
                # 路径此前被整体门控误杀，v3 恢复自愈、仅跳过 close_window
                # （保留 Lua 通道给起床段帧表）。
                time.sleep(1.2)
                blk = 0
                for _ in range(14):
                    img = window_backend.capture_hwnd(hwnd)
                    if img is None:
                        break
                    if float(np.asarray(img).mean()) < 60:
                        blk += 1
                        if blk >= 4:
                            break
                        time.sleep(2.0)
                        continue
                    blk = 0
                    lua._ensure_prompt(force=False)
                    lua.burst_presses(["A"] * 2)
                    time.sleep(1.3)
                if (args.walk_lua and chan is not None
                        and not args.no_lua_kb):
                    # walk-lua：保留 Lua 通道（起床段帧表 + 走路段帧表复用），
                    # 只关 lua_active 语义。焦点不再还给主窗口——PostMessage
                    # 路径 84-106.5s 键全由帧表驱动，不需要焦点。
                    print(f"  ↩ 键盘屏段结束：保持 Lua 通道（fix14b 自愈已"
                          f"推完对话，game_ms={game_ms - t_base}ms）",
                          flush=True)
                else:
                    lua.close_window()
                    time.sleep(1.0)
                    _force_foreground(hwnd)
                    time.sleep(0.5)
                    print(f"  ↩ 键盘屏段结束：恢复 PostMessage"
                          f"（game_ms={game_ms - t_base}ms，"
                          f"下个键 {keys[i]['t'] - t_base}ms）", flush=True)
            # 抓屏（验证/检查用，与录制同节奏）
            if args.verify and game_ms - last_cap_ms >= CAP_INTERVAL_MS:
                last_cap_ms = game_ms
                t0 = time.monotonic()
                img = window_backend.capture_hwnd(hwnd)
                cap_dt = (time.monotonic() - t0) * 1000
                if img is not None:
                    last_frame_mean = float(np.asarray(img).mean())
                    Image.fromarray(img).save(run_dir / f"t{game_ms:07d}.png")
                if 46000 <= game_ms - t_base <= 52000:
                    print(f"    抓屏 game_ms={game_ms - t_base}ms 耗时{cap_dt:.0f}ms", flush=True)
            # fix14：RIGHT 唤醒画面驱动重试——fix13 实证养焦速度每次运行
            # 抖动巨大（74.3s 恢复后 15s 就好，fix8-12 要 23-25s）→ 重试
            # 窗口必须长于抖动范围。drop A×8（fix14）后无「再睡」对话框
            # 污染（mean 66-70 不再出现），84.5-95.5s 只要画面在睡眠
            # （mean<60）就长按 1.2s 重发 RIGHT，打到醒为止。唤醒后画面
            # mean 88-110（房间）→ 条件不满足自动停。长按复刻录制 hold
            # 1.12s（fix13 假设：唤醒是长按触发）。
            # 窗口上界 95500→100000→118000→135000（2026-08-08 探针实证：45.19s
            # 阻塞推后 restore 点后，焦点恢复越过 95.5s 窗口、唤醒永不触发；延长
            # 到 100s 多给恢复余量。批量调度验证再延长：补 A 单发化后若对话推完
            # 时多打 A 触发「上床」暗场景（mean 58 静止，112-116s）→ RIGHT 长按
            # 唤醒兜底。条件有 mean<60/66-70 门控，醒后自动停，无副作用。
            # walk_offset is None（未开闸）才唤醒：开闸后走路段转场黑屏
            # （mean 8-58）不得误触发 RIGHT 干扰帧表键。
            # 2026-08-08 第三轮：暗场景（mean 40-60，疑似上床/错房间）RIGHT 单键
            # 无效（117.1s 实测 mean 仍 58）→ 轮换试探 A→START→RIGHT（每轮换键，
            # 1.4s 节流，18s 窗口约 12 次试探）。A 在床上可能弹「再睡」框
            # （mean 66-70 → 下轮 RIGHT 关框）；START 可能开菜单。试探后打印
            # mean 变化，哪个键能拉回 mean>=60 即生效。
            if (not lua_active and not right_batch_sent
                    and 84500 <= game_ms <= 135000
                    and walk_offset is None and now - last_wake_retry > 1.4):
                img_w = window_backend.capture_hwnd(hwnd)
                if img_w is not None:
                    m = float(np.asarray(img_w).mean())
                    # 暗场景探测后防残留：上轮试探 A/START 后画面变亮（mean>=60
                    # 非 66-70）→ 可能是菜单/对话框被打开 → B 短点按关闭（B 在
                    # 正常场景/房间无副作用；正确唤醒的亮场景打 B 也无害）
                    if (dark_last_key is not None and m >= 60
                            and not (66 <= m <= 70)):
                        dark_last_key = None
                        if not safe_send(window_backend.VK[Key.B], False):
                            raise ReplayWindowLost()
                        time.sleep(0.12)
                        if not safe_send(window_backend.VK[Key.B], True):
                            raise ReplayWindowLost()
                        print(f"  ↩ 暗场景试探防残留：B 关菜单/框（{game_ms - t_base}ms，"
                              f"mean={m:.1f}）", flush=True)
                        last_wake_retry = now
                    elif m < 60 or 66 <= m <= 70:
                        last_wake_retry = now
                        if 40 <= m <= 60 and not dlg2_seen:
                            # 转场/起床动画中的暗（第二对话未出现）——不探测
                            # （第四轮：104.1s 转场黑屏曾被误判为暗场景，浪费
                            # 探测轮次打 A 在转场上）
                            print(f"  · 转场暗画面不探测（{game_ms - t_base}ms，"
                                  f"mean={m:.1f}）", flush=True)
                        elif 40 <= m <= 60:
                            # 暗场景（上床/错房间）——轮换试探 A/START/RIGHT
                            key = (Key.A, Key.START, Key.RIGHT)[dark_try_i % 3]
                            dark_try_i += 1
                            dark_last_key = key
                            name = {Key.A: "A", Key.START: "START",
                                    Key.RIGHT: "RIGHT"}[key]
                            if not safe_send(window_backend.VK[key], False):
                                raise ReplayWindowLost()
                            time.sleep(1.2)
                            if not safe_send(window_backend.VK[key], True):
                                raise ReplayWindowLost()
                            print(f"  🎲 暗场景试探 {name}（{game_ms - t_base}ms，"
                                  f"mean={m:.1f}，轮换#{dark_try_i}）", flush=True)
                        else:
                            if not safe_send(window_backend.VK[Key.RIGHT], False):
                                raise ReplayWindowLost()
                            time.sleep(1.2)
                            if not safe_send(window_backend.VK[Key.RIGHT], True):
                                raise ReplayWindowLost()
                            print(f"  ↻ RIGHT 唤醒重试（{game_ms - t_base}ms，mean={m:.1f}）",
                                  flush=True)
                    else:
                        last_wake_retry = now  # 已唤醒：节流 1.4s 内不再查
            # 开闸前坐标诊断（2026-08-08 第三轮：暗场景卡死时读玩家坐标，
            # 区分「床上」（坐标静止=站立点）vs「错房间」（坐标可动）——
            # 决定脱困键选择。每 2s 一次，不阻塞主循环）
            if (walk_offset is None and chan is not None
                    and game_ms - t_base >= 104000
                    and now - last_coord_diag > 2.0):
                last_coord_diag = now
                cxx = chan.read_u16(PLAYER_X)
                cyy = chan.read_u16(PLAYER_Y)
                if cxx is not None and cyy is not None:
                    print(f"  📍 开闸前坐标 ({cxx},{cyy}) mean={last_frame_mean:.1f} "
                          f"({game_ms - t_base}ms)", flush=True)
            # fix11：起床对话段差盒自愈——95.5-104.5s 若画面仍亮（RIGHT 唤醒后
            # A×8 剩余键推进可能差盒）→ 补 A×2 推进。
            # 2026-08-08 第八轮失败教训：判定改为行级对话盒检查（75<=top<=110
            # 且 dlg>90）后零注入——床边镜头下的起床对话-打开场景 top=124.6
            # 不合格 → 起床对话从未被推进 → 玩家冻结 60s+，第二对话/闸门/
            # 走路全部不发生。回放起床对话**必须**靠 fix11 注入（录制 8 次 A
            # 落在延迟唤醒后的起床动画上无效；fix16 门控又挡住剩余 A）。
            # 第十轮门控修正：mean 从 >85 收紧到 >120——第九轮实测对话推进中
            # mean 126-130（95.2-103.0s），对话关后 mean 115.0-115.3（103.0-
            # 103.7s）——mean>85 把最后 4 个 A（103.0-103.7s ×2）打在「起床
            # 对话已关的床边场景」→ 疑为 2F 剧情锁触发器（玩家从 (120,96)
            # DOWN 1 格到 (120,112) 后输入全失效，录制同路径走 6 格无碍；
            # 录制 43 次 A 全在对话开着时按，从不打空）。mean>120 只在对话
            # 确实开着时注入，打空场景直接停。
            # 保留转场黑屏停（a8_black_seen，防第二对话双推）与 Lua 帧注入
            # （0.7s 节流，不受焦点影响）；chan 不可用时 PostMessage 兜底
            if (not lua_active and not a_batch_sent
                    and 95500 <= game_ms <= 104500
                    and not a8_black_seen and now - last_a8_retry > 0.7
                    and a8_spam < A8_SPAM_CAP):
                img_a = window_backend.capture_hwnd(hwnd)
                if img_a is not None:
                    a2 = np.asarray(img_a)
                    m = float(a2.mean())
                    if m < 60:
                        a8_black_seen = True
                        last_a8_retry = now
                        print(f"  ⏹ 起床对话段转场黑屏（{game_ms - t_base}ms，"
                              f"mean={m:.1f}）", flush=True)
                    elif m > 120:
                        last_a8_retry = now
                        a8_spam += 2
                        if chan is not None:
                            f0 = chan.read_frame()
                            if f0 is not None:
                                # Lua 帧注入 A×2：2 帧点击 + 8 帧间隔
                                # （一次点击=一次对话推进，不触发快进）
                                for off, msk in ((2, 1), (4, 0), (10, 1), (12, 0)):
                                    chan.schedule(f0 + off, msk)
                                print(f"  ⚡ A×2 Lua 帧注入推进（{game_ms - t_base}ms，"
                                      f"mean={m:.1f}）", flush=True)
                            else:
                                # 读帧失败：PostMessage 兜底
                                if not safe_send(window_backend.VK[Key.A], False):
                                    raise ReplayWindowLost()
                                time.sleep(0.12)
                                if not safe_send(window_backend.VK[Key.A], True):
                                    raise ReplayWindowLost()
                                print(f"  ↻ A×1 补推进（PM 兜底，{game_ms - t_base}ms，"
                                      f"mean={m:.1f}）", flush=True)
                        else:
                            if not safe_send(window_backend.VK[Key.A], False):
                                raise ReplayWindowLost()
                            time.sleep(0.12)
                            if not safe_send(window_backend.VK[Key.A], True):
                                raise ReplayWindowLost()
                            time.sleep(0.15)
                            if not safe_send(window_backend.VK[Key.A], False):
                                raise ReplayWindowLost()
                            time.sleep(0.12)
                            if not safe_send(window_backend.VK[Key.A], True):
                                raise ReplayWindowLost()
                            print(f"  ↻ A×2 补推进（{game_ms - t_base}ms，mean={m:.1f}）",
                                  flush=True)
                    else:
                        last_a8_retry = now  # 非对话（转场中/室外）：节流内不再查
            # fix14c v7（2026-08-08）：帧表 A 批的画面兜底——round-12 实证
            # 第一对话第 8 个 A（帧 7209）推进失败 → 残留 1 句停留 3.5s
            # （dlg=129.5 恒定）→ 第二对话批首键（107.9s）被消耗推残留句 →
            # 第二对话弹出晚 ~3.5s（111.4s vs 预期 107.9s）→ A 批键已打空
            # 大半 → 第二对话只推 4 句停留 → walk DOWN 打在对话中无效 →
            # 冻结 (120,112)。修复：A 批推完后画面检测「对话残留」→ Lua 补
            # A 单发（帧表同通道，无焦点依赖）。两档判定（实测特征值）：
            # ① 第一对话残留：dlg>125（白底对话框，实测 129.5）——window
            #    下界 104500 已保证第一对话 A 键（末键墙钟 104.0s）全推完，
            #    补 A 不双推
            # ② 第二对话残留：dlg>100（第二对话弹出实测 102）+ f>last_a_frame
            #    （A 批键序已尽）——键序已尽，补 A 只推进不双推
            # 开闸仍由帧表（last_a_frame+30，见下）；fix14e 画面开闸
            # （dlg2_clear>=3）在 A 批体系下禁用——2F 室内空闲 top≈96 dlg≈94
            # 恒满足判定 → 误开闸（round-11 v1 实证），见 elif 门控。
            # v8：节流用独立 last_fix14c_retry（round-14 饿死实证，见 865 行）。
            # v10.3（round-20）：A 批模式（a_batch_sent）下整个块禁用——
            # round-19 失败链闭合：A 批帧锚定（F_dlg1 + 录制相对偏移）本来就
            # 能推完对话 1+2，fix14c 补推进（104.2s A×2）打在第二对话尾段 =
            # 多余 A → 对话内容错位 → 107.3s 剧情瞬移 2F 楼梯口 → 冻结。
            # 帧表驱动下对话推进与录制帧轴同步，无需画面兜底（round-12 的
            # 残留实证属于 A 批锚定不完善的旧时代）。回退路径（A 批未入队）
            # 保留 fix14c 兜底 + fix14e 画面开闸（elif 分支原有门控）。
            if (not lua_active and not a_batch_sent
                    and 104500 <= game_ms <= 132000
                    and now - last_fix14c_retry > 1.2 and a8_spam < A8_SPAM_CAP):
                img_d2 = window_backend.capture_hwnd(hwnd)
                if img_d2 is not None:
                    a2 = np.asarray(img_d2)
                    t_top = float(a2[6:58].mean())
                    t_dlg = float(a2[110:140].mean())
                    f_now = chan.read_frame() if chan is not None else None
                    need_a = False
                    if walk_offset is None and 75 <= t_top <= 110:
                        # v8：第一档阈值 125→120——round-14 实测实时捕获
                        # PrintWindow 偶发偏小（第二对话残留 top 102.1→96.0、
                        # dlg 98.3→96.3），125 余量 4.5 会被吞；120 余量 9.5
                        # 仍远高于第二对话残留（96-104）与空闲（≈94）
                        if t_dlg > 120:
                            need_a = True   # ① 第一对话残留（白底对话框）
                        elif (t_dlg > 100 and f_now is not None
                              and f_now > last_a_frame):
                            need_a = True   # ② 第二对话残留（A 批键序已尽）
                    if need_a:
                        dlg2_seen = True
                        dlg2_clear = 0
                        last_dlg_residual = True   # v8：残留中 → 开闸门控锁
                        residual_clear_at = None
                        if (f_now is not None
                                and chan.schedule(f_now + 2, 1)
                                and chan.schedule(f_now + 6, 0)):
                            # Lua 帧表补 A：hold 4 帧 = 66ms（单发，防多余
                            # A 打到场景触发上床——2026-08-08 单发化教训）
                            a8_spam += 1
                            print(f"  ↻ 对话残留补推进（Lua，"
                                  f"{game_ms - t_base}ms，top={t_top:.1f} "
                                  f"dlg={t_dlg:.1f} f={f_now}）", flush=True)
                        else:
                            # Lua 通道异常：PostMessage 单发兜底
                            if not safe_send(window_backend.VK[Key.A], False):
                                raise ReplayWindowLost()
                            time.sleep(0.12)
                            if not safe_send(window_backend.VK[Key.A], True):
                                raise ReplayWindowLost()
                            a8_spam += 1
                            print(f"  ↻ 对话残留补推进（PM，"
                                  f"{game_ms - t_base}ms，top={t_top:.1f} "
                                  f"dlg={t_dlg:.1f}）", flush=True)
                    elif dlg2_seen and walk_offset is None and not a_batch_sent:
                        # fix14e（旧画面开闸路径，仅 A 批未入队时保留）：
                        # 对话稳定消失（连续 3 次判定不成立 ≈3.6s）→ 走路段
                        # 开始。A 批体系（帧表开闸）下禁用——2F 室内空闲
                        # top≈96 dlg≈94 恒满足判定 → 误开闸（round-11 v1）。
                        # 2026-08-08 亮度门控：暗场景（床上/错房间 mean 58
                        # 静止）不是对话，3 次判定会误开闸 → 批量键打在床上
                        # 卡死（批量验证实证）。画面 mean>=60（房间/床边）才
                        # 累计判定；暗场景等 RIGHT 唤醒重试（118s 窗口）兜底
                        if last_frame_mean > 0 and last_frame_mean < 60:
                            dlg2_clear = 0
                            if game_ms - t_base > 112000 and (game_ms - t_base) % 5000 < 1000:
                                print(f"  ⚠️ 暗场景延迟开闸（mean={last_frame_mean:.1f}，"
                                      f"{game_ms - t_base}ms——等 RIGHT 唤醒兜底）",
                                      flush=True)
                        else:
                            dlg2_clear += 1
                        if dlg2_clear >= 3:
                            res = _open_gate()
                            if res == "probe_break":
                                break
                        last_fix14c_retry = now
                    else:
                        # 判定非残留：延迟 3s 置 False（防实时捕获偶发偏小
                        # 漏检 → 误开闸 → walk 批打在残留对话上全无效；
                        # 延迟期内 fix14c 每 1.2s 重试，dlg 波动命中即续锁）
                        if residual_clear_at is None:
                            residual_clear_at = now + 3.0
                        elif now >= residual_clear_at:
                            last_dlg_residual = False
                    last_fix14c_retry = now  # 统一节流（含 need_a=False 检测）
            # 起床段帧表开闸检测（第 11 轮 v2）：帧表推进对话（fix14c 补 A
            # 已被 wake_batch_sent 门控），第二对话结束 → 开闸。round-11 v1
            # 实证：行级判定在 2F 不可用——室内空闲 top≈96 dlg≈94 恒满足
            # 「对话中」判定，对话关后玩家站定判定恒真 → 画面开闸永不触发
            # （玩家 104-174s 钉在 (120,112)）。改用帧进度：帧表键是 Lua
            # 核心注入必生效（无焦点依赖），末键 A up（录制 106.41s）后
            # 5 帧对话关、26 帧后走路首键（106.84s）——余量 20 帧 = 26 − 6
            # （round-15 实测对话实际关在 A 末键前 6 帧，见 t115768 剖面）；
            # v9 阈值 30→20、节流 1.0→0.1s：round-15 实证旧参数下对话关→
            # walk 首键 gap 1.0s 超上床阈值（录制 0.44s 成功）→ 玩家回床 →
            # 从床 DOWN 2 格到 (120,112) 再触发第二对话 → 锁死。首键帧现
            # 锚定 F_gate+1（_plan_walk t0=walk 首键，省 20 帧），开闸越快
            # gap 越接近录制 0.44s。
            # v10.3（round-20）：帧门控开闸（取代 v10/v10.1/v10.2 变暗检测）
            # ——A 批含下床 DOWN（帧表驱动）后，起床段时序完全确定：DOWN up
            # （last_a_frame = F_dlg1+1156）后玩家已下床，出门/下楼由 walk 批
            # 帧表复刻（同锚 F_dlg1），开闸不需要画面检测。v10 变暗检测在
            # v10.3 下必然死锁：出门变暗（录制 106.55s）发生在 DOWN down
            # （106.847s）前/中，而 v10.1 门控要求 f_now > last_a_frame
            # （= DOWN up 帧，录制 108.282s）→ 变暗确认永不触发。帧门控确定
            # 性：f_now > last_a_frame + 3（DOWN up + 0.05s）→ 开闸；walk
            # 首键（RIGHT 109438）帧 = F_dlg1+1225 = DOWN up + 69 帧，入队
            # 余量 1.1s 充裕（socket 批量入队 ~0.2s）。
            if (a_batch_sent and walk_offset is None and not lua_active
                    and chan is not None and 104000 <= game_ms <= 132000
                    and now - last_dark_chk > 0.1):
                last_dark_chk = now
                f_now = chan.read_frame()
                if f_now is not None and f_now > last_a_frame + 3:
                    print(f"  🚪 帧门控开闸（A 批含下床键推完：f={f_now} > "
                          f"last_a+3={last_a_frame + 3}，"
                          f"{game_ms - t_base}ms）", flush=True)
                    res = _open_gate()
                    if res == "probe_break":
                        break
            # 走路段坐标反馈（socket 方案）：每 ~1s 读玩家坐标 vs 帧进度键积分
            # 预测（walk_traj 轨迹表推进，2026-08-08 批量调度版——pred 不再
            # 静止锚定，否则人物一走就误报 >4 格）。地图变化（door 转场）→
            # 重锚 + 跳步（转场期间已执行步被转场吞掉，不计入）；误差 > 4 格
            # → 分叉报警中止（不等 mGBA 崩溃——301s 全段实证的提前发现机制）
            if (chan is not None and F_gate is not None and walk_offset is not None
                    and game_ms - last_coord_chk >= (300 if traj_idx <= 3 else 1000)):
                # 第六轮诊断：走路段前 3 步（traj_idx<=3）加密到 300ms——
                # 第五轮第一段 DOWN 只走 1 格（预测 6 格），加密采样看人物
                # 逐帧轨迹（撞墙/键失效/起点偏）
                last_coord_chk = game_ms
                x = chan.read_u16(PLAYER_X)
                y = chan.read_u16(PLAYER_Y)
                bnk = chan.read_u16(MAP_BANK)
                mid = chan.read_u16(MAP_ID)
                f = chan.read_frame()
                if None in (x, y, bnk, mid, f):
                    print(f"  ✗ 坐标读取失败（通道中断）——走路段中止", flush=True)
                    break
                cur_map = (bnk & 0xFF, mid & 0xFF)
                if cur_map != last_map:
                    last_map = cur_map
                    warp_waiting = False   # 第九轮：地图变化 = 转场完成
                    alarm_observe = False  # 第十轮：同清观察期
                    # 转场重锚：pred 从当前实际坐标重新开始；转场期间已执行步
                    # （up 帧 ≤ 当前帧）的位移被转场重置，不计入
                    anchor_x, anchor_y = x, y
                    while (traj_idx < len(walk_traj)
                           and walk_traj[traj_idx][0] <= f):
                        traj_idx += 1
                    print(f"  🗺 地图变化 {cur_map}（重锚 pos=({x},{y})，跳 "
                          f"{traj_idx} 步，帧 {f}）", flush=True)
                else:
                    while (traj_idx < len(walk_traj)
                           and walk_traj[traj_idx][0] <= f):
                        _, ddx, ddy = walk_traj[traj_idx]
                        anchor_x += ddx
                        anchor_y += ddy
                        traj_idx += 1
                    err = abs(x - anchor_x) + abs(y - anchor_y)
                    print(f"  🚶 pos=({x},{y}) pred=({anchor_x},{anchor_y}) "
                          f"误差 {err}px map={cur_map} 帧 {f}（轨迹 "
                          f"{traj_idx}/{len(walk_traj)}）", flush=True)
                    if warp_waiting:
                        # 第九轮：warp 转场等待——落点加载完成（坐标跳变）
                        # → 重锚继续；黑屏超时 = 真锁
                        if (x, y) != warp_pos:
                            warp_waiting = False
                            anchor_x, anchor_y = x, y
                            while (traj_idx < len(walk_traj)
                                   and walk_traj[traj_idx][0] <= f):
                                traj_idx += 1
                            print(f"  ⏩ warp 转场完成（pos=({x},{y})），重锚继续",
                                  flush=True)
                        elif now - warp_since > 6.0:
                            print(f"  ✗ warp 转场黑屏超时（>6s，pos 仍 "
                                  f"({x},{y})）——真锁/转场失败，中止", flush=True)
                            break
                        else:
                            print(f"  ⏳ warp 转场中（pos 冻结 ({x},{y})，"
                                  f"等待落点…）", flush=True)
                    elif err > COORD_ALARM_PX:
                        # 第九/十轮：坐标误差 > 阈值不立即中止——先判转场。
                        # 第九轮实证：玩家 (120,96) DOWN → (120,112) 后坐标
                        # 冻结（err 80px），但画面 116.1s dlg 行 99.8→6.8→
                        # 0.2（底部变黑=楼梯/转场动画）、116.9s 转场完成
                        # mean 回升 94.2——abort 掐在转场尾巴（误差报警时
                        # 画面恰好恢复亮，mean<40 判据错过）。真分叉（撞墙
                        # 走错）的特征是坐标冻结 + 画面静止；转场特征是无
                        # 论画面明暗，坐标会在 ~1-2s 内跳变（落点加载）。
                        # 因此：黑屏（mean<40）→ 等落点（warp_waiting）；
                        # 非黑屏 → 进入 2s 观察期——期间坐标跳变 = 转场
                        # 完成 → 重锚继续；2s 后坐标仍冻结 = 真锁中止。
                        img_w = window_backend.capture_hwnd(hwnd)
                        if img_w is not None:
                            wm = float(np.asarray(img_w).mean())
                            if wm < 40:
                                warp_waiting = True
                                warp_since = now
                                warp_pos = (x, y)
                                print(f"  ⏳ 坐标误差 {err}px 但画面黑屏"
                                      f"（mean={wm:.1f}）——疑似楼梯 warp"
                                      f" 转场，豁免等待落点", flush=True)
                            elif alarm_observe and (x, y) != alarm_observe_pos:
                                # 观察期坐标跳变 = 转场完成 → 重锚继续
                                alarm_observe = False
                                anchor_x, anchor_y = x, y
                                while (traj_idx < len(walk_traj)
                                       and walk_traj[traj_idx][0] <= f):
                                    traj_idx += 1
                                print(f"  ⏩ 转场完成（观察期坐标跳变 "
                                      f"pos=({x},{y})），重锚继续", flush=True)
                            elif alarm_observe and now - alarm_observe_since > 2.0:
                                print(f"  ✗ 坐标误差 {err}px 且观察 2s 坐标"
                                      f"仍冻结（pos=({x},{y})，mean={wm:.1f}）"
                                      f"——真分叉/锁，中止", flush=True)
                                break
                            elif not alarm_observe:
                                alarm_observe = True
                                alarm_observe_since = now
                                alarm_observe_pos = (x, y)
                                print(f"  ⏳ 坐标误差 {err}px（mean={wm:.1f}）"
                                      f"——进入 2s 转场观察", flush=True)
                            else:
                                # 观察中，坐标未变，未超时：继续等
                                print(f"  ⏳ 转场观察中（pos=({x},{y})，"
                                      f"mean={wm:.1f}）…", flush=True)
                        else:
                            print(f"  ✗ 坐标误差 {err}px > {COORD_ALARM_PX}px"
                                  f"（4 格）——走路段分叉，中止", flush=True)
                            break
            # 第 11 轮 v4：外循环兜底抓屏——原抓屏在内层键循环内，长空闲期
            # （66-84s 无键到期）内层循环直接 break 永不触达 → 66.3-81.9s
            # 帧缺口（round-11e 实证），睡眠起点不可见 = 诊断盲区。外循环
            # 按 500ms 节流补抓（与内层共用 last_cap_ms 去重）。
            if args.verify and game_ms - last_cap_ms >= CAP_INTERVAL_MS:
                last_cap_ms = game_ms
                img = window_backend.capture_hwnd(hwnd)
                if img is not None:
                    Image.fromarray(img).save(run_dir / f"t{game_ms:07d}.png")
            # 焦点检查（轻量）：只 SetForegroundWindow，不补 WM_ACTIVATE。
            # 2026-08-08 fix4 实证：restore 点的 WM_ACTIVATE 能恢复 Qt 焦点
            # （62.03s A 生效、64.4s 对齐），但每 2s 周期性 WM_ACTIVATE 疑似
            # 反复打断 Qt 焦点（65.48s 的 A 又失效、67s 起再冻结）——周期
            # 置前只做 SetForegroundWindow（对已前台窗口近乎 no-op，无副作用）。
            # Lua 注入期间跳过：置前会夺走 prompt 焦点）。fix9：频率 2s→0.5s
            # （fix8 实证养焦 ~23s 才生效，RIGHT 83.95s 需更积极的置前）。
            if not lua_active and now - last_focus_chk > 0.5:
                last_focus_chk = now
                try:
                    win32gui.SetForegroundWindow(hwnd)
                except Exception:
                    pass
            if now - last_prog > 30:
                last_prog = now
                el = (game_ms - t_base) / 1000.0
                print(f"  回放中 {el:.0f}s / {total_s:.0f}s"
                      f"（{el / total_s * 100:.0f}%），按键 {known} 跳过 {skipped}",
                      flush=True)
                if not lua_active:
                    _force_foreground(hwnd)
            if i >= len(keys):  # 全部按键已在到期时刻发出
                # --verify 且有 --to 时：继续抓屏观察尾部（转场/后续状态）
                if args.verify and args.to is not None and game_ms - t_base < args.to * 1000:
                    time.sleep(0.01)
                    continue
                break
            time.sleep(0.01)
    except KeyboardInterrupt:
        pass
    except ReplayWindowLost:
        pass  # safe_send 已打印中止原因；finally 正常清理
    finally:
        # 关闭走路段调度通道（若脚本已加载，mGBA 进程随后终止释放端口）
        if chan is not None:
            chan.close()
        # 松开所有按键——句柄可能已失效（ReplayWindowLost 路径），逐个容错
        for key in list(window_backend.VK):
            try:
                window_backend.send_vk(window_backend.VK[key], up=True, hwnd=hwnd)
            except Exception:
                pass
        if proc:
            # 关掉自己启动的 mGBA（避免留孤儿实例干扰下次回放；同时保住 .sav 不被改）
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                pass
        if sav_bak is not None:
            # 恢复录制起点 .sav（回放中游戏会重建 SRAM，必须覆盖回去）
            shutil.copy2(sav_bak, sav_path)
            sav_bak.unlink(missing_ok=True)
            print(f"🧹 已恢复 .sav（回放产生的 SRAM 被覆盖回录制起点状态）")
    print(f"回放结束: {known} 个键位事件（跳过 {skipped} 个原始标签事件）")

    # ---- 验证报告 ----
    if args.verify:
        print("  对比回放与录制快照...")
        report = verify_report(demo_path, run_dir, args.to)
        (run_dir / "report.txt").write_text(report, encoding="utf-8")
        print(report)
        print(f"报告已存: {run_dir / 'report.txt'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
