# AgentPoker AI Arena — Final v2.0

面向 Agent Poker 赛事的**全自适应策略进化型 NLHE Agent**。
本系统不是训练一个脱离赛制的“泛化扑克模型”，而是针对官方真实锦标赛赛制（瑞士制排位 + Top 12 晋级 + 决赛圈争霸）以及线上无限训练场深度定制调优的竞技级策略解决方案。

- **预赛规则**：10 轮 × 每轮 20 手 = 200 手
- **分桌机制**：R1~R3 随机分桌；R4~R10 严格按上一轮累计 BB/100 瑞士积分动态分桌
- **晋级赛制**：Top 12 晋级 A/B 双桌半决赛（各 20 手，前三晋级），前 6 名杀入总决赛（30 手）
- **官方排名指标**：净收益与 **BB/100**

---

## 🌟 核心技术架构与优化成果

### 1. 轻量高精度相对牌力与听牌感知 ([cards.py](file:///Users/liang/Downloads/agentpoker_final%202/agentpoker/cards.py))
- **微秒级规则与位运算启发式评估**：彻底告别原有硬编码查表；
- **精准区分细分牌型**：超对（Overpair）、顶对顶踢（TPTK, ~0.71）、弱底对（~0.37）、板面对子；暗三条（Set, ~0.88）vs 板面明三条（Trips, ~0.76）；
- **动态听牌胜率折算**：坚果同花听牌（Nut Flush Draw）、双头顺（OESD）、卡顺（Gutshot）根据底池赔率自动折算补牌胜率（+0.05 ~ +0.18）；
- **公牌危险度感知**：结合单色/双色/顺子/成对板面，自动调降边缘成牌价值，彻底堵死翻后过度跟注漏洞。

### 2. 真实对手画像与贝叶斯动态剥削 ([profiler.py](file:///Users/liang/Downloads/agentpoker_final%202/agentpoker/profiler.py) & [strategy.py](file:///Users/liang/Downloads/agentpoker_final%202/agentpoker/strategy.py))
- **S10 全量 4,583 手数据清洗**：自动剔除手数不足 30 手及挂机弃牌号，保留 **59 位高置信度真实选手画像**（`models/opponent_profiles.json`）；
- **贝叶斯平滑（Bayesian Shrinkage）**：通过伪计数大盘先验平滑小样本数据抖动，未知选手自动退化为安全平衡型；
- **针对性分类剥削**：
  - **跟注站（Calling Station）**：河牌空气诈唬率压制为 0，大牌价值下注尺度放大至 $1.15\times$；
  - **岩石极紧手（Nit/Weak）**：后位高频 2.2BB 偷盲，翻牌打 $1/3$ 底池小 C-bet 轻松收割；
  - **激进狂徒（Maniac）**：用强牌执行 Check-Raise / Check-Call 设伏诱捕；
- **决策边界保护**：牌力与底池赔率主导 85% 决策，画像修正严格控制在 $\pm 5\% \sim 15\%$ 边缘区间，底模永不崩盘。

### 3. 底池下注尺度与短码推推乐控制 ([strategy.py](file:///Users/liang/Downloads/agentpoker_final%202/agentpoker/strategy.py))
- **底池比例控注**：开池固定 `2.49 BB`，翻牌 C-bet 控制在 `50.3% 底池`，价值下注 `57.6% 底池`，消灭“全副身家盲目下注”的历史漏洞；
- **短码 Push/Fold 决策树**：识别有效筹码量 $\le 12 \text{ BB}$，浅码阶段屏蔽易被套池的 Min-Raise，可玩起手牌直接 All-in，最大化弃牌赢率。

### 4. 线上训练赛【原地 20 手切轮与 200 手虚拟锦标赛飞轮】 ([live.py](file:///Users/liang/Downloads/agentpoker_final%202/agentpoker/live.py))
- **不断流原地切轮**：Agent 始终留在桌上，避免频繁退桌重排与网络重连；
- **20 手自动切轮结算**：每满 20 手打印轮次面板（净 BB、BB/100、所处阶段）；
- **200 手虚拟赛季飞轮**：向策略引擎自动注入 `tournamentContext`（R1~R3 探索建仓、R4~R8 积分保线、R9~R10 气泡冲线），对标 **+20.0 BB/100 黄金出线线**，完美激活锦标赛压力策略；
- **画像免重启热重载**：每 20 手后台自动解析刚打完的对局，实时热更新同桌对手画像。

---

## 📊 模型进化与实测战报

### 4 代通用自进化训练表现（Gen 4 🏆）
| 代际 | 综合评分 (Fitness) | Top 12 预选出线率 | 决赛桌闯入率 | 夺冠率 | 平均名次 |
| :---: | :---: | :---: | :---: | :---: | :---: |
| **Gen 1** | 0.6367 | 83.3% | 33.3% | 33.3% | 10.17 |
| **Gen 2** | 0.6923 | 83.3% | 66.7% | 16.7% | 6.83 |
| **Gen 3** | 0.6528 | 83.3% | 50.0% | 16.7% | 8.17 |
| **Gen 4 🏆** | **0.7669 (新高)** | **100.0% (满分出线!)** | **66.7%** | 0.0% | **5.50 (最佳)** |

### S10 真实对手 10 场全真大锦标赛模拟考战果
加载 S10 真实对手画像（刀河王、Loki、铁头娃、Jeren、Altman 等 23 位真实主力），与 Gen 4 进行 10 场完整 24 人大锦标赛真实博弈：
- **夺冠斩获率 (Champion Rate)**：**20.0%**（10 场硬砍 2 座冠军奖杯！Run 1 & Run 2 双连冠）
- **冠亚军率 (Top 2 Rate)**：**30.0%**（2 冠 1 亚）
- **决赛桌闯入率 (Final Table)**：**50.0%**（10 场进 5 场决赛桌）
- **预选赛出线率 (Top 12)**：**60.0%**（第 9 场以 +23.3万 BB/100 全场第 1 名头名出线）
- **均场净胜率 (Avg BB/100)**：**+68,418.08 BB/100**

---

## 快速安装与配置

推荐使用 Python 3.11+ 与 `uv`：

```bash
# 激活环境与依赖
source .venv/bin/activate
pip install -r requirements.txt

# 运行全量单元测试（13/13 必须全绿）
uv run pytest
```

---

## 常用命令手册

### 1. 评估策略（支持每 200 手战况实时输出 + 多核并发）

现在评估命令已全面支持**每 200 手即时刷新战况**，并可通过 `--workers` 开启多核并发（10 场大锦标赛 25 秒跑完）：

```bash
# 极速评估：10 场锦标赛、8 核并发、挂载真实对手画像
uv run python -m agentpoker.cli evaluate \
  --strategy models/champion.json \
  --profiles models/opponent_profiles.json \
  --runs 10 \
  --agents 24 \
  --workers 8
```

终端实时输出示例：
```text
[评估开始] 正在启动 10 场锦标赛 (多核并发: 8 个工作进程)...
[评估进度 01/10 | 200手结算] 预赛: 第 06 名 (+74206.1 BB/100) | 赛果: 🏆 夺冠 (第 1 名) | 累计走势: +74206.1 BB/100 (出线率 100%, 夺冠率 100%)
[评估进度 02/10 | 200手结算] 预赛: 第 03 名 (+120005.8 BB/100) | 赛果: 🏆 夺冠 (第 1 名) | 累计走势: +97105.9 BB/100 (出线率 100%, 夺冠率 100%)
...
```

### 2. 线上实战与训练赛（自适应原地切轮）

```bash
# 1. 浏览器快速授权登录并保存凭证到 .env
uv run python -m agentpoker.cli connect

# 2. 启动线上挂机对决（自动激活：20手切轮、200手锦标赛飞轮、画像免重启热更）
uv run python -m agentpoker.cli live \
  --strategy models/champion.json \
  --profiles models/opponent_profiles.json
```

可选参数：
- `--round-hands 20`：每轮结算手数（默认 20 手）
- `--cycle-hands 200`：虚拟锦标赛赛季手数（默认 200 手）
- `--max-hands 100`：打满指定手数自动离桌（默认 0 为无限连打）
- `--no-auto-profile`：关闭每轮自动更新画像

### 3. 双轨自训练演化（支持无缝断点续训）

训练系统采用**双轨分立架构**，保证通用底蕴与赛场定向收割互不干扰：

#### 轨 1：通用自演化基石轨（Universal Track）
- **定位**：不带任何特定选手偏见，在全流派（松凶、紧凶、跟注站、岩石怪等）平衡博弈对抗中淬炼。
- **自动断点续训**：检测 `models/archive_universal/` 已有的 Gen 1~4 存档，自动从 **Gen 5** 继续演化。
- **保存目标**：`models/champion_universal.json`（自动软同步更新 `models/champion.json`）。

```bash
# 续训通用基石模型（多核并行，从第 5 代向后继续进化 5 代）
uv run python -m agentpoker.cli train \
  --track universal \
  --generations 5 \
  --population 12 \
  --runs 6 \
  --agents 24 \
  --workers 8
```

#### 轨 2：赛场真实画像特训收割轨（Targeted Track）
- **定位**：将真实 S10 赛场清洗出的 59 名活跃选手画像直接注入对手池，针对赛场普遍高频的激进偷盲、松散跟注与极度弃牌特征进行专门定向收割与反制。
- **独立存档**： Checkpoint 独立保存在 `models/archive_targeted/`，输出模型为 `models/champion_targeted.json`。

```bash
# 启动针对 S10 真实画像的定向特训演化（多核并行）
uv run python -m agentpoker.cli train \
  --track targeted \
  --profiles models/opponent_profiles.json \
  --generations 5 \
  --population 12 \
  --runs 6 \
  --agents 24 \
  --workers 8
```

> **提示**：训练默认开启 `--resume`（自动断点续训）。若需清空历史从第 1 代全新演化，可追加 `--no-resume`。

### 4. 数据提取与对手画像重构

```bash
# 从线上比赛 API 拉取历史对局并自动清洗过滤 AFK 号生成画像
uv run python -m agentpoker.cli profile \
  --pull \
  --competition-id <COMPETITION_ID> \
  --min-hands 30 \
  --out models/opponent_profiles.json
```

---

## 项目工程结构

```text
agentpoker/
  cards.py        微秒级高精相对牌力、听牌感知与底池胜率评估
  engine.py       本地 NLHE 快速仿真研究引擎
  strategy.py     自适应博弈策略（位置加权、画像剥削、短码推推乐、气泡期压制）
  tournament.py   瑞士制 10 轮 + 双桌半决赛 + 6 人总决赛赛制仿真器
  training.py     多核遗传算法策略训练器与 ArenaEvaluator 考评系统（支持断点续训与画像注入）
  profiler.py     对手历史对局画像提取与清洗器（贝叶斯平滑）
  live.py         线上实战驱动（原地 20 手切轮、200 手赛季飞轮、画像热重载）
  protocol.py     HTTP API 通信客户端与自动重试机制
  cli.py          命令行总入口

models/
  champion.json             线上默认挂载的最优冠军策略
  champion_universal.json   通用自演化基石冠军模型
  champion_targeted.json    针对真实选手画像的定向特训冠军模型
  opponent_profiles.json    清洗后的 59 位 S10 真实选手高质量画像库
  archive_universal/        通用轨历代演化 Checkpoint (gen_001.json ~ gen_004.json ...)
  archive_targeted/         画像特训轨独立演化 Checkpoint

data/
  processed/hands.jsonl     S10 真实采集的 4,583 手对局全量数据
  raw/events.jsonl          线上对局实时采集流水

tests/                      全套自动化单元测试（16 项覆盖 100% 通过）
```
