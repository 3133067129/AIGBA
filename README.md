# AI 玩宝可梦绿宝石386

AI 自主游玩「绿宝石386v2.1个人修复版」（Emerald 386 ROM hack，中文汉化版）。
目标：获取 8 个徽章 → 击败联盟冠军 → 捕获全部 386 只宝可梦。

## 当前状态（2026-08-06）

**Phase 1（走路/对话/菜单闭环）进行中**：

- ✅ **新游戏确定性流程**：标题 → 按 A 变焦 → 等 300 帧 → DOWN+A×2 → 菜单（bright~173）→ A 选新游戏（纯像素判定，无 LLM）
- ✅ **开场推进**：advance_with_watchdog 推进博士/搬家剧情 → 玩家在家 2F 可控（方向验证判定：按 UP 后 y 减）
- ✅ **家结构破解**（修复版 DFS 实证）：家 = 2F 大地图（x0-152 y0-208，63 格密闭）+ 1F 入口区（x96-144 y112-224，连通西侧走廊 x8-128）
- ✅ **出门机制**：家 2F 东侧 (152,112) 面向 **RIGHT** = 出门 → 未白镇 (136,112) bright 142（A 键=回家，双向）
- ✅ **坐标标定**：player_x=0x02020650, player_y=0x02020652（u16 像素，16px/格）
- ✅ **攻略结构化**：pmcenter.cn 绿宝石386 攻略全文 → `data/knowledge/walkthrough.json`（38 步，含全部道馆馆主/四天王配置）
- ⏳ **未白镇移动锁**（当前卡点）：出门后玩家被 hack 的剧情/转场状态机锁死，四方向按键无效；MOVE_FLAG(0x03000F2C) 写 0 不稳定、savestate 恢复全部损坏（详见下方「已知 hack 问题」）

## 架构

- **模拟器**：mgba-python 无头核心（`src/emulator/mgba_core.py` 是唯一接触 libmgba 的层）
  - 内存读写（含 raw_write 修复）、帧步进、按键、savestate、截图
- **状态感知**：纯内存读取（`src/state/extractor.py` + `offsets.json`），战斗文本 GBK 解码（Phase 2 用）
- **视觉**：Ollama qwen2.5vl:7b（`src/perception/llm_vision.py`，provider 可插拔）
  - GPU 后端故障 → 自动 fallback 纯 CPU；num_ctx 4096（默认 128k 加载失败）
- **控制**：`src/control/dfs.py` 格级 DFS 探索器（右墙法则 + visited 过滤 + 撞墙 A 解锁 + 门检测），
  `src/control/controller.py` 像素级界面判定（对话框/菜单）
- **引导**：`src/brain/new_game.py`（标题/菜单/开场推进）、`src/brain/guide.py`（攻略驱动 agent，待实跑）
- **预览**：`src/emulator/preview.py` pygame 实时窗口（倍速 +/-、暂停 p、人工接管键盘转发）

## 环境要求

- Windows + Python 3.11（用 `.venv\Scripts\python.exe`，PATH 上的 pip 可能属于其他版本）
- mgba-python 需源码构建（无官方 Windows wheel），产物在 `third_party/libmgba-py/build/win64/mgba/`
- Ollama + qwen2.5vl:7b（`ollama pull qwen2.5vl:7b`）
  - 显存/内存不足时：`options: {num_ctx: 4096, num_gpu: 0}`（llm_vision 已自动 fallback）

## 使用

```bash
.venv\Scripts\python.exe src/main.py smoke           # 冒烟测试
.venv\Scripts\python.exe src/main.py verify-offsets  # 标定内存偏移
.venv\Scripts\python.exe src/main.py new-game        # 新开档
.venv\Scripts\python.exe tools/demo_play.py          # 带预览窗的 AI 演示（推荐观看）
.venv\Scripts\python.exe tools/view_play.py [state] [speed]  # 预览 + 人工接管
.venv\Scripts\python.exe tools/unlock_town2.py       # 冷启动→出门→未白镇解锁尝试
.venv\Scripts\python.exe tools/guide_clock.py        # 冷启动全流程（调钟）验证
.venv\Scripts\python.exe tools/demo_recorder.py      # 人工演示录制（未白镇试解锁）
.venv\Scripts\python.exe tools/replay_demo.py demo_xxx.jsonl  # 确定性回放验证
.venv\Scripts\python.exe tools/demo_knowledge.py demo_xxx.jsonl  # 轨迹→知识入库
```

预览窗快捷键：方向键/A/B = 人工接管（自动暂停 AI）、`+`/`-` 调速、`p` 暂停、`ESC` 退出。

## 目录

```
config/      settings.yaml + offsets.json（内存偏移标定产物）
src/
  emulator/  mgba_core.py（libmgba 封装）、keys.py、preview.py
  state/     extractor.py（内存→GameState）、offsets.py、pokemon_decrypt.py
  perception/ llm_vision.py（Ollama/Claude/mock）、screen.py
  brain/     new_game.py（标题→新游戏→开场）、guide.py（攻略驱动 agent）
  control/   dfs.py（格级 DFS）、controller.py（界面判定/移动）
  persistence/ checkpoints.py、knowledge_store.py、metrics.py
tools/       冷启动/破解/验证脚本（见下）
data/        knowledge/（攻略+进度）、checkpoints/（savestate）、tmp_dumps/
backups/     原 .sav 备份
third_party/ libmgba-py（源码构建）
```

## 已知 hack 问题（重要！）

1. **1F 门洞 bug**：1F 走廊 (120,128) 面向 UP 按方向键 = "进门洞"（bright 70→120），
   之后 4 方向/A/B/START/L/R 全无效——死路。真门在 2F 东侧 (152,112) 面向 RIGHT。
2. **savestate 陷阱**：过场/对话动画中保存的 savestate 恢复后状态不稳定（位置漂移、
   移动锁）。**冷启动单进程是确定性方案**。静止可控态保存的也会漂移（未白镇状态）。
3. **未白镇移动锁**：从门到达未白镇后玩家被锁（画面正常 bright 142、NPC 动画活跃、
   但按键无效）。MOVE_FLAG=0x03000F2C 写 0 可解锁一次（不可复现）；每帧写 0 反而更糟。
4. **坐标污染**：未白镇场景 0x02020650 读数受 NPC 动画影响（按 UP 可能 x 变化）——
   移动判定必须用"方向验证"（UP → y 减）。
5. **Ollama GPU 后端不稳定**：`memory layout cannot be allocated` → 需 num_gpu=0 纯 CPU。

## 破解工具（tools/）

- 冷启动：`save_intro_outdoor.py`（新游戏→可控→保存）、`unlock_town2.py`（冷启动→出门→解锁）、
  `clock_then_door.py`（含调钟）、`guide_clock.py`（调钟全流程验证）
- 探索：`explore_2f_full.py` / `explore_1f_full.py`（修复版 DFS 全图）、`west_explore.py`、
  `town_explore.py`（未白镇）、`scan_doors*.py`（建筑门扫描）
- 调试：`debug_title.py`/`debug_menu.py`（新游戏时序）、`debug_move.py`（移动判定）、
  `find_move_flag.py`（行为标定移动锁）、`test_pixel.py`（像素级移动验证）
- 状态检查：`check_states.py`（遍历 savestate 报位置/亮度）
- 人工：`view_play.py` / `demo_play.py`（预览窗 + 键盘接管）
- 演示学习（人工示范 → AI 学习）：
  `demo_recorder.py`（录制人工操作轨迹）→ `replay_demo.py`（确定性回放验证）
  → `demo_knowledge.py`（轨迹 → 路径/事件/成功片段知识入库）
  `data/demos/*.jsonl` 为帧级精确轨迹（按键事件+状态快照+标签），
  `data/knowledge/demos/*.md` 为提取后的可读知识。

## 阶段

- Phase 0 ✅ 环境：mgba-python 源码构建、qwen2.5vl 中文读图、冒烟测试、队伍解密实证
- Phase 1 🔄 走路/对话/菜单闭环：新游戏✅ 进家✅ 调钟✅ 出门✅ 未白镇解锁⏳
  （解锁后：邻居→救博士→选御三家→103路→图鉴→第一道馆）
- Phase 2 战斗闭环（练级/捕获/逃跑，遭遇表自动记录）
- Phase 3 主线 8 徽章 + 联盟冠军
- Phase 4 全图鉴 386（覆盖探索 + 捕获工程）
