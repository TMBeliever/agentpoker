# AgentPoker AI Arena

面向 Agent Poker 赛事的无限注德州扑克（NLHE）锦标赛 Agent，基于进化策略训练，支持真实对手画像剥削。

## 赛制

- **预赛**：10 轮 × 20 手 = 200 手，R1~R3 随机分桌，R4~R10 瑞士积分动态分桌
- **晋级**：Top 12 → A/B 双桌半决赛（各 20 手，前三晋级）→ 总决赛（30 手）
- **排名指标**：净收益 / BB/100

## 快速开始

```bash
# 安装依赖
uv sync

# 连接账号（写入 .env）
uv run python -m agentpoker.cli connect

# 开始对战
uv run python -m agentpoker.cli live --strategy models/champion.json
```

## 训练

```bash
# 快速版（约 40 分钟，6 代）
GENERATIONS=6 RUNS_PER_CANDIDATE=60 REEVAL_RUNS=20 FINAL_RACE=100 \
SAVE=models/champion_new.json \
./run_train.sh --no-resume

# 正式版（约 5-6 小时，30 代）
SAVE=models/champion_new.json ./run_train.sh --no-resume

# 针对真实对手画像的定向训练
SAVE=models/champion_targeted.json uv run python -m agentpoker.cli train \
  --track targeted --profiles models/opponent_profiles.json

# 从已有存档续训（默认行为）
./run_train.sh
```

训练过程实时输出每个候选的 fitness，每代结束输出汇总。

## 评估

```bash
# 在真实对手画像上评估冠军模型
uv run python -m agentpoker.cli evaluate \
  --strategy models/champion.json \
  --profiles models/opponent_profiles.json \
  --runs 500
```

## 对手画像

```bash
# 从本地手牌记录构建画像
uv run python -m agentpoker.cli profile --input data/processed/hands.jsonl

# 直接从 API 拉取手牌并构建
uv run python -m agentpoker.cli profile --pull
```

## 目录结构

```
agentpoker/
  strategy.py      # 决策核心，StrategyParams 参数化策略
  training.py      # 进化训练：StrategyTrainer + ArenaEvaluator
  tournament.py    # 锦标赛模拟器
  engine.py        # NLHE 引擎（筹码守恒，zero-sum）
  cards.py         # 牌力评估，rank7 快速 7 张牌判定
  calibration.py   # 胜率标定表（强度分数 → 真实胜率）
  profiler.py      # 真实对手画像构建
  live.py          # 实战驱动
  context.py       # 锦标赛压力信号（训练与实战统一路径）

models/
  champion.json             # 冠军模型（训练后生成）
  archive/                  # 各代存档，支持续训
  opponent_profiles.json    # 59 位真实选手画像
```

## 核心参数（StrategyParams）

| 参数 | 说明 |
| :--- | :--- |
| `vpip` | 入池率，控制起手牌范围 |
| `open_frequency` | 开局加注频率 |
| `threebet_frequency` | 3-bet 频率 |
| `cbet_frequency` | 持续下注频率 |
| `value_threshold` | 价值下注胜率门槛 |
| `safety` / `attack` | 锦标赛保守/激进平衡 |
| `bubble_aggression` | 气泡期激进度 |
| `temperature` | 决策随机性 |

## 训练方法

进化策略（ES）：每代对 `population` 个候选进行锦标赛评估，取 top-k elite 做交叉变异，生成下一代种群。评估使用 **Common Random Numbers**（所有候选共享同一对手池和随机种子），消除候选间抽签运气。每代结束后对 top-k 进行留出集重评，取平均参数候选与最佳原始 elite 中表现更好的作为该代冠军。

## 测试

```bash
uv run python -m pytest tests -q
```
