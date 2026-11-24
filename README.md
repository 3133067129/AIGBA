# AI 玩宝可梦绿宝石386

AI 自主游玩「绿宝石386v2.1个人修复版」（Emerald 386 ROM hack，中文汉化版）。
目标：获取 8 个徽章 → 击败联盟冠军 → 捕获全部 386 只宝可梦。

方案：**纯视觉 + 模拟键盘/鼠标**，跑在**真实 mGBA.exe 窗口**上
（PrintWindow 捕获 + PostMessage/Lua 输入），由用户手柄示范录制、AI 回放验证学习。

## 当前状态（2026-08-08）

**窗口模式录制-回放验证链已跑通**：

- ✅ **手柄旁路录制**：用户用手柄在真实 mGBA 里玩（SDL 映射用户内部配置），
  录制器旁路读手柄 + 抓屏 + 监控存档文件，完全不打扰游戏
- ✅ **回放验证**：PostMessage/Lua 双通道回放 + 画面驱动自愈（fix 系列），
  **0-121s 关键段**（睡眠唤醒→起床对话→第二对话→走路段开始）与录制逐帧对齐
  （对齐帧 54-66%、发散帧 <10%）
- ✅ **键盘屏突破**：命名界面期间 PostMessage 全灭（Qt 焦点偏离），
  改 Lua 直注入（emu:addKey/clearKey 绕过 Qt 键盘系统）打通
- ✅ **睡眠唤醒破解**：睡眠场景 A 键弹「再睡」对话框永远无法唤醒，
  RIGHT 长按 1.2s 唤醒（短按 0.15s 失效）
- ⏳ **走路段分叉（当前卡点）**：走路段 PostMessage 送达存在帧相位抖动
  （±16ms）→ 人物位置差累积 → **转场目标由人物站位决定**（386 hack 特性）
  → 位置差跨过门口触发阈值 = 概率性走错地图 → 分叉 → 转场动画卡死 →
  mGBA 崩溃。0-121s 已对齐证明录制数据可靠，走路段是**回放保真度硬限制**

## 架构

```
手柄(SDL) ──pygame.joystick──> tools/gamepad_demo_recorder.py（旁路录制）
        ──> data/demos/demo_*.jsonl（按键/快照/存档事件）
        ──> tools/replay_demo_window.py（PostMessage/Lua 回放 + 画面自愈 + --verify 抓屏）
        ──> 块级 diff 对录制 → data/demos/replay/<stem>/report.txt（✅/✗）
        ──> tools/demo_knowledge_window.py（轨迹 → 知识 data/knowledge/demos/）
```

- **输入三层事实**（2026-08-08 多次实证）：
  1. SDL gamepad（用户录制）——绕过 Qt 键盘系统，始终有效（回放不可用，手柄被占用）
  2. Lua 直注入（键盘屏段）——`emu:addKey(N)/clearKey(N)` 注入 core，
     键盘屏期间 PostMessage 完全无效，必须 Lua；每命令冻结核心 ~250ms
  3. PostMessage（对话/走路段）——对话屏有效（需窗口聚焦）；本机火绒 HIPS
     拦 SendInput，PostMessage 是唯一可行键盘路径
- **回放自愈体系**（画面驱动，PostMessage 时序抖动全靠兜底）：
  RIGHT 长按唤醒 → A×8 补推进 → 第二对话行级判定补 A → 走路段动态门控
  （`walk_offset` 自适应唤醒时刻浮动）→ safe_send 窗口句柄失效自愈
- **视觉**：qwen2.5vl:7b（Ollama，`src/perception/llm_vision.py`）——
  7B 对 GBA 小像素场景识别不可靠，只用于「同/不同」粗判；可靠验证靠像素 diff
- **第一代无头架构**（已不是主战场）：mgba-python 核心（`src/emulator/mgba_core.py`）、
  内存状态提取（`src/state/extractor.py`）、DFS 格级探索（`src/control/dfs.py`）、
  `src/brain/` 引导。成果保留：家结构破解、坐标标定、攻略结构化、savestate 教训

## 环境要求

- Windows + Python **3.14**（一律 `py -3.14`）+ pywin32（PostMessage/PrintWindow）
- mGBA.exe 在仓库根目录；ROM 路径在 `config/settings.yaml` `rom.path`
- 火绒 HIPS 拦截 SendInput（回放必须 PostMessage 直发窗口）
- Ollama + qwen2.5vl:7b（`ollama pull qwen2.5vl:7b`）；GPU 故障自动 fallback CPU

## 使用

```bash
# 录制（用户用手柄示范；--test 先逐键核对手柄编码）
py -3.14 tools/gamepad_demo_recorder.py --launch [--test]

# 回放 + 验证（核心验证手段；--to N 只跑前 N 秒）
py -3.14 tools/replay_demo_window.py demo_xxx.jsonl --launch --verify --to 135
py -3.14 tools/replay_demo_window.py demo_xxx.jsonl --launch --verify   # 全段

# 诊断三板斧
py -3.14 -u data/tmp_timeline.py data/demos/replay/<stem> [起点s] [终点s]  # 逐帧最优匹配+漂移
py -3.14 -u data/tmp_ascii.py rp|rec [t_ms_abs] [y0 y1] [x0 x1]            # 帧区域 ASCII 亮度图

# 冒烟 / 锁分析
py -3.14 tools/smoke_window.py
py -3.14 tools/analyze_lock.py
```

验证报告判定：对齐帧（最优 diff <0.25）占比、发散帧（>0.55）<10%、中位 diff <0.20 → ✅。
匹配窗口 ±5s；验证必须 `--clean-sav` 冷启动（savestate 陷阱，见下）。

## 目录

```
config/      settings.yaml（ROM/LLM 配置）+ offsets.json
src/
  emulator/  window_backend.py（PostMessage 输入/PrintWindow 捕获/找窗）、gamepad.py（旁路手柄）、mgba_core.py（第一代无头）
  perception/ screen.py（diff_ratio 逐像素不等比）、llm_vision.py（qwen2.5vl）
  control/   visual_controller.py（纯画面移动判定）、player_tracker.py（精灵模板匹配）、dfs.py（第一代）
  state/     extractor.py（第一代内存提取）
tools/       gamepad_demo_recorder.py（录制）、replay_demo_window.py（回放验证）、
             demo_knowledge_window.py（知识）、smoke_window.py、analyze_lock.py、诊断/破解脚本
data/        demos/（录制轨迹+快照+回放验证）、knowledge/（攻略+轨迹知识）、checkpoints/
third_party/ libmgba-py（第一代构建产物，仍保留）
```

## 已知 hack 问题（386 修复版特有）

1. **savestate 陷阱**：过场/对话动画中保存的 savestate 恢复后状态不稳定（位置漂移、
   移动锁）。**冷启动单进程是确定性方案**；回放验证必须 `--clean-sav`
2. **转场目标由人物站位决定**（2026-08-08 走路段分叉根因）：人物在门口位置差几步
   → 地图转场去往不同房间。走路段位置差累积 = 概率性分叉
3. **转场动画帧全相似**：所有转场（黑白闪）帧互相 diff 极小——分叉判定必须结合
   前后帧序列，单帧全谱匹配会被转场帧误导
4. **睡眠「再睡」对话框**：睡眠场景 A 键弹「再睡」对话框（mean 66-70）无法唤醒，
   必须 RIGHT 长按 1.2s
5. **1F 门洞 bug**：1F 走廊 (120,128) 面向 UP = "进门洞"死路；真门在 2F 东侧 (152,112)
   面向 RIGHT
6. **未白镇移动锁**：出门后玩家被 hack 剧情状态机锁死，MOVE_FLAG(0x03000F2C)
   写 0 不稳定（第一代无头时代卡点；窗口模式尚未重试）
7. **坐标污染 / Ollama GPU 不稳定**：坐标读数受 NPC 动画影响；LLM GPU 后端
   `memory layout cannot be allocated` → 自动 fallback CPU

## 阶段

- Phase 0 ✅ 环境：mgba-python 构建、qwen2.5vl 读图、冒烟测试
- Phase 1 🔄 走路/对话/菜单闭环：新游戏✅ 进家✅ 调钟✅ 出门✅ 手柄示范录制✅
  回放验证 0-121s ✅ / 走路段分叉 ⏳
- Phase 2 战斗闭环（练级/捕获/逃跑，遭遇表自动记录）
- Phase 3 主线 8 徽章 + 联盟冠军
- Phase 4 全图鉴 386（覆盖探索 + 捕获工程）
