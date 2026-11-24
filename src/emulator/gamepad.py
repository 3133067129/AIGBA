"""手柄读取层：旁路轮询真实手柄（pygame.joystick，无窗口不抢焦点）。

映射事实来源：%APPDATA%/mGBA/config.ini 的 [gba.input.SDLB]（用户在 mGBA 里
调好的绑定，2026-08-07 实测：北通 BTP-KP20D XINPUT DONGLE）。
pygame 与 mGBA 读同一 SDL 设备 → 按钮/轴索引一致。

mGBA 绑定格式（config.ini）：
- keyA=0 → GBA A = SDL 按钮 0（pygame get_button(0) 同源）
- axisRightAxis=+0 → 轴 0 正半 = 右；axisLeftAxis=-0 → 轴 0 负半 = 左
  （带符号索引：符号=半轴方向，|值|=轴号；-0 也是合法负半轴）
- axisUpAxis=-1 → 轴 1 负半 = 上（左摇杆推上）
- hat0Up=6 等 → D-pad 绑定（值编码 pygame 归一化后核对，--test 实测）

未映射输入（存档键/扳机等）以原始标签上报：
- 未映射按钮 → "BTN<i>"
- 未映射轴（如扳机 AX4/AX5）→ "AX<i>+" / "AX<i>-"
- 未映射 hat → "HAT<x>,<y>"
"""
from __future__ import annotations

import ctypes
import os
import time
from pathlib import Path

import pygame

from .keys import Key

MGBA_CONFIG_PATH = Path(os.environ.get("APPDATA", "")) / "mGBA" / "config.ini"
SDLB_SECTION = "gba.input.SDLB"

# mGBA 按钮绑定键名 → GBA 动作
_BUTTON_KEYS = {
    "A": Key.A, "B": Key.B, "SELECT": Key.SELECT, "START": Key.START,
    "L": Key.L, "R": Key.R,
}
_AXIS_KEYS = {
    "Up": Key.UP, "Down": Key.DOWN, "Left": Key.LEFT, "Right": Key.RIGHT,
}
_HAT_COORDS = {
    Key.UP: (0, -1), Key.DOWN: (0, 1), Key.LEFT: (-1, 0), Key.RIGHT: (1, 0),
}

DIR_NAMES = {"UP", "DOWN", "LEFT", "RIGHT"}


class NoGamepadError(RuntimeError):
    pass


def load_mgba_bindings(path: str | Path | None = None) -> dict:
    """解析 mGBA config.ini 的手柄绑定。

    返回 {"buttons": {SDL按钮索引: Key}, "axes": {Key: (轴号, 符号)},
          "hat": {Key: (x, y)}, "guid": 设备 GUID 或 None}。
    优先 [gba.input.SDLB]（活动设备），缺省用设备专属 profile 段。
    """
    cfg = {}
    bind = {"buttons": {}, "axes": {}, "hat": {}, "guid": None}
    path = Path(path) if path else MGBA_CONFIG_PATH
    if not path.exists():
        return bind
    import configparser
    parser = configparser.ConfigParser()
    parser.read(path, encoding="utf-8")
    sec = None
    if parser.has_section(SDLB_SECTION):
        sec = parser[SDLB_SECTION]
    else:
        for name in parser.sections():
            if name.startswith("gba.input-profile."):
                sec = parser[name]
                break
    if sec is None:
        return bind

    for name, key in _BUTTON_KEYS.items():
        v = sec.get(f"key{name}", fallback=None)
        if v and v.strip().lstrip("-").isdigit() and int(v) >= 0:
            bind["buttons"][int(v)] = key
    for name, key in _AXIS_KEYS.items():
        v = sec.get(f"axis{name}Axis", fallback=None)
        if v and v.strip():
            s = v.strip()
            idx = abs(int(s))
            sign = -1 if s.startswith("-") else 1
            bind["axes"][key] = (idx, sign)
    if any(sec.get(f"hat0{n}", fallback=None) is not None
           for n in ("Up", "Down", "Left", "Right")):
        bind["hat"] = dict(_HAT_COORDS)
    bind["guid"] = sec.get("device0", fallback=None) or None
    return bind


class Gamepad:
    """手柄轮询器。poll() 状态 diff → [(标签, down)]。"""

    def __init__(self, bindings: dict | None = None,
                 deadzone: float = 0.25, threshold: float = 0.5):
        pygame.init()  # 全初始化但不开窗口（display 未 set_mode 不抢焦点）
        pygame.joystick.init()
        bindings = bindings if bindings is not None else load_mgba_bindings()
        self.bindings = bindings
        self.deadzone = deadzone
        self.threshold = threshold
        self.j = self._pick_joystick(bindings.get("guid"))
        self.name = self.j.get_name()
        self._state: dict[str, bool] = {}
        self._axis_last: dict[tuple[int, int], bool] = {}
        self._axis_base = self._calibrate_axes()
        self._prime()  # 首轮 poll 前先填充初始状态，防全部键误报"按下"

    def _calibrate_axes(self) -> list[float]:
        """轴基线标定（5 次采样取中值）。

        XInput 扳机轴空闲时贴边（SDL: -1 空闲 ~ +1 按满，0 在半程），
        与摇杆（空闲≈0）行为不同 —— 用基线区分单边轴。
        """
        samples: list[list[float]] = [[] for _ in range(self.j.get_numaxes())]
        for _ in range(5):
            pygame.event.pump()  # SDL 轴状态在事件泵后才更新（否则读到初始 0）
            for i in range(self.j.get_numaxes()):
                samples[i].append(self.j.get_axis(i))
            time.sleep(0.005)
        return [sorted(s)[len(s) // 2] for s in samples]

    def _prime(self) -> None:
        """首轮 poll 前先记录当前完整状态（丢弃 diff）。

        否则第一轮 poll() 会把每个键的初始状态当成"按下"上报
        （prev={} 时 prev.get(label)=None != False），录制开头会
        出现 19+ 个假按键事件（2026-08-08 实测事故）。"""
        self.poll()

    def _pick_joystick(self, guid: str | None):
        n = pygame.joystick.get_count()
        if n == 0:
            raise NoGamepadError("pygame 未检测到手柄（接收器插好/手柄开机了吗）")
        if guid:
            for i in range(n):
                j = pygame.joystick.Joystick(i)
                if j.get_guid() == guid:
                    j.init()
                    return j
        j = pygame.joystick.Joystick(0)
        j.init()
        return j

    def _axis_active(self, idx: int, sign: int) -> bool:
        v = self.j.get_axis(idx)
        key = (idx, sign)
        last = self._axis_last.get(key, False)
        base = self._axis_base[idx] if idx < len(self._axis_base) else 0.0
        if abs(base) > 0.6:
            # 单边轴（扳机类：空闲贴边）——只有与空闲侧相反的一侧有意义，
            # 空闲侧永远不报（否则扳机空闲时会被误判为按住）。
            if (base < 0) == (sign < 0):
                self._axis_last[key] = False
                return False
            offset = -base  # 按下方向（如空闲 -1 → 朝 + 按）
            press_th = base + offset * self.threshold
            release_th = base + offset * self.deadzone
            if offset > 0:
                act = v > press_th if not last else v > release_th
            else:
                act = v < press_th if not last else v < release_th
        elif sign > 0:
            act = v > self.threshold if not last else v > self.deadzone
        else:
            act = v < -self.threshold if not last else v < -self.deadzone
        self._axis_last[key] = act
        return act

    def poll(self) -> list[tuple[str, bool]]:
        """返回 [(标签, down)]（含首次状态的完整快照 diff）。"""
        pygame.event.pump()  # Windows 下 SDL 手柄状态在事件泵里更新
        cur: dict[str, bool] = {}
        buttons = self.bindings.get("buttons", {})
        for i in range(self.j.get_numbuttons()):
            key = buttons.get(i)
            label = key.name if key else f"BTN{i}"
            cur[label] = bool(self.j.get_button(i))
        # 轴：先按映射半轴，再补未映射半轴（扳机等原始标签）
        mapped_axes = set()
        for key, (idx, sign) in self.bindings.get("axes", {}).items():
            mapped_axes.add((idx, sign))
            cur[key.name] = self._axis_active(idx, sign)
        for i in range(self.j.get_numaxes()):
            for sign in (+1, -1):
                if (i, sign) not in mapped_axes:
                    cur[f"AX{i}{'+' if sign > 0 else '-'}"] = self._axis_active(i, sign)
        if self.j.get_numhats() > 0:
            hat = tuple(self.j.get_hat(0))
            hat_map = self.bindings.get("hat", {})
            for key, coord in hat_map.items():
                cur[key.name] = hat == coord
            if not hat_map:
                cur[f"HAT{hat[0]},{hat[1]}"] = hat != (0, 0)
        changes = []
        prev = self._state
        for label, v in cur.items():
            if prev.get(label) != v:
                changes.append((label, v))
        self._state = cur
        return changes

    def mapping_summary(self) -> str:
        """人类可读的映射摘要（boot 事件/启动打印用）。"""
        parts = []
        b = self.bindings.get("buttons", {})
        for idx, key in sorted(b.items()):
            parts.append(f"{key.name}=BTN{idx}")
        for key, (idx, sign) in self.bindings.get("axes", {}).items():
            parts.append(f"{key.name}=AX{idx}{'+' if sign > 0 else '-'}")
        if self.bindings.get("hat"):
            parts.append("方向=D-pad")
        return " ".join(parts) if parts else "（无 mGBA 绑定，全原始标签）"


# ---------- XInput 直读兜底（pygame 看不到设备时）----------

class XINPUT_GAMEPAD(ctypes.Structure):
    _fields_ = [
        ("wButtons", ctypes.c_ushort),
        ("bLeftTrigger", ctypes.c_ubyte),
        ("bRightTrigger", ctypes.c_ubyte),
        ("sThumbLX", ctypes.c_short),
        ("sThumbLY", ctypes.c_short),
        ("sThumbRX", ctypes.c_short),
        ("sThumbRY", ctypes.c_short),
    ]


class XINPUT_STATE(ctypes.Structure):
    _fields_ = [("dwPacketNumber", ctypes.c_ulong), ("Gamepad", XINPUT_GAMEPAD)]


# XINPUT 物理键位（bitmask）→ 标签
_XI_BUTTONS = [
    ("DPAD_UP", 0x0001), ("DPAD_DOWN", 0x0002), ("DPAD_LEFT", 0x0004),
    ("DPAD_RIGHT", 0x0008), ("START", 0x0010), ("BACK", 0x0020),
    ("LS", 0x0040), ("RS", 0x0080), ("LB", 0x0100), ("RB", 0x0200),
    ("A", 0x1000), ("B", 0x2000), ("X", 0x4000), ("Y", 0x8000),
]


class XInputGamepad:
    """XINPUT 直读（ctypes xinput1_4）。标签为 XINPUT 物理键语义，
    与 mGBA SDL 索引映射可能不同 —— 仅作 pygame 不可用时的兜底 + --test 对照。"""

    def __init__(self, index: int = 0):
        try:
            self._xinput = ctypes.windll.xinput1_4
        except OSError:
            self._xinput = ctypes.windll.xinput1_3
        self.index = index
        if self._read() is None:
            raise NoGamepadError("XInput 未检测到控制器（接收器插好/手柄开机了吗）")
        self._state: dict[str, bool] = {}
        self._axis_last: dict[str, bool] = {}
        self.poll()  # 与 Gamepad 同样先填充初始状态，防首轮全键误报

    def _read(self) -> XINPUT_STATE | None:
        st = XINPUT_STATE()
        err = self._xinput.XInputGetState(self.index, ctypes.byref(st))
        if err != 0:  # 未连接/断开
            return None
        return st

    def _axis_active(self, name: str, v: float, neg: bool = False,
                     trig: bool = False) -> bool:
        last = self._axis_last.get(name, False)
        if trig:
            act = v > 0.5 if not last else v > 0.1
        elif neg:
            act = v < -0.5 if not last else v < -0.1
        else:
            act = v > 0.5 if not last else v > 0.1
        self._axis_last[name] = act
        return act

    def poll(self) -> list[tuple[str, bool]]:
        st = self._read()
        cur: dict[str, bool] = {}
        if st is not None:
            g = st.Gamepad
            for name, mask in _XI_BUTTONS:
                cur[name] = bool(g.wButtons & mask)
            cur["LT"] = self._axis_active("LT", g.bLeftTrigger / 255.0, trig=True)
            cur["RT"] = self._axis_active("RT", g.bRightTrigger / 255.0, trig=True)
            cur["LSTICK_L"] = self._axis_active("LSTICK_L", g.sThumbLX / 32768.0, neg=True)
            cur["LSTICK_R"] = self._axis_active("LSTICK_R", g.sThumbLX / 32768.0)
            cur["LSTICK_U"] = self._axis_active("LSTICK_U", g.sThumbLY / 32768.0, neg=True)
            cur["LSTICK_D"] = self._axis_active("LSTICK_D", g.sThumbLY / 32768.0)
        changes = []
        for label, v in cur.items():
            if self._state.get(label) != v:
                changes.append((label, v))
        self._state = cur
        return changes

    @property
    def name(self) -> str:
        return f"XInput 控制器 {self.index}"


def make_gamepad(deadzone: float = 0.25, threshold: float = 0.5,
                 prefer_xinput: bool = False) -> Gamepad | XInputGamepad:
    """优先 pygame/SDL（与 mGBA 索引一致）；失败回退 XInput 直读。"""
    if not prefer_xinput:
        try:
            return Gamepad(deadzone=deadzone, threshold=threshold)
        except NoGamepadError:
            pass
    return XInputGamepad()  # 连接失败时 XInputGamepad 自身抛 NoGamepadError
