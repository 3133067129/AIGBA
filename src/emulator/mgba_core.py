"""mgba-python 无头核心封装 —— 项目里唯一接触 libmgba 的模块。

API 约定（已从 mgba-src/src/platform/python 源码确认）：
- 内存索引为区域相对偏移：gba.wram.u8[0x25A08] == 绝对地址 0x02025A08
- 按键：core.set_keys(*key_names) / add_keys / clear_keys，常量如 GBA.KEY_A
- 截图：image.Image(w,h) → core.set_video_buffer(img) → run_frame() → img.to_pil()
- 状态：core.save_raw_state() / load_raw_state(bytes)
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import numpy as np

import mgba
import mgba.gba as gba
import mgba.image as image
import mgba.vfs as vfs

# 静音 libmgba 默认日志（BIOS/DMA 噪音）
try:
    import mgba.log
    mgba.log.silence()
except Exception:
    pass

from .keys import Key, KEY_MAP, to_mgba_keys

# 内存区域基址（libmgba 常量，索引 = 绝对地址 - 基址）
BASE_WORKING_RAM = 0x02000000  # EWRAM
BASE_WORKING_IRAM = 0x03000000  # IWRAM
BASE_CART_SRAM = 0x0E000000


class EmulatorError(RuntimeError):
    pass


class Emulator:
    """无头 GBA 模拟器封装。单线程使用；预览线程只读 screenshot()。"""

    def __init__(self, rom_path: str | Path, sav_path: str | Path | None = None,
                 sav_footer_bytes: int = 0):
        self.rom_path = Path(rom_path)
        self.sav_path = Path(sav_path) if sav_path else None
        self.sav_footer_bytes = sav_footer_bytes

        if not self.rom_path.exists():
            raise EmulatorError(f"ROM not found: {self.rom_path}")

        try:
            self.core = mgba.core.load_path(str(self.rom_path))
        except Exception as e:
            raise EmulatorError(f"Failed to load ROM {self.rom_path}: {e}") from e
        if self.core is None:
            raise EmulatorError(f"mgba could not open {self.rom_path}")

        # load_path 已按平台返回 GBA 实例（含 memory/wram 视图），勿再包装
        self.gba = self.core

        # 视频 buffer 必须在 reset 之前设置，否则画面不渲染进 buffer
        self._video_dims = tuple(self.core.desired_video_dimensions()) if self.core.desired_video_dimensions() else (240, 160)
        self._video = image.Image(*self._video_dims)
        self.core.set_video_buffer(self._video)

        if self.sav_path:
            self.load_save(self.sav_path)

        # 重置到初始状态（加载存档后执行）
        self.core.reset()

        # 每帧回调（供预览窗实时刷新；None = 关闭）
        self._on_frame = None
        # 输入钩子（帧级采样版）：每帧 run_frame() 执行前采样「请求按键集」，
        # 变化时调用 cb(down: tuple[Key, ...], frame: int)。
        # frame = 当前 frame_counter（即将执行的帧号）。
        # 录制语义：t = 按键生效帧（该帧执行前）；回放时 fc==t 设置 → 同帧生效。
        # 与 pygame 事件延迟无关（事件延迟只影响按键「哪帧生效」，不影响记录语义）。
        # 注意：libmgba 绑定无 keysActive 属性可读，请求集由 press_hold/release 显式维护。
        self._key_hook = None
        self._last_keys: tuple[Key, ...] = ()
        self._requested_keys: tuple[Key, ...] = ()

    def set_key_hook(self, cb) -> None:
        """注册输入钩子 cb(down: tuple[Key, ...], frame: int)，按键集变化时（帧前采样）调用。"""
        self._key_hook = cb
        self._last_keys = self._requested_keys

    @property
    def on_frame(self):
        """注册回调 on_frame(emulator)，每跑一帧后调用（预览窗用）。"""
        return self._on_frame

    @on_frame.setter
    def on_frame(self, cb):
        self._on_frame = cb

    # ---------- 生命周期 ----------

    def load_save(self, sav_path: str | Path) -> bool:
        """加载电池存档。若文件带多余 footer 字节导致失败，自动截断重试。"""
        sav_path = Path(sav_path)
        candidates = [sav_path]
        temp = None
        if self.sav_footer_bytes > 0:
            total = sav_path.stat().st_size
            # 常见存档大小：128KB = 131072 字节（绿宝石）；超出则视为带 footer
            if total > 131072:
                temp = Path(tempfile.mktemp(suffix=".sav"))
                with open(sav_path, "rb") as f, open(temp, "wb") as out:
                    shutil.copyfileobj(f, out, length=total - self.sav_footer_bytes)  # noqa: F821
                candidates = [sav_path, temp]
        for cand in candidates:
            vf = vfs.open_path(str(cand), "r+b")
            if vf is None:
                continue
            if self.core.load_save(vf):
                return True
        return False

    def reset(self) -> None:
        self.core.reset()

    def run_frames(self, n: int = 1) -> None:
        for _ in range(n):
            # 帧前采样：记录「即将执行的帧」实际读取的按键集
            if self._key_hook is not None:
                keys = self._requested_keys
                if keys != self._last_keys:
                    self._last_keys = keys
                    self._key_hook(keys, self.core.frame_counter)
            self.core.run_frame()
            if self._on_frame is not None:
                self._on_frame(self)

    def step(self) -> None:
        self.core.step()

    @property
    def frame_counter(self) -> int:
        return self.core.frame_counter

    # ---------- 按键 ----------

    def _set(self, keys: tuple[Key, ...], method) -> None:
        # 绑定要求 int 键常量（GBA.KEY_UP 等），字符串名字需转成整型
        values = [getattr(self.core, name) for name in to_mgba_keys(*keys)]
        getattr(self.core, method)(*values)

    def press(self, key: Key, frames: int = 8) -> None:
        """按住按键 frames 帧后松开（单次点击）。"""
        self.press_hold(key)
        self.run_frames(frames)
        self.release()

    def press_sequence(self, keys: list[Key], hold_frames: int = 8) -> None:
        for k in keys:
            self.press(k, hold_frames)

    def hold(self, keys: list[Key], frames: int) -> None:
        self._set(tuple(keys), "set_keys")
        self._requested_keys = tuple(keys)
        self.run_frames(frames)
        self.core.clear_keys()
        self._requested_keys = ()

    def press_hold(self, *keys: Key) -> None:
        """开始按住（配合 release 使用，供逐帧轮询场景）。"""
        self._set(tuple(keys), "set_keys")
        self._requested_keys = tuple(keys)

    def release(self) -> None:
        # 注意：binding 的 clear_keys() 无参调用是 no-op（keysActive &= ~0），
        # 必须用 set_keys() 无参（=0）直接整体清空，否则按键永远保持按下。
        self.core.set_keys()
        self._requested_keys = ()

    def release_all(self) -> None:
        self.core.clear_keys()
        self._requested_keys = ()

    # ---------- 内存 ----------

    def read(self, addr: int, n: int) -> bytes:
        """读 n 字节（EWRAM 绝对地址）。"""
        if 0x02000000 <= addr < 0x03000000:
            base = BASE_WORKING_RAM
            mem = self.gba.memory.wram
        elif 0x03000000 <= addr < 0x04000000:
            base = BASE_WORKING_IRAM
            mem = self.gba.memory.iwram
        else:
            raise EmulatorError(f"Unsupported memory address: 0x{addr:08X}")
        idx = addr - base
        return bytes(mem.u8[idx:idx + n])

    def u8(self, addr: int) -> int:
        return self.read(addr, 1)[0]

    def u16(self, addr: int) -> int:
        return int.from_bytes(self.read(addr, 2), "little")

    def u32(self, addr: int) -> int:
        return int.from_bytes(self.read(addr, 4), "little")

    def write(self, addr: int, data: bytes) -> None:
        """写 n 字节（EWRAM/IWRAM 绝对地址）。供 hack 应急（坐标瞬移等）。"""
        if 0x02000000 <= addr < 0x03000000:
            base = BASE_WORKING_RAM
            mem = self.gba.memory.wram
        elif 0x03000000 <= addr < 0x04000000:
            base = BASE_WORKING_IRAM
            mem = self.gba.memory.iwram
        else:
            raise EmulatorError(f"Unsupported memory address: 0x{addr:08X}")
        idx = addr - base
        # 注意：mem.u8[idx]=v 的 __setitem__ 有绑定 bug（漏 segment 参数），
        # 必须用 raw_write(addr, value) 4 参数版
        for i, b in enumerate(data):
            mem.u8.raw_write(idx + i, b)

    def search(self, value, addr_min: int = 0x02000000, addr_max: int = 0x04000000):
        """内存搜索（用于偏移标定）。返回 (绝对地址, 值) 列表。"""
        results = self.gba.memory.wram.search(value)
        if addr_min >= 0x03000000:
            results += self.gba.memory.iwram.search(value)
        return [(r.address, r.value) for r in results
                if addr_min <= r.address < addr_max]

    # ---------- 截图 ----------

    def screenshot(self) -> np.ndarray:
        """返回当前帧画面 240x160x3 uint8 RGB（H,W,C）。

        注意：不推进模拟器。调用方需已 run_frames 至少一帧，
        否则返回的是缓冲区内旧帧。
        """
        arr = np.asarray(self._video.to_pil(), dtype=np.uint8)  # RGBA HxWx4
        return arr[:, :, :3]

    # ---------- 存档 ----------

    def save_state(self) -> bytes:
        return bytes(self.core.save_raw_state())

    def load_state(self, data: bytes) -> bool:
        return bool(self.core.load_raw_state(data))
