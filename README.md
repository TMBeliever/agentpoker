# AgentPoker AI Arena (V2 Architecture)

面向 120 人无限注德州扑克（6-Max NLHE）官方正规锦标赛的工业级竞技 AI 系统，基于多阶段博弈论、进化策略自博弈与真实对手画像剥削驱动。

---

## 赛制规格与博弈论架构 (Official 120-Player Tournament Specification)

- **参赛规模**：**标准 120 人**（20 个 6-Max 桌同步开打，筹码破产自动补满 100 BB，并在账本扣除 100 BB 罚分）
- **筹码深度**：起始筹码 100 BB（$20,000，小盲 100，大盲 200）。
- **预赛阶段 (Preliminary)**：10 轮 × 20 手 = 200 手。
  - **连续筹码跨轮继承**：筹码严格跨轮累积，严禁中途重置（杜绝无损刷筹码漏洞）。
  - **动态瑞士轮分桌 (Swiss Pairing)**：R1~R3 随机分桌，R4~R10 严格按累计 BB/100 积分与净收益多级决胜分桌（强强对话与同级收割）。
  - **有效完赛率门槛**：全场选手须完成 $\ge 80\%$（160手）方可计入出线评定。
  - **出线晋级率**：按 200 手总净收益决出 **Top 12 晋级（出线率 10.0%）**。
- **半决赛阶段 (Semifinal)**：Top 12 蛇形交叉分为 A/B 两桌（各 20 手，筹码重置为 100 BB，每桌前 3 名晋级，共 6 人进决赛）。
- **总决赛阶段 (Final Table)**：单桌 6 人总决战（30 手，筹码重置为 100 BB，最高净收益者荣获**全场总冠军**，基准夺冠率 0.833%）。
- **验收与工程报告**：详见 [docs/ACCEPTANCE_REPORT.md](docs/ACCEPTANCE_REPORT.md)。

---

## 快速开始

```bash
# 1. 安装依赖环境 (uv)
uv sync

# 2. 授权连接比赛服务器 (自动保存 API Key 到 .env，权限 0600)
uv run python -m agentpoker.cli connect

# 3. 启动实战 Agent (加载已认证 Production Champion 模型)
uv run python -m agentpoker.cli live --strategy models/champion.json
```

---

## 核心架构模块 (Architecture Highlights)

1. **筹码守恒与账本连续性 (`agentpoker/engine.py`)**：
   - 保证 $\sum \text{Stack}_i + \text{Pot} = \text{Const}$，连续筹码继承贯穿预赛 200 手，破产自动买入严格记入独立账本。
2. **多阶段自适应决策架构 (`agentpoker/strategy.py`)**：
   - **预赛阶段 (Preliminary)**：鱼群收割策略（面对被动跟注站加注尺度放宽至 $1.30\times \sim 1.35\times$，坚决杜绝纯空气诈唬，价值下注拉满）。
   - **半决赛阶段 (Semifinal)**：ICM 气泡期风险折溢价（第 3 名稳健防守 $+0.07$ 门槛溢价，第 4~6 名大幅放宽推入偷盲范围）。
   - **决赛阶段 (Final Table)**：冠军赢家通吃策略（落后选手逐步放宽全押与 3-bet 频率，争夺第 1 名）。
   - **坚决杜绝开放式跛入 (No Open Limping)**：激进型选手 preflop 坚持 Raise or Fold 原则。
3. **金字塔生态对手池 (`agentpoker/ecosystem.py`)**：
   - **30% 鲨鱼 (Sharks)**：稳健激进 (TAG) 与松凶压迫 (LAG)。
   - **40% 常客 (Regulars)**：平衡默认型 (Balanced)。
   - **30% 鱼群 (Fish)**：被动跟注站 (Calling Station)、狂热玩家 (Maniac) 与极端保守坚果型 (Nit)。
4. **离线胜率查表与快速标定 (`agentpoker/cards.py`, `agentpoker/calibration.py`)**：
   - 基于 `_RANK_CHAR` 快速索引表，手牌分类查表速率突破 **200,000 次/秒**；连续双线性插值保障胜率单调性。
5. **网络断线重试与稳态守护 (`agentpoker/protocol.py`, `agentpoker/live.py`)**：
   - HTTP 502/503/504 指数退避抖动重试，3000ms 超时前自动兜底合法动作 (`_fallback_action`)，零闪退保障。
6. **冠军认证门禁 (`agentpoker/battle.py`)**：
   - 自动化 5 维客观门禁判定（榜首排名、深进率优势、正期望 BB/100、Top 12 出线率、相对历史标杆的博弈优势），带时间戳安全晋升与自动备份。

---

## 命令行全功能手册 (CLI Reference)

### 1. 锦标赛擂台对战与冠军认证 (`battle` / `arena`)
```bash
# 启动 50 场 120 人金字塔生态擂台赛，并对候选模型执行自动化认证
uv run python -m agentpoker.cli battle \
  --models models/champion.json models/archive/gen_028.json \
  --archetypes tight lag \
  --opponents pyramid \
  --runs 50 \
  --agents 120 \
  --certify \
  --candidate "models/champion.json" \
  --save-report "data/arena_latest.json"
```

### 2. 实战挂机比赛 (`live`)
```bash
# 运行实战 Agent，支持热更新对手画像，200手周期提示
uv run python -m agentpoker.cli live \
  --strategy models/champion.json \
  --profiles models/opponent_profiles.json \
  --equity-samples 200 \
  --cycle-hands 200
```

### 3. 自演化训练 (`train`)
```bash
# 启动金字塔生态自博弈演化训练（严格执行德扑参数几何与单调性约束）
uv run python -m agentpoker.cli train \
  --generations 10 \
  --population 16 \
  --runs 60 \
  --agents 120 \
  --base-model models/champion.json \
  --archive models/archive_v2 \
  --save models/champion_next.json
```

### 4. 对手画像拉取与清洗 (`profile`)
```bash
# 从线上比赛 API 拉取最新战绩并构建贝叶斯平滑画像
uv run python -m agentpoker.cli profile --pull --min-hands 30
```

### 5. 可视化 Web 控制台 (`dashboard`)
```bash
# 启动本地可视化仪表盘（查看选手画像、对局复盘与擂台战报）
uv run python -m agentpoker.cli dashboard --port 8080
```

---

## 自动化测试与质量门禁

本项目遵循严格的自动化测试纪律（12 个阶段全部通过）：

```bash
# 运行全量 121 项自动化单元与集成测试
uv run python -m pytest
```

```
======================== 121 passed in 98.87s (0:01:38) ========================
```

- `tests/test_stage1_accounting.py`: 筹码守恒、多池拆分与连续跨轮继承 (11 tests)
- `tests/test_stage2_config.py`: 120 人正赛配置与不可变数据契约 (8 tests)
- `tests/test_stage3_context.py`: 锦标赛阶段感知上下文向量与压力映射 (6 tests)
- `tests/test_stage4_ecosystem.py`: 金字塔生态 30/40/30 整数分割 (5 tests)
- `tests/test_stage5_swiss.py`: 瑞士轮多级决胜分桌与半决赛蛇形分组 (5 tests)
- `tests/test_stage6_strategy.py`: 多阶段策略自适应、被动鱼群收割与气泡期博弈 (5 tests)
- `tests/test_stage7_calibration.py`: 离线胜率标定表高速查找与平滑插值 (6 tests)
- `tests/test_stage8_live.py`: 网络指数退避重试与异常兜底动作守护 (5 tests)
- `tests/test_stage9_evolution.py`: 锦标赛适应度评估与单调性参数约束 (4 tests)
- `tests/test_stage10_battle.py`: 两两对决胜率互惠矩阵与冠军认证门禁 (5 tests)
- `tests/test_stage11_champion.py`: Generation 28 缺陷审计与新一代冠军验证 (5 tests)
- `tests/test_v2_architecture.py` & others: 历史回归测试与端到端系统验证 (56 tests)

---

## 目录结构

```
agentpoker/
  ├── config.py         # 120人比赛不可变规则配置 (TournamentConfig)
  ├── context.py        # 阶段感知上下文向量 (TournamentContext)
  ├── ecosystem.py      # 金字塔生态发生器 (30% Sharks, 40% Regulars, 30% Fish)
  ├── pairing.py        # 瑞士轮动态积分编排与蛇形分桌 (SwissPairer)
  ├── strategy.py       # 多阶段自适应决策引擎 (StrategyAgent, StrategyParams)
  ├── engine.py         # NLHE 牌局模拟引擎 (筹码守恒、账本连续性、多池计算)
  ├── cards.py          # 牌型评估与高速手牌分类查表
  ├── calibration.py    # 离线蒙特卡洛标定表与胜率连续插值
  ├── battle.py         # 锦标赛多模型擂台对决与冠军认证门禁
  ├── training.py       # 进化演化引擎与名人堂机制
  ├── live.py           # 实战通信与异常兜底控制器
  ├── protocol.py       # 网络请求、指数退避重试与环境发现
  ├── profiler.py       # 真实玩家画像清洗与贝叶斯先验统计
  └── dashboard.py      # Web 可视化复盘服务器

models/
  ├── champion.json             # 当前已认证出战冠军模型 (Production Champion V2)
  ├── opponent_profiles.json    # 线上选手贝叶斯画像库
  └── archive/                  # 历史归档模型 (包含 gen_028.json 历史标杆)

docs/
  ├── baseline_report.md        # Stage 0: 基线审计与问题清单
  ├── stage1_report.md ~ stage11_report.md # Stages 1-11 门禁证据报告
  └── ACCEPTANCE_REPORT.md      # Stage 12: 最终综合验收报告
```

---

## 许可证

MIT License
