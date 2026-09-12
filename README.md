# AgentPoker AI Arena

面向 Agent Poker 赛事的无限注德州扑克（NLHE）锦标赛 Agent，基于进化策略训练，支持真实对手画像剥削。

## 赛制与规模

- **参赛规模**：**约 120 人**（20 个 6-Max 桌同步开打，筹码破产自动补满 100 BB）
- **预赛**：10 轮 × 20 手 = 200 手，R1~R3 随机分桌，R4~R10 瑞士积分动态分桌（强强对决）
- **晋级机制**：按 200 手总净收益（BB/100）决出 **Top 12（出线率 10.0%）**
- **半决赛**：Top 12 蛇形分为 A/B 两桌（各 20 手，每桌前三晋级，共 6 人进决赛）
- **总决赛**：单桌 6 人决战（30 手），净收益第 1 名斩获**全场总冠军**（基准夺冠率 0.83%）
- **完整赛制与博弈论手册**：详见 [docs/TOURNAMENT_SPEC.md](docs/TOURNAMENT_SPEC.md)

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

# 通用训练 + 混入优质真实画像（推荐：既有原型覆盖，又见到真实对手）
MIX_PROFILES=1 PROFILE_MIN_HANDS=300 PROFILE_SHARE=0.5 \
SAVE=models/champion.json ./run_train.sh --no-resume

# 针对真实对手画像的定向训练（默认自动以 models/champion.json 为底模微调，也可显式指定 --base-model）
SAVE=models/champion_targeted.json uv run python -m agentpoker.cli train \
  --track targeted --profiles models/opponent_profiles.json --base-model models/champion.json

# 从已有存档续训（默认行为）
./run_train.sh
```

### 混练开关

默认的 Universal 训练只用 6 个合成原型。加 `--mix-profiles` 可以在保留原型的同时混入真实对手画像：

| 参数 | 默认 | 说明 |
| :--- | :---: | :--- |
| `--mix-profiles` | 关 | 通用训练中混入真实画像 |
| `--profile-min-hands` | 100 | 画像质量门槛，低于此手数不采用（剔除噪声大的画像） |
| `--profile-share` | 0.5 | 画像在对手池中占的座位比例上限，其余留给原型+种群+名人堂 |

为什么限制 `profile_share`：真实画像的风格分布偏斜（TAG/LAG/Maniac 占 50/60），纯画像训练会欠训练紧弱/被动风格；原型负责补上这些缺失的极端风格。

训练过程实时输出每个候选的 fitness，每代结束输出汇总。

### 训练参数速查

`./run_train.sh` 用环境变量控制（写法 `VAR=值 ./run_train.sh`），底层是 `agentpoker train`。额外的命令行参数会原样透传，例如 `./run_train.sh --no-resume --archive models/my_archive`。

| 环境变量 | CLI 参数 | 默认 | 说明 |
| :--- | :--- | :---: | :--- |
| `GENERATIONS` | `--generations` | 30 | 训练代数。每代耗时取决于 `RUNS_PER_CANDIDATE` 和 `AGENTS` |
| `POPULATION` | `--population` | 16 | 每代候选策略数，越大探索越广、每代越慢 |
| `RUNS_PER_CANDIDATE` | `--runs` | 120 | **每个候选评估的场数，噪声的主要来源**。30 场时标准误 ±0.07，120 场约 ±0.035 |
| `REEVAL_RUNS` | `--reeval-runs` | 60 | 每代初选后用全新对手池复评的场数，消除「冠军只是抽样运气」 |
| `FINAL_RACE` | `--final-race` | 500 | 最终留出集验证场数，决定报告数字的可信度 |
| `AGENTS` | `--agents` | 36 | 每场锦标赛参赛人数，建议对齐真实赛场规模 |
| `WORKERS` | `--workers` | CPU 核数 | 并发进程数 |
| `SAVE` | `--save` | models/champion.json | 冠军模型输出路径 |
| — | `--archive` | models/archive_universal | 各代存档目录，用于断点续训 |
| — | `--no-resume` | 关 | 忽略已有存档、从第 1 代重训（默认会自动续训） |
| — | `--track` | 自动 | `universal`=原型池泛化 / `targeted`=真实画像特训 |
| — | `--equity-samples` | 0 | 0=离线查表（快）；>0=实时蒙特卡洛采样（准但慢很多） |
| — | `--holdout-frac` | 0.25 | 留出集比例，这部分画像不参与训练、只用于最终验证 |
| `MIX_PROFILES` | `--mix-profiles` | 关 | 通用训练中混入优质真实画像 |
| `PROFILE_MIN_HANDS` | `--profile-min-hands` | 100 | 画像质量门槛，低于此手数不采用 |
| `PROFILE_SHARE` | `--profile-share` | 0.5 | 画像在对手池中占比上限，其余留给原型 |
| `PROFILES` | `--profiles` | models/opponent_profiles.json | 画像文件路径 |
| `BASE_MODEL` | `--base-model` | 自动识别 | 初始底模路径（如 `models/champion.json`）。无存档时以此模型为起点微调，避免从零冷启动 |

耗时参考（8 核，16 候选/代）：36 人 × 120 场约 9 分钟/代；96 人 × 120 场约 15 分钟/代。单场锦标赛实测 36 人 2.2 秒、96 人 3.7 秒。

### 评估参数

| 参数 | 默认 | 说明 |
| :--- | :---: | :--- |
| `--strategy` | models/champion.json | 要评估的模型文件 |
| `--runs` | 500 | 评估场数，500 场时标准误约 ±0.016 |
| `--agents` | 36 | 对手池人数 |
| `--profiles` | 无 | 指定后对手来自真实画像而非原型 |
| `--workers` | 自动 | 并发进程数 |

### 实战参数

| 参数 | 默认 | 说明 |
| :--- | :---: | :--- |
| `--strategy` | models/champion.json | 使用的模型文件 |
| `--max-hands` | 0 | 打满多少手后停止（0=不限）。想跑一个完整 200 手周期就设 `200` |
| `--max-steps` | 0 | 最多循环多少步后退出（0=不限） |
| `--round-hands` | 20 | 每轮手数，用于轮次结算提示 |
| `--cycle-hands` | 200 | 每周期手数，用于赛季结算与锦标赛压力信号 |
| `--no-auto-profile` | 关 | 关闭画像热更新（默认每 20 手自动更新一次对手画像） |
| `--competition-id` / `--key` / `--app` | 读 `.env` | 赛事 ID / API 密钥 / 服务器地址 |

### 画像参数

| 参数 | 默认 | 说明 |
| :--- | :---: | :--- |
| `--pull` | 关 | 直接从赛事 API 拉取最新战绩（不加则读本地文件） |
| `--input` | data/processed/hands.jsonl | 本地手牌输入文件 |
| `--out` | models/opponent_profiles.json | 画像输出路径（会覆盖同路径旧文件） |
| `--min-hands` | 30 | 不足此手数的选手不写入画像 |
| `--prior-weight` | 8.0 | 贝叶斯先验权重，越大则小样本选手越向「均衡型」收缩 |
| `--no-filter-afk` | 关 | 关闭挂机/僵尸号过滤 |
| `--max-hands` | 不限 | 最多拉取多少手牌 |

> 所有命令都支持 `--help` 查看参数说明，例如 `uv run python -m agentpoker.cli train --help`

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
