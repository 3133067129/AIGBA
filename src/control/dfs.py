"""精确格级 DFS 探索器：走遍当前地图找出口/户外。

核心原语 move_one(d)：朝 d 走恰好 1 格（坐标对齐，动画结束才返回），
保证格子记录精确（此 hack 坐标是像素级，动画中途读数漂移）。

DFS：记录已访问格子，优先未访问方向，死路回溯。
出口判定：bright > 阈值（室内 44-74，户外 141）。

用法:
    from src.control.dfs import DfsExplorer
    ex = DfsExplorer(emu, extractor, controller, outdoor_bright=100)
    result = ex.run(max_steps=800)   # {"outdoor": bool, "path": [...], "visited": n}
"""
from __future__ import annotations

import time

from src.emulator.mgba_core import Emulator
from src.state.extractor import GameStateExtractor
from src.control.controller import Controller

OFFSET = {"UP": (0, -1), "RIGHT": (1, 0), "DOWN": (0, 1), "LEFT": (-1, 0)}
BACK = {"UP": "DOWN", "DOWN": "UP", "LEFT": "RIGHT", "RIGHT": "LEFT"}
DIRS = ["UP", "RIGHT", "DOWN", "LEFT"]


class DfsExplorer:
    def __init__(self, emu: Emulator, extractor: GameStateExtractor,
                 controller: Controller, outdoor_bright: float = 100.0,
                 on_step=None, unlock_dialog: bool = True,
                 door_drop: float = 0.0):
        self.emu = emu
        self.ex = extractor
        self.ctrl = controller
        self.outdoor_bright = outdoor_bright
        self.on_step = on_step
        # 撞墙时按 A 解锁剧情对话（室内场景用）；户外导航禁用防误触门
        self.unlock_dialog = unlock_dialog
        # 门检测：移动后亮度骤降 > door_drop = 进门（户外导航用，
        # 设为 0 关闭）。命中时走回原地并视为撞墙（跳过该方向）。
        self.door_drop = door_drop
        # 最近一次 door_drop 命中的方向（供外部识别 warp 门位置）
        self.last_door_drop = None

    # ---------- 格级原语 ----------

    def _grid(self) -> tuple:
        st = self.ex.extract(self.emu)
        return (st.player_x // 16, st.player_y // 16)

    def _settle(self, frames: int = 40) -> None:
        self.emu.run_frames(frames)

    def _try_move(self, d: str, tgt: tuple | None) -> tuple | None:
        """按住 d 方向逐帧检测：到达目标格（或任意新格）即返回；判定撞墙返回 None。

        2026-08-06 修正：玩家未对齐格中心时（上次 move_one 返回在"刚跨入
        新格边界"，动画还差 ~8px 到中心），按新方向键会先"补走"当前朝向
        余步（~15 帧，仍在原格内）再转身移动——20 帧撞墙窗口不够，误判
        撞墙。改为 60 帧判定 + 移动成功后收尾 8 帧滑到格中心（位置精确，
        后续按键直接转身，无补走）。
        """
        from src.emulator.keys import Key
        g0 = self._grid()
        self.ctrl.emu.press_hold(getattr(Key, d))
        unchanged = 0
        for _ in range(120):  # 最多 120 帧（补走+转身+走格 ~40 帧）
            self.ctrl.emu.run_frames(1)
            g = self._grid()
            if g != g0:
                self.ctrl.emu.release()
                self.ctrl.emu.run_frames(8)  # 收尾：滑到格中心（无按键，不移出当前格）
                return g
            unchanged += 1
            if unchanged >= 60:
                break  # 撞墙（60 帧 ≈ 1 秒，含补走余步）
        self.ctrl.emu.release()
        return None

    def move_one(self, d: str) -> tuple | None:
        """朝 d 移动，返回新格子（可能超过 1 格——楼梯自动滑行）；撞墙返回 None。

        Emerald 楼梯：按方向自动斜向滑行多格，接受任意实际到达的格子。
        撞墙时可能被剧情对话锁定（进门触发妈妈对话）→ 按 A 解锁重试。
        unlock_dialog=False 时（户外导航）不做 A 解锁，防误触门/对话。
        """
        g0_bright = float(self.emu.screenshot().mean())
        self.last_door_drop = None
        r = self._try_move(d, None)
        if r is not None:
            if self.door_drop > 0:
                # 门检测：移动后亮度骤降 = 进了室内（门）→ 走回并视为撞墙
                b = float(self.emu.screenshot().mean())
                if b < g0_bright - self.door_drop:
                    self.last_door_drop = d
                    self._try_move(BACK[d], None)
                    return None
            return r
        if not self.unlock_dialog:
            return None
        from src.emulator.keys import Key
        self.emu.press(Key.A, 8)
        self.emu.run_frames(50)
        return self._try_move(d, None)

    def probe(self, d: str) -> tuple | None:
        """探测 d 方向：能走则走 1 格并返回新格子（保持在新格子）。"""
        return self.move_one(d)

    # ---------- DFS（右墙法则 + visited 过滤）----------

    def run(self, max_steps: int = 800, confirm=None,
            confirm_every: int = 8) -> dict:
        """confirm(step, grid, emu) -> bool：每 confirm_every 步调用，
        返回 True 视为到达目标（如城镇中心判定，LLM 慢速确认）。"""
        visited: set = {self._grid()}
        stack: list[tuple] = []  # (父格子, 来路方向)
        path: list[tuple] = []
        t0 = time.time()
        g = self._grid()
        facing = "UP"
        for steps in range(max_steps):
            bright = float(self.emu.screenshot().mean())
            if bright > self.outdoor_bright:
                if self.on_step:
                    self.on_step(f"🎉 户外！bright={bright:.0f} pos={g}")
                return {"outdoor": True, "grid": g, "visited": len(visited),
                        "steps": steps + 1, "path": path}
            if confirm is not None and steps % confirm_every == 0:
                if confirm(steps, g, self.emu):
                    if self.on_step:
                        self.on_step(f"🎯 目标达成 pos={g}")
                    return {"target": True, "grid": g, "visited": len(visited),
                            "steps": steps + 1, "path": path}
            # 右墙法则顺序：右转 → 直走 → 左转 → 掉头
            right = {"UP": "RIGHT", "RIGHT": "DOWN", "DOWN": "LEFT", "LEFT": "UP"}[facing]
            order = [right, facing,
                     {"UP": "LEFT", "LEFT": "DOWN", "DOWN": "RIGHT", "RIGHT": "UP"}[facing],
                     BACK[facing]]
            moved = False
            for d in order:
                ng = self.move_one(d)
                if ng is None:
                    continue  # 撞墙
                if ng in visited:
                    self.move_one(BACK[d])  # 已访问：回原位试下一方向
                    continue
                # 走新格子
                facing = d
                visited.add(ng)
                path.append((g, d))
                stack.append((g, d))
                g = ng
                moved = True
                if self.on_step:
                    self.on_step(f"→({g[0]},{g[1]}) {d} bright={bright:.0f} "
                                 f"visited={len(visited)}")
                break
            if moved:
                continue
            # 4 方向全撞墙/全访问 → 回溯
            if not stack:
                if self.on_step:
                    self.on_step("已遍历全部可达格子，未找到出口")
                break
            prev_g, came = stack.pop()
            self.move_one(BACK[came])
            g = prev_g
            if self.on_step:
                self.on_step(f"←回溯 ({g[0]},{g[1]})")
        return {"outdoor": False, "grid": g, "visited": len(visited),
                "steps": steps + 1, "path": path}
