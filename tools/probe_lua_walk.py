"""走路段 Lua 帧级调度通道 + 探针（2026-08-08 socket 方案）。

背景：PostMessage 走路段存在帧相位抖动（±16ms 游戏帧量化 + Qt 队列延迟）→
人物位置差累积 → 386 hack 转场目标由人物站位决定 → 概率性走错地图 → mGBA
崩溃（301s 全段实证）。根治：走路段全部按键按【游戏帧】精确调度，而非按
墙钟发送。

架构（全部经 third_party/libmgba-py/mgba-src 源码验证）：
- sched_server.lua：经「脚本」窗口 REPL 剪贴板粘贴加载（单行压缩 ~1s；
  0.008s/字符的 WM_CHAR 逐字符要 ~50s，不可行），注册 frame 回调 +
  socket 监听 8890
- frame 回调 = videoFrameEnded（gba/video.c:181）在核心线程同步执行
  （thread.c ADD_CALLBACK(frame) → context.c:220 mScriptInvoke 直调），
  脚本内 emu:setKeys/currentFrame/read16 直调零 Interrupter 冻结（冻结只在
  REPL runCode/load 路径，ScriptingController.cpp:76）
- 帧计数语义（gba/video.c:181-187）：frame 回调期间 currentFrame() == 刚
  结束的帧号，之后 ++video->frameCounter——该时刻 setKeys 的键在下一帧的
  keysRead 生效 → 目标激活帧 G 的调度帧 = G−1
- socket 客户端每帧自动轮询（lua.c:147 `sock:_hook(0)` 注册 frame 回调），
  'received' 事件 → onrecv 按行处理；receive 的 AGAIN/断开语义与官方
  res/scripts/socketserver.lua 模式一致
- Python 侧 SchedChannel（S/F/R/P 协议）+ 帧目标公式
  F(t) = F_gate + round((t − WALK_KEY_ABS) × 0.06) − 1，掩码 = 事件后 held
  状态（正逻辑位掩码，GBAKey：A=0 B=1 S=2 s=3 RIGHT=4 LEFT=5 UP=6 DOWN=7）
- 坐标反馈：read16 玩家坐标（0x02020650/652）+ 地图（0x02025A0C/0E），
  键积分预测对比 → 分叉检测（超阈值报警中止，不等 mGBA 崩溃）

走路步数模型（帧语义边界分析）：键激活帧 G..H−1（共 H−G 帧）。第一格在
激活帧 G 的 walk 决策即提交（15 帧动画与按键无关）；第 n+1 格在激活帧
G+15n 的决策检查按键。故 steps = ceil(激活帧/15)，激活帧 =
round(hold_ms × 0.06)。边界：hold 15 帧 = 1 格（第 16 帧才提交第 2 格）。
"""
from __future__ import annotations

import re
import socket
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 注意：replay_demo_window 在 main() 内 lazy import 本模块——此刻该模块已
# 完整加载（常量均在模块顶层定义），无循环导入问题
from tools.replay_demo_window import (DIR_KEYS, PROMPT_WIN_Y, VK2LUA,
                                      WALK_KEY_ABS)  # noqa: E402

SCHED_PORT = 8890
PLAYER_X = 0x02020650     # 玩家像素 x（u16，16px/格，第一代已标定）
PLAYER_Y = 0x02020652     # 玩家像素 y
MAP_BANK = 0x02025A0C     # 地图 bank（u8）
MAP_ID = 0x02025A0E       # 地图 id（u8）
WALK_FRAMES_PER_STEP = 15  # 绿宝石走路帧/格
CTX_PASTE_Y = 81          # QLineEdit 右键菜单「粘贴」= 第 4 项 y（同 Tools「脚本」
                          # 实测映射 15/37/58/81；粘贴=撤销/剪切/复制/粘贴）
SV_X, SV_Y = 1900, 550    # 「脚本」窗口位置（与 LuaInjector.prepare 一致）

DIRVEC = {"RIGHT": (1, 0), "LEFT": (-1, 0), "UP": (0, -1), "DOWN": (0, 1)}

SCHED_LUA_PATH = ROOT / "tools" / "sched_server.lua"


def sched_lua_oneline() -> str:
    """sched_server.lua 单行压缩（REPL prompt 是单行 QLineEdit，粘贴用）。

    文件内无注释；压缩 = 空白折叠为单空格（字符串字面量内的单个空格保留）。
    """
    text = SCHED_LUA_PATH.read_text(encoding="utf-8")
    return re.sub(r"\s+", " ", text).strip()


def _paste_clipboard(lua, use_ctxmenu: bool) -> bool:
    """把剪贴板内容粘进 prompt：Ctrl+V（post 键）或右键上下文菜单「粘贴」。

    2026-08-08 记忆实证：WM_KEYDOWN 对 Qt 文本插入无效（WM_CHAR 才有效），
    Enter/修饰键走 QKeyEvent 路径（Enter 有效）——Ctrl+V 的修饰键状态由消息
    流跟踪，理论可行但未实证；右键菜单「粘贴」是纯物理点击（火绒不拦鼠标），
    兜底路径。
    """
    import ctypes
    import win32con
    sv = lua.sv
    if not sv or not lua._win32gui.IsWindow(sv):
        return False
    g = lua._win32gui
    if use_ctxmenu:
        user32 = ctypes.windll.user32
        # 2026-08-08 启动预载实证：窗口刚 SetWindowPos/移动完就右键，可能落在
        # 错误的控件上（文本区 vs prompt 的右键菜单项布局不同 → 点错项 →
        # 连接失败）。先等窗口稳定再点。
        time.sleep(1.0)
        user32.SetCursorPos(SV_X + 500, SV_Y + PROMPT_WIN_Y)   # prompt 上右键
        time.sleep(0.12)
        user32.mouse_event(0x0008, 0, 0, 0, 0)   # RIGHTDOWN
        time.sleep(0.1)
        user32.mouse_event(0x0010, 0, 0, 0, 0)   # RIGHTUP
        time.sleep(0.8)
        popup = None
        for h in lua._visible_set():
            if "QWindowPopup" in g.GetClassName(h):
                popup = h
                break
        if not popup:
            print("  ⚠️ 右键上下文菜单未弹出", flush=True)
            return False
        pr = g.GetWindowRect(popup)
        print(f"  [粘贴] 上下文菜单 popup {popup:#x} rect={pr}"
              f"（点 {pr[0] + 100},{pr[1] + 31 + CTX_PASTE_Y}）", flush=True)
        user32.SetCursorPos(pr[0] + 100, pr[1] + 31 + CTX_PASTE_Y)  # 「粘贴」
        time.sleep(0.12)
        user32.mouse_event(0x0002, 0, 0, 0, 0)
        time.sleep(0.1)
        user32.mouse_event(0x0004, 0, 0, 0, 0)
        time.sleep(0.3)
        return True
    for vk in (0x11, 0x56):   # VK_CONTROL, V
        g.PostMessage(sv, win32con.WM_KEYDOWN, vk, 1)
    for vk in (0x56, 0x11):
        g.PostMessage(sv, win32con.WM_KEYUP, vk, 1)
    time.sleep(0.3)
    return True


def load_sched_via_paste(lua, use_ctxmenu: bool = False) -> bool:
    """sched_server.lua 单行压缩粘贴进 REPL prompt 并执行（~2.5s）。

    1500 字符逐字符 WM_CHAR ~30s 不可行；剪贴板粘贴一次完成。执行后由
    load_sched_channel 的连接验证成败。
    """
    import ctypes
    import win32clipboard
    import win32con
    lua._ensure_prompt(force=True)
    code = sched_lua_oneline()
    try:
        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardText(code)
        finally:
            win32clipboard.CloseClipboard()
    except Exception:
        print("  ⚠️ 剪贴板写入失败", flush=True)
        return False
    if not _paste_clipboard(lua, use_ctxmenu):
        return False
    g = lua._win32gui
    scan = ctypes.windll.user32.MapVirtualKeyW(0x0D, 0)
    g.PostMessage(lua.sv, win32con.WM_KEYDOWN, 0x0D, (scan << 16) | 1)
    time.sleep(0.03)
    g.PostMessage(lua.sv, win32con.WM_KEYUP, 0x0D, (scan << 16) | 0xC0000001)
    time.sleep(1.2)   # runCode（Interrupter 冻结 ~250ms）+ socket bind
    return True


def load_sched_channel(lua) -> "SchedChannel | None":
    """粘贴加载 sched_server.lua + TCP 连接。

    先 Ctrl+V 后右键菜单兜底；都失败返回 None（调用方中止回放——走路段无法
    帧调度即回到 PostMessage 分叉状态，跑下去无意义）。
    """
    # Ctrl+V 路径已知脆弱（WM_KEYDOWN 对 Qt 粘贴无效，记忆实证）只试一次；
    # 右键菜单物理点击给 3 次重试（2026-08-08 启动预载实证：首次右键可能
    # 点在未稳定窗口的错控件上 → 菜单错/粘贴错位 → 连接失败）
    for method, label, tries in ((False, "Ctrl+V", 1), (True, "右键菜单", 3)):
        for attempt in range(tries):
            if not load_sched_via_paste(lua, use_ctxmenu=method):
                print(f"  ⚠️ sched_server.lua 粘贴失败（{label}"
                      f"{f'，尝试 {attempt + 1}/{tries}' if tries > 1 else ''}）",
                      flush=True)
                continue
            chan = SchedChannel(SCHED_PORT)
            if chan.connect(timeout=3.0):
                print(f"  🔌 走路段调度通道已连接（sched_server.lua @{SCHED_PORT}，"
                      f"{label}）", flush=True)
                return chan
            print(f"  ⚠️ 通道连接失败（{label} 尝试 {attempt + 1}/{tries}"
                  f"后端口 {SCHED_PORT} 未监听）", flush=True)
            time.sleep(1.0)
    return None


def sched_frame(F_gate: int, t_rec_abs: int) -> int:
    """录制 abs 时刻 t → 调度帧（目标激活帧 G 的 G−1，见模块 docstring）。"""
    g = F_gate + round((t_rec_abs - WALK_KEY_ABS) * 0.06)
    return g - 1


def walk_steps(hold_ms: float) -> int:
    """按住时长（ms）→ 走格数（绿宝石 ~15 帧/格，≥1 帧必出第一格）。"""
    frames = max(1, round(hold_ms * 0.06))
    return (frames + WALK_FRAMES_PER_STEP - 1) // WALK_FRAMES_PER_STEP


def _plan_walk(walk_keys, F_gate, x0, y0, anchor_ms=None):
    """走路键 → (调度事件 [(帧, 掩码, 键名, down/up)], 键积分预测 (x, y),
    轨迹 [(up帧, dx, dy)])。

    事件按录制时刻顺序；掩码 = 该事件后累计 held 状态（脚本按帧应用，同帧
    多事件按到达顺序）。预测位移 = Σ 每键 steps × 16px × 方向。轨迹表供
    回放坐标反馈按帧进度推进 pred（转场重锚后用相对增量）。

    v10.3（2026-08-08）：anchor_ms 非 None 时帧 =
    F_gate + round((t − anchor_ms)×0.06) − 1——与 A 批同轴同式（起床段帧表
    A 批锚定 F_dlg1 + 89000）。下床 DOWN（106844-108282）并入 A 批后，walk
    批（109438 起，出门后第一 RIGHT）帧 = F_dlg1 + 1225 = DOWN up 帧
    （F_dlg1+1156）+ 69 帧（录制 108282→109438 = 1.156s 精确复刻）。锚定
    同一 F_dlg1 → 起床段/走路段帧轴统一，无锚定误差累积。

    v9（anchor_ms=None）：帧 = F_gate + 1 + round((t − t0)×0.06)，t0 = walk
    段第一键时刻——首键在 F_gate+1 立即执行（旧基准 WALK_KEY_ABS 使首键晚
    20 帧，见下方注释；探针模式/非 A 批回退路径仍用此行为）。

    2026-08-08 round-11f 修复：旧配对式处理（down → 找同名 up → i=j+1）在
    并发键（按住 DOWN 期间按下 A）下把配对区间内的异键整段跳过（实证：
    110.42s A down 夹在 110.20s DOWN down 与其配对 up（110.48s）之间 →
    i=j+1 跳段 → A down 丢失、mask 与时间序不符 → walk 批推进对话的键
    被吞）。时间序状态机：逐事件按时刻累计 held，孤儿 up 容错，mask =
    该时刻真实按键状态，无跳段。
    """
    events = []
    traj = []   # 每步位移完成后 (up 事件帧, 位移增量)——重锚后相对累计
    held = 0
    px, py = x0, y0
    last_down = {}  # name → (down 时刻, 帧) 最近一次 down（up 回溯算步数）
    # v9：帧锚定基准 = walk 段第一键时刻（非 WALK_KEY_ABS）——首键在
    # F_gate+1 立即执行。round-15 实证：旧基准（WALK_KEY_ABS=106500）让首键
    # 帧 = F_gate+20（0.33s 延迟）→ 对话关→DOWN gap 1.0s 超上床阈值
    # （录制 0.44s 成功）→ 玩家回床 → 从床 DOWN 2 格到 (120,112) 再触发
    # 第二对话 → 锁死。首键尽快出门 = 复刻录制节奏（0.44s 内）。
    t0 = anchor_ms if anchor_ms is not None else (
        walk_keys[0]["t"] if walk_keys else WALK_KEY_ABS)
    for k in walk_keys:
        name = k["name"]
        bv = VK2LUA.get(name)
        if bv is None:
            continue  # 未映射键（原始标签）——不调度（同主循环 walk 分支 skipped）
        bit = 1 << bv
        t = k["t"]
        if anchor_ms is not None:
            f = F_gate + round((t - anchor_ms) * 0.06) - 1
        else:
            f = F_gate + 1 + round((t - t0) * 0.06)
        if k["down"]:
            held |= bit
            events.append((f, held, name, "down"))
            last_down[name] = (t, f)
        else:
            held &= ~bit
            events.append((f, held, name, "up"))
            if name in DIRVEC and name in last_down:
                dx, dy = DIRVEC[name]
                steps = walk_steps(t - last_down[name][0])
                ddx, ddy = dx * 16 * steps, dy * 16 * steps
                traj.append((f, ddx, ddy))
                px += ddx
                py += ddy
                del last_down[name]
    return events, (px, py), traj


class SchedChannel:
    """mGBA 调度脚本 TCP 通道（sched_server.lua）。

    协议（\n 分隔 ASCII）：
      S <frame> <mask>   帧 frame 处把按键掩码设为 mask（sched[frame] 队列）
      F                   → 响应 "F <frame>"
      R <addr>            → 响应 "R <addr> <value>"
      P                   → 响应 "P ok"
    脚本侧：frame 回调按帧应用掩码；socket 客户端经自动注册的 frame 回调
    轮询（lua.c `_hook`）——全程零 Interrupter 冻结。

    2026-08-08 round-11d 修复：mask 0（键释放）必须接受——原 `if f and m`
    在 Lua 中 0 为 falsy → 所有释放事件被丢弃 → 键合并成连续按住（实证：
    RIGHT 按 1.13s 变按住 5.4s 不唤醒、A 连按合成一个长按弹「再睡」框、
    walk 批的释放事件同样全丢）。注意 sched_server.lua 必须保持无注释
    （sched_lua_oneline 压缩成单行粘贴，`--` 注释会吞掉行尾全部代码）。
    """

    def __init__(self, port: int = SCHED_PORT):
        self.port = port
        self.sock: socket.socket | None = None
        self._buf = b""

    def connect(self, timeout: float = 3.0) -> bool:
        try:
            self.sock = socket.create_connection(("127.0.0.1", self.port),
                                                 timeout=timeout)
        except OSError:
            return False
        self.sock.settimeout(1.0)
        for _ in range(3):
            if self.ping():
                return True
        self.close()
        return False

    def _read_line(self) -> bytes | None:
        while b"\n" not in self._buf:
            try:
                chunk = self.sock.recv(4096)
            except socket.timeout:
                return None
            except OSError:
                return None
            if not chunk:
                return None
            self._buf += chunk
        line, self._buf = self._buf.split(b"\n", 1)
        return line.strip()

    def _cmd(self, want_prefix: bytes, line: str) -> bytes | None:
        if not self.sock:
            return None
        try:
            self.sock.sendall(line.encode() + b"\n")
        except OSError:
            return None
        t0 = time.monotonic()
        while time.monotonic() - t0 < 2.0:
            ln = self._read_line()
            if ln is None:
                return None
            if ln.startswith(want_prefix):
                return ln
        return None

    def ping(self) -> bool:
        return self._cmd(b"P", "P") is not None

    def read_frame(self) -> int | None:
        ln = self._cmd(b"F", "F")
        if ln is None:
            return None
        parts = ln.split()
        return int(parts[1]) if len(parts) >= 2 else None

    def read_u16(self, addr: int) -> int | None:
        ln = self._cmd(b"R", f"R {addr}")
        if ln is None:
            return None
        parts = ln.split()
        return int(parts[2]) if len(parts) >= 3 else None

    def schedule(self, frame: int, mask: int) -> bool:
        if not self.sock:
            return False
        try:
            self.sock.sendall(f"S {frame} {mask}\n".encode())
            return True
        except OSError:
            return False

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None


def run_probe(chan, keys, F_gate, gate_x, gate_y) -> tuple[str, bool]:
    """走路段探针：通道往返 / 帧单调 / 前 20 走路键帧级调度位移 vs 键积分 /
    单键 3 帧步数（走路模型边界）。

    通过标准（对应计划「冻结 std/释放精度/位置误差」在 socket 方案下的形态）：
    - 通道往返 ≥ 9/10（脚本在线、帧回调轮询有效）
    - 帧读数单调（游戏帧时钟可用）
    - 20 键位移误差 ≤ 1 格（16px）——帧调度精确 + 步数模型正确
    """
    lines = [f"探针起点: F_gate={F_gate} pos=({gate_x},{gate_y})"]
    fail = []
    # 1) 通道往返
    t0 = time.monotonic()
    okp = 0
    for _ in range(10):
        if chan.ping():
            okp += 1
    rtt = (time.monotonic() - t0) / 10 * 1000
    lines.append(f"[1] 通道往返: {okp}/10 成功，均值 {rtt:.1f}ms")
    if okp < 9:
        fail.append("通道往返失败率过高")
    # 2) 帧读数单调
    fr = []
    for _ in range(5):
        f = chan.read_frame()
        if f is None:
            break
        fr.append(f)
        time.sleep(0.02)
    mono = len(fr) >= 4 and all(fr[i + 1] >= fr[i] for i in range(len(fr) - 1))
    lines.append(f"[2] 帧读数 ×{len(fr)}: {fr} 单调={'是' if mono else '否'}")
    if not mono:
        fail.append("帧读数非单调")
    # 3) 前 20 个走路键帧级调度
    walk = [k for k in keys if k["t"] >= WALK_KEY_ABS][:20]
    events, (px, py) = _plan_walk(walk, F_gate, gate_x, gate_y)
    dirs = ",".join(sorted({e[2] for e in events if e[3] == "down"}))
    for f, m, _n, _k in events:
        chan.schedule(f, m)
    last_f = events[-1][0] if events else F_gate
    lines.append(f"[3] 调度 {len(events)} 事件（{len(walk)} 键 [{dirs}]），帧跨度 "
                 f"F_gate+{events[0][0] - F_gate}..F_gate+{last_f - F_gate}，"
                 f"键积分预测 ({px},{py})")
    # 4) 等执行完（最后事件帧 + 45——走路动画收尾）
    t0 = time.monotonic()
    while time.monotonic() - t0 < 90:
        f = chan.read_frame()
        if f is None:
            break
        if f >= last_f + 45:
            break
        time.sleep(0.1)
    x1, y1 = chan.read_u16(PLAYER_X), chan.read_u16(PLAYER_Y)
    err = abs(x1 - px) + abs(y1 - py)
    ok3 = err <= 16
    lines.append(f"[4] 20 键执行后: pos=({x1},{y1}) vs 预测 ({px},{py}) → "
                 f"误差 {err}px" + (" ✓≤1 格" if ok3 else " ✗>1 格"))
    if not ok3:
        fail.append(f"20 键位移误差 {err}px > 1 格")
    # 5) 单键 3 帧步数（第一个方向键 ×5，间隔 40 帧）——走路模型验证。
    #    信息项：方向被挡（墙/门）时位移不足是正常现象，不判失败
    dk = next((k for k in walk if k["name"] in DIRVEC), None)
    if dk is not None:
        base = (chan.read_frame() or F_gate) + 45
        b = 1 << VK2LUA[dk["name"]]
        for n in range(5):
            chan.schedule(base + n * 40 - 1, b)       # 激活帧 base+n*40
            chan.schedule(base + n * 40 + 2, 0)       # 3 帧后释放
        t0 = time.monotonic()
        while time.monotonic() - t0 < 30:
            f = chan.read_frame()
            if f is None or f >= base + 5 * 40 + 40:
                break
            time.sleep(0.1)
        x2, y2 = chan.read_u16(PLAYER_X), chan.read_u16(PLAYER_Y)
        dx, dy = DIRVEC[dk["name"]]
        d = (x2 - x1) * dx + (y2 - y1) * dy
        lines.append(f"[5] 单键 3 帧 ×5（{dk['name']}）: 位移 {d:+d}px"
                     f"（期望 +80px=5 步）" + (" ✓" if d == 80 else "（被挡或模型偏差，"
                                                                 "信息项）"))
    lines.append("")
    if fail:
        lines.append(f"✗ 探针未通过（{len(fail)} 项）：" + "；".join(fail))
        return "\n".join(lines), False
    lines.append("✅ 探针全部通过——走路段帧级调度可行")
    return "\n".join(lines), True


def run_freeze_probe(chan, keys, F_gate, gate_x, gate_y, cap=None) -> tuple[str, bool]:
    """(120,112) 冻结诊断探针（2026-08-08 第十一轮，见 tools/replay_demo_window.py
    的 walk-lua 批量调度）。

    背景：round-10 批量走路段里玩家从 (120,96) 走 1 格到 (120,112) 后坐标
    冻结（DOWN 仍按住），而录制同路径走 6 格无碍、warp 黑屏在 108.5s。
    (120,112) 是已知 2F 剧情锁点（demo 233825 实证）。冻结性质未知：
    A) 墙——仅 DOWN 被挡（(120,128) 不可通行），其余方向可动 → 录制 walk-from
       与回放不同（起点差 1 格）；
    B) 锁——玩家移动任务死亡，全方向无响应（233825 末态）。

    做法：只调度录制走路段首个方向键 hold（DOWN 86 帧 = 6 格，复现 round-10
    冻结路径），观察段轮询坐标（~0.3s/次，最长 8s，cap 每轮抓屏同帧存档），
    冻结确认后逐方向发 14 帧探针键（=1 格：walk_steps(14×16.7ms)=1），每次
    读坐标+地图判定该方向是否可动。
    """
    walk = [k for k in keys if k["t"] >= WALK_KEY_ABS]
    first = next((i for i, k in enumerate(walk)
                  if k["name"] in DIRVEC and k["down"]), None)
    if first is None:
        return "冻结探针: 走路段无方向键，无法复现", False
    # 只取首个 hold（down + 其 up）——复现 round-10 的 DOWN 86 帧
    seg = walk[first:first + 2]
    events, (ex, ey), _traj = _plan_walk(seg, F_gate, gate_x, gate_y)
    if len(events) < 2:
        return f"冻结探针: 首键 {seg[0]['name']} 无配对 up，跳过", False
    down_f, up_f = events[0][0], events[1][0]
    for f, m, _n, _k in events:
        chan.schedule(f, m)
    ddx, ddy = ex - gate_x, ey - gate_y
    lines = [f"冻结探针: F_gate={F_gate} pos=({gate_x},{gate_y})",
             f"  调度首个 hold: {seg[0]['name']} 帧 +{down_f - F_gate}.."
             f"+{up_f - F_gate}（键积分 Δ({ddx},{ddy})px）"]
    # 等 hold 结束 + 走路动画收尾
    t0 = time.monotonic()
    while time.monotonic() - t0 < 30:
        f = chan.read_frame()
        if f is None or f >= up_f + 40:
            break
        time.sleep(0.05)
    # 观察段：~0.3s/次，最长 8s——记录 (帧, 坐标, 地图)，cap 每轮抓屏
    obs = []
    t0 = time.monotonic()
    while time.monotonic() - t0 < 8.0:
        f = chan.read_frame()
        x = chan.read_u16(PLAYER_X)
        y = chan.read_u16(PLAYER_Y)
        bnk = chan.read_u16(MAP_BANK)
        mid = chan.read_u16(MAP_ID)
        pos = (x, y) if x is not None and y is not None else None
        mp = (bnk & 0xFF, mid & 0xFF) if bnk and mid else None
        obs.append((f, pos, mp))
        if cap:
            cap(f)
        time.sleep(0.3)
    uniq = []
    for f, pos, mp in obs:
        if not uniq or (pos, mp) != (uniq[-1][1], uniq[-1][2]):
            uniq.append((f, pos, mp))
    lines.append("  观察段位置序列: " + " | ".join(
        f"F{f} {pos} m{mp}" for f, pos, mp in uniq))
    if len(uniq) != 1:
        lines.append(f"  ✅ hold 后坐标在动（{len(uniq)} 段）——未冻结，"
                     f"首 hold 直接走通，无逐方向探针")
        return "\n".join(lines), True
    fx, fy = uniq[0][1]
    lines.append(f"  ⚡ 坐标冻结于 {fx}——进入逐方向探针（14 帧 hold = 1 格）")
    last_pos = (fx, fy)
    for name in ("DOWN", "RIGHT", "UP", "LEFT"):
        f0 = chan.read_frame() or F_gate
        base = f0 + 5
        b = 1 << VK2LUA[name]
        chan.schedule(base - 1, b)
        chan.schedule(base + 13, 0)            # 激活帧 base..base+13 = 14 帧
        t0 = time.monotonic()
        while time.monotonic() - t0 < 10:
            f = chan.read_frame()
            if f is None or f >= base + 35:
                break
            time.sleep(0.05)
        x = chan.read_u16(PLAYER_X)
        y = chan.read_u16(PLAYER_Y)
        bnk = chan.read_u16(MAP_BANK)
        mid = chan.read_u16(MAP_ID)
        mp = (bnk & 0xFF, mid & 0xFF) if bnk and mid else None
        if cap:
            cap(chan.read_frame())
        pos = (x, y) if x is not None and y is not None else None
        dd = "—"
        if pos is not None and last_pos is not None:
            ddx2, ddy2 = pos[0] - last_pos[0], pos[1] - last_pos[1]
            dd = f"Δ({ddx2:+d},{ddy2:+d})"
        lines.append(f"  探针 {name}: →{pos} m{mp} {dd}")
        if pos is not None:
            last_pos = pos
    return "\n".join(lines), True


if __name__ == "__main__":
    # 自检（无 mGBA）：sched_frame/walk_steps/_plan_walk 纯函数 + Lua 压缩
    s = sched_lua_oneline()
    assert "\n" not in s and "--" not in s, "Lua 单行压缩异常"
    print(f"Lua 单行 {len(s)} 字符 ✓")
    assert sched_frame(100000, 106500) == 99999        # t=WALK_KEY_ABS → F_gate−1
    assert sched_frame(100000, 106847) == 100020       # round(347×0.06)=21 → −1
    assert walk_steps(50) == 1 and walk_steps(188) == 1
    assert walk_steps(250) == 1 and walk_steps(266) == 2   # 16 帧边界
    assert walk_steps(656) == 3
    keys = [
        {"name": "RIGHT", "t": 106500, "down": True},
        {"name": "RIGHT", "t": 106688, "down": False},   # 188ms = 1 格
        {"name": "DOWN", "t": 106900, "down": True},
        {"name": "DOWN", "t": 107156, "down": False},    # 256ms = 1 格
    ]
    events, (px, py), traj = _plan_walk(keys, 100000, 100, 200)
    assert (px, py) == (116, 216), (px, py)
    assert events[0][0] == 99999 and events[-1][0] == 100038
    assert traj == [(100010, 16, 0), (100038, 0, 16)], traj
    print("纯函数自检 ✓")
