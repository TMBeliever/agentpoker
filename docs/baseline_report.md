# AgentPoker Stage 0: 仓库基线与审计报告 (Baseline Report)

## 一、项目架构与主要执行路径 (Execution Paths)

### 1. 核心模块与入口
- **CLI 入口 (`agentpoker/cli.py`)**:
  - `train`: 启动演化训练 (`StrategyTrainer.fit`)
  - `evaluate`: 对单个候选模型进行竞技场评测 (`ArenaEvaluator.evaluate`)
  - `battle`: 启动多人竞技对战联赛 (`ArenaBattleRunner.run_battle`)
  - `live`: 连接官方实战赛事 WebSocket (`LiveGameController`)
  - `export`: 导出对手画像库 (`OpponentProfiler.export`)
- **Web 仪表盘 (`agentpoker/dashboard.py`)**:
  - 提供 HTTP 界面，支持实时训练监控、画像库筛选预设（如金字塔生态 36 人）、竞技场评测。
- **实战赛事控制器 (`agentpoker/live.py`)**:
  - 接入 `agentpoker.cn` 正式赛场，处理房间订阅、动作请求、对手画像动态加载与增量累积。

### 2. 赛事模拟与核心引擎
- **底牌与对局引擎 (`agentpoker/engine.py` - `NLHEngine`)**:
  - 6 人桌德州扑克离散事件模拟器，处理强制盲注、轮转、翻牌前/翻牌/转牌/河牌下注轮、未跟注溢出筹码返还 (`_settle` 中的 uncalled excess) 及分层边池计算。
- **锦标赛模拟器 (`agentpoker/tournament.py` - `LeagueSimulator`)**:
  - 编排完整赛事赛程：预赛 10 轮 × 20 手、R1-R3 随机配对、R4-R10 瑞士轮配对、前 12 强晋级、半决赛蛇形分组、决赛 6 人桌争夺冠军。
- **配对与排位 (`agentpoker/pairing.py`, `agentpoker/scoring.py`)**:
  - `random_groups`, `swiss_groups`, `rank_standings`, `Standing`。

### 3. AI 策略与训练体系
- **智能体决策 (`agentpoker/strategy.py` - `StrategyAgent`, `StrategyParams`)**:
  - 翻前位置感知开池、大盲防守、短码推折 (Push/Fold)、翻后持续下注、转牌开火、河牌阻断牌极化诈唬、多人底池安全衰减、贝尔曼晋级效用压力调节。
- **演化训练系统 (`agentpoker/training.py` - `StrategyTrainer`)**:
  - 种群遗传算法（高信噪比目标函数、严格绝对精英常驻、交叉、高斯变异、战术耦合约束裁剪、留出集验证、终局淘汰赛及精英参数平滑）。
- **对手画像挖掘 (`agentpoker/profiler.py` - `OpponentProfiler`)**:
  - 解析历史对局日志，提取翻前与翻后统计数据，执行贝叶斯平滑并分类玩家风格画像。

---

## 二、当前测试集执行基线 (Baseline Test Results)

- **测试框架**: pytest 9.1.1 (Python 3.11.16)
- **测试结果**:
  - Total Tests: 56
  - Passed: 56 (100%)
  - Failed: 0
  - Skipped: 0
  - 执行耗时: 9.05s
- **覆盖测试套件清单**:
  - `tests/test_battle.py` (4 passed)
  - `tests/test_calibration.py` (10 passed)
  - `tests/test_engine.py` (6 passed)
  - `tests/test_live_body.py` (1 passed)
  - `tests/test_live_controller.py` (2 passed)
  - `tests/test_optimization.py` (10 passed)
  - `tests/test_protocol.py` (1 passed)
  - `tests/test_resumable_training.py` (4 passed)
  - `tests/test_strategy_params_live.py` (4 passed)
  - `tests/test_tournament.py` (1 passed)
  - `tests/test_training_statistics.py` (7 passed)
  - `tests/test_v2_architecture.py` (6 passed)

---

## 三、赛事全仓硬编码值清单 (Hard-coded Values Inventory)

| 数值 / 变量名 | 出现位置 | 当前语义与用途 | 存在的问题与冲突 |
| :--- | :--- | :--- | :--- |
| `36` / `pool_size` | `agentpoker/training.py:249, 333` | `ArenaEvaluator` 与 `StrategyTrainer` 默认种群池大小 | 偏离 120 人赛制，导致训练评估的场上生态与正式赛场严重脱节 |
| `36` / `field_size` | `agentpoker/battle.py:357, 780` | `ArenaBattleRunner` 默认参赛人数，交互提示“标准正赛为 36 人” | 与 120 人正式赛制不一致 |
| `36` / `agents` | `agentpoker/cli.py:97, 106, 125, 163, 361` | CLI 命令默认人数全部硬编码为 36 | 命令行参数未对齐 120 人标准 |
| `36` / `inpAgents` | `agentpoker/dashboard.py:55, 672` | 仪表盘界面默认参赛人数为 36 | UI 端硬编码 |
| `120` / `FIELD_SIZE` | `agentpoker/context.py:32` | 锦标赛场上总人数常数 (120 人) | 正确，但仅存在于 context 模块，未统领全局 |
| `10` / `rounds` | `agentpoker/tournament.py:17` | 预赛默认总轮数 (10 轮) | 需与单轮 20 手组合为 200 手 |
| `20` / `hpr` | `agentpoker/tournament.py:17` | 预赛每轮手牌数 (20 手) | 与赛制一致 |
| `20` (半决赛) | `agentpoker/tournament.py:99` | 半决赛手牌数 (20 手) | 硬编码在循环中 `for h in range(20):` |
| `30` (决赛) | `agentpoker/tournament.py:122` | 决赛手牌数 (30 手) | 硬编码在循环中 `for h in range(30):` |
| `100` / `sb` | `agentpoker/tournament.py:17` | 小盲 100 筹码 | 符合初始 100BB 设定 (BB=200) |
| `100` (筹码重置) | `agentpoker/tournament.py:47` | **预赛换桌强制重置筹码** `st[aid]['stack'] = 100 * self.big_blind` | **【严重缺陷】** 预赛每轮换桌违规重置筹码为 100BB，破坏了筹码连续累积 |
| `100` (破产重买) | `agentpoker/tournament.py:59, 70` | 破产后自动补满 100BB | **【严重缺陷】** 重买未扣除选手 tournament_net 记账，存在筹码印钞漏洞 |

---

## 四、关键系统漏洞与缺陷定位 (Critical Flaws Identified)

### 1. 筹码与重买账本错误 (P0)
- **预赛换桌违规重置**: `LeagueSimulator._play_group` 在每一轮开始时强制执行 `st[aid]['stack'] = 100 * self.big_blind`。在 200 手连续赛事中，上一轮赢到 300 BB 的选手筹码凭空蒸发，上一轮打残到 10 BB 的选手获得免费补筹码。
- **重买未记入成本**: 选手破产后补筹码 100 BB，其 `net_bb` 仅计算每手 `(final - before) / bb`，破产补入的 100 BB 未体现在扣除项中。严格的账本必须满足：
  $$\text{tournament\_net\_bb} = \frac{\text{current\_stack} - \text{initial\_stack} - \text{rebuy\_cost}}{\text{BB}}$$

### 2. 赛事规则配置碎片化 (P0)
- 缺乏单一真理源 `TournamentConfig`。
- `field_size` 在 `training.py` 默认为 36，在 `battle.py` 默认为 36，在 `cli.py` 默认为 36，而在 `context.py` 却定义为 120。必须建立唯一的 `TournamentConfig` 全局统摄。

### 3. 对手画像分母谬误 (P0)
- `OpponentProfiler.export` 与 `StrategyAgent.OpponentStats` 计算动作频率时，使用 `events / hands`（如 `raises / hands`, `calls / hands`, `folds / hands`），导致分母严重失真。必须重构为基于机会数 (opportunity-based) 的精确统计：`count / opportunity`。

### 4. 瑞士轮同分 Tiebreak 丢失 (P1)
- `agentpoker/pairing.py:swiss_groups` 仅依据 `scores.get(x)` 和选手 ID 排序分桌，丢弃了正式规则规定的“R4-R10 累计净胜 BB”同分判定准则。

### 5. 局部分析猜测全局排位 (P1)
- `agentpoker/context.py:synthetic_context` 依据单一选手的自身 BB/100 猜测全局排位，但未在上下文结构中置位 `synthetic = True`，导致策略层无法区分“真实官方排位”与“局部猜测排位”。

---

## 五、Gate 0 准出判定 (Gate 0 Evaluation)

- [x] **G0.1 能运行 baseline tests**: 已执行 pytest 全量回归。
- [x] **G0.2 能列出所有测试结果**: 56 个测试全部列出，56 passed。
- [x] **G0.3 能列出所有赛事相关 hard-coded values**: 已完成 36/24/120/10/20/30/100/200 全量搜索与归类。
- [x] **G0.4 能确定所有主要 execution paths**: CLI、Dashboard、Live、Tournament、Engine、Training 路径全部摸清。
- [x] **G0.5 不允许隐藏现有失败测试**: 无任何失败测试被跳过或隐藏。

**Gate 0 判定结果: PASS**
准许进入 **Stage 1: Poker Engine 与赛事账本正确性**。
