# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目

AI 自主游玩「绿宝石386v2.1个人修复版」（Emerald 386 ROM hack，中文汉化版）：
8 徽章 → 冠军 → 全 386 图鉴。方案是**纯视觉 + 模拟键盘/鼠标**，跑在**真实 mGBA.exe 窗口**上（PrintWindow 捕获 + PostMessage/Lua 输入）。

**当前阶段（2026-08-08）**：窗口模式录制-回放验证链已跑通。0-121s 关键段（睡眠唤醒→起床对话→第二对话→走路段开始）回放与录制逐帧对齐 ✅。走路段（121s+）回放存在保真度硬限制（见「已知问题」），全段 736s 验证被走路段分叉阻塞。旧 README 的 mgba-python 无头架构（`src/emulator/mgba_core.py`、`src/brain/`、DFS 探索）是**第一代，已不是主战场**——主战场是 `tools/*_window.py` 系列。

## 环境与常用命令

- Windows + Python **3.14**，一律用 `py -3.14`（不是 `.venv`，窗口脚本需 pywin32）
- 火绒 HIPS 拦 SendInput → **PostMessage 直发**是唯一可行键盘输入（详见架构）
- mGBA.exe 在本仓库根目录；ROM 路径在 `config/settings.yaml` `rom.path`

```bash
# 录制（旁路：用户用手柄玩，录制器读手柄+抓屏，不打扰 mGBA）
py -3.14 tools/gamepad_demo_recorder.py --launch [--test]   # --test 逐键核对手柄原始编码

# 回放 + 验证（核心验证手段）
py -3.14 tools/replay_demo_window.py demo_20260807_234704.jsonl --launch --verify --to 135
# 验证报告 → data/demos/replay/<demo-stem>/report.txt（✅ 对齐 / ✗ 发散）
# 不带 --to = 全段；--clean-sav 从无存档冷启动（录制起点必须一致）

# 关键段诊断工具（必须会用的三板斧）
py -3.14 -u data/tmp_timeline.py data/demos/replay/<stem> [起点s] [终点s]   # 逐帧最优匹配+漂移
py -3.14 -u data/tmp_ascii.py rp|rec [t_ms_abs] [y0 y1] [x0 x1]             # 帧区域 ASCII 亮度图
# 说明：回放帧名 t{abs:07d}，abs 含 t_base 偏移（回放首帧 297）；录制帧名是录制自身 abs（16 起）。
# rp 参数必须是 abs 时间（相对+297）；帧在 ~500ms 网格上，传具体帧名数字。

# 全谱匹配（定位回放状态在录制时间线上的位置，找分叉点）：
# 写脚本对回放帧与全部录制帧做 diff_ratio 最小匹配（±5s 窗口是 tmp_timeline 的局限）
```

## 核心架构（需要读多文件才懂）

### 录制-验证闭环（主战场）

```
手柄(SDL) ──pygame.joystick──> tools/gamepad_demo_recorder.py（旁路，~125Hz 轮询）
        ──> data/demos/demo_*.jsonl（按键事件 {t_ms,key,down} + 快照事件 + save/load/jump）
        ──> tools/replay_demo_window.py（PostMessage/Lua 回放 + 画面驱动自愈 + --verify 抓屏）
        ──> data/demos/replay/<stem>/t*.png → verify_report（块级 diff 对录制）
        ──> tools/demo_knowledge_window.py（快照 diff 分段 + 输入对齐 → data/knowledge/demos/）
```

关键文件：
- `src/emulator/gamepad.py`：旁路手柄轮询；映射解析自 `%APPDATA%/mGBA/config.ini` `[gba.input.SDLB]`（用户配置，**只读不写**）；未映射输入报原始标签（BTN<i>/AX<i>±/HAT<x,y>）
- `src/emulator/window_backend.py`：`send_vk`（PostMessage 直发 WM_KEY*，lParam 需扫描码+扩展位 bit24+transition 位）、`capture_hwnd`（PrintWindow 优先，全黑回退 BitBlt，NEAREST 缩放到 240x160，异常自愈返回 None）、`find_window`
- `src/perception/screen.py`：`diff_ratio = mean(a != b)`（逐像素不等占比，**无归一化**——mean 差大的图 diff 不可能小，可用于交叉验证）
- `src/perception/llm_vision.py`：qwen2.5vl:7b（Ollama），GPU 故障自动 fallback CPU；**7B 对 240x160 GBA 小像素场景识别不可靠**（场景类型乱标），只可用于「同/不同」粗判
- `src/control/visual_controller.py` / `player_tracker.py`：纯画面移动判定（变化率阈值）/ 主角精灵 SAD 模板匹配（无内存依赖，第二代控制层）

### 窗口输入三层事实（2026-08-08 多次实证，反了会全灭）

1. **SDL gamepad（用户录制）**：绕过 Qt 键盘系统，始终有效——但用户手柄被占用，回放不可用
2. **Lua 直注入（键盘屏段）**：mGBA「脚本」窗口（Tools→脚本...，物理鼠标点击第 4 项）里 `emu:addKey(N)/clearKey(N)` 注入 core，绕过 Qt 键盘系统。**键盘屏（命名界面）期间 PostMessage 完全无效**（Qt 焦点偏离），必须 Lua。每命令经 Interrupter 冻结核心 ~250ms——键密度高会积压落后。Lua 键位：A=0 B=1 SELECT=2 START=3 RIGHT=4 LEFT=5 UP=6 DOWN=7
3. **PostMessage（对话/走路段）**：对话屏有效（前提窗口聚焦）；发送成功≠生效（Qt 焦点/队列）。扩展键（方向 0x25-0x28）lParam 必须带 `0x01000000`。**帧相位抖动 ±16ms**（60fps 游戏帧量化）+ Qt 队列延迟 → 走路键送达时刻波动 → **人物位置差累积**

焦点机制：窗口失焦（弹窗/脚本窗口关闭后）Qt 焦点停在「偏离对象」，`SetForegroundWindow` 对已前台窗口是 no-op——需延时 + `_force_foreground`（WM_ACTIVATE）触发 Qt 焦点归还，且**长空闲期沉淀**后 PostMessage 才长期稳定（62s 刚关窗只稳定 2-3 键，90s 处恢复长期稳定）。

### 回放自愈体系（replay_demo_window.py，fix 系列）

主循环按 `eff_t = k["t"] + t_base` 发键；关键时刻用**画面驱动自愈块**兜底（PostMessage 时序抖动不可预测，全靠它们把状态拉回录制线）：
- 键盘屏段 `_kb_phase`：Lua burst 注入推进（45-66s）
- **RIGHT 唤醒重试**（84.5-95.5s）：睡眠场景（mean<60 或 66-70）→ 长按 1.2s（短按 0.15s 实测无效——「再睡」对话框陷阱）
- **A×8 补推进**（95.5-99s）：对话未转场 → 补 A×2
- **第二对话自愈**（104.5-132s）：行级判定 `top[6:58]∈[75,110] 且 dlg[110:140]>90` = 对话中 → 补 A×2
- **走路段门控**（fix14e/f）：第二对话稳定消失（连续 3 次判定不成立 ≈3.6s）→ `walk_offset = game_ms - WALK_KEY_ABS`，走路键 `eff_t = t + walk_offset` 开闸；开闸后禁用补 A（人物走动在 y110-140 的高亮会误判为对话框）
- **safe_send**（fix15）：send_vk 包 try/except——1400 无效句柄时查 `proc.poll()`、FindWindow 重找、重试一次、失败抛 `ReplayWindowLost` 优雅中止；主循环每轮检查进程存活

## 关键不变量（用户规则，必须遵守）

- 主角性别选「女」、主角名字为「A」、主角的所有宝可梦不命名
- mGBA 手柄映射由用户内部配置——录制器/回放器**不得改写** `%APPDATA%/mGBA/config.ini`
- 录制必须是**旁路进程**（不注入、不抢焦点、不干扰用户操作）
- 回放验证用块级 8x8 diff（跳过顶部白条行）抗 NEAREST 缩放伪影；同刻 diff（±0.5s 内匹配）区分真实对齐 vs 全谱最优匹配假象；行级剖面定位白条位置

## 已知 hack 问题（386 修复版特有，踩坑记录）

1. **savestate 陷阱**：过场/对话动画中保存的 savestate 恢复后状态不稳定（位置漂移、移动锁）。**冷启动单进程是确定性方案**；回放验证必须 `--clean-sav` 从冷启动起
2. **转场目标由人物站位决定**（2026-08-08 走路段分叉根因）：人物在门口位置差几步 → 地图转场去往**不同房间**（实测：回放转场到了录制 154s 的对话房间而非录制 115s 的走路场景）。走路段位置差累积跨过触发阈值 = 概率性分叉（0-135s 验证 ✅ 不可复现，是运气）
3. **转场动画帧全相似**：所有转场（黑白闪）动画帧 mean 8-58 且互相 diff 极小——全谱匹配时转场帧可能匹配到录制任意时刻的转场，判分叉必须结合前后帧序列
4. **睡眠「再睡」对话框**：睡眠场景 A 键弹「再睡」对话框（mean 66-70）永远无法唤醒，必须 RIGHT 长按
5. 旧 README 记录的其他坑（1F 门洞 bug、未白镇移动锁、坐标污染、Ollama GPU 不稳定）仍是有效背景，但属于第一代无头架构时代

## 数据布局

- `data/demos/demo_*.jsonl`：录制轨迹（按键/快照/存档事件）；`data/demos/img/` 录制快照；`data/demos/replay/<stem>/` 回放快照 + report.txt
- `data/knowledge/demos/*.md`：轨迹提取的知识；`data/knowledge/walkthrough.json`：pmcenter.cn 攻略结构化（38 步）
- 验证报告判定：对齐帧（最优 diff <0.25）占比、发散帧（>0.55）<10%、中位 diff <0.20 → ✅；匹配窗口 ±5s

## 代码约定

- 文件头部注释承载**实测结论**（如 window_backend.send_vk 的 HIPS 拦截说明、replay 的 fix 系列演进）——改代码前先读注释，注释里的实证结论比 README 新
- 自愈块用画面行级/均值判定（top 行、dlg 行、mean 阈值），阈值都带实测出处注释
- 时间单位：录制/回放 JSONL 用 ms（abs）；回放帧名含 t_base 偏移（297）；诊断脚本参数注意区分 abs/相对
