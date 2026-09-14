# 扑克 AI 训练系统基线分析报告 (TRAINING_BASELINE.md)
**阶段状态**: Stage 0 审计完成 (代码严格零改动)  
**审计时间**: 2026-09-14  
**目标版本**: AgentPoker 2.2+ 训练引擎 (`agentpoker/training.py`, `agentpoker/tournament.py`, `agentpoker/engine.py`)

---

## 一、 当前完整训练链路数据流图

```text
       ┌────────────────────────────────────────────────────────┐
       │             Initial Population / Resumed Checkpoint     │
       └───────────────────────────┬────────────────────────────┘
                                   │
                                   ▼
       ┌────────────────────────────────────────────────────────┐
       │  Candidate Generation (Crossover 65% + Gaussian Mutate) │
       └───────────────────────────┬────────────────────────────┘
                                   │
        ┌──────────────────────────┴──────────────────────────┐
        │                                                     │
        ▼                                                     ▼
┌───────────────────────────────┐             ┌───────────────────────────────┐
│     Fixed Archetypes Pool     │             │    Empirical Profiles Pool    │
│ (NIT, Tight, Balanced, etc.)  │             │ (75% Train / 25% "Holdout")   │
└───────────────┬───────────────┘             └───────────────┬───────────────┘
                │                                             │
                └──────────────────────┬──────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ Opponent Pool Assembly (_draw_pool: Profiles + Population + Hall of Fame)   │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ Tournament Simulation (LeagueSimulator.run_event: Prelim 120 -> Semi -> Fin)│
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ Raw Metrics Extraction (me.rank, me.bb100 [Prelim ONLY], top12/final/champ) │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ Fitness Aggregation (_summarise: Top 20% + Final 20% + Champ 25% + BB 30%)  │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ Initial Selection (Ranked by Fitness -> Top 25% Elites Extracted)           │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ Elite Re-Evaluation (Rescore Elites on Fresh CRN Seed & Opponent Pool)      │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ Generation Champion -> Hall of Fame Update -> Parameter Smoothing           │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ Final Race (Stable Champ vs Last-Gen Champ vs Peak Champ on "Holdout Pool") │
│ ⚠️ 严重数据泄露: 用 Holdout 的胜者作为最终 Champion，Holdout 变成 Validation │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ Final Model Output (Save to candidate.json / Promote to champion.json)      │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 二、 数据集真实流向与模型选择映射

| 数据子集 / 环境 | 物理构成来源 | 是否参与训练演化 | 是否参与模型选择 | 真实承担的角色 | 存在问题 |
| :--- | :--- | :---: | :---: | :---: | :--- |
| **Train Profiles** | `opponent_profiles.json` 切分的 75% | **是** | **是** (代际进化筛选) | **训练集 (Train)** | 小样本画像 (15手) 未做置信度收缩 |
| **Train Archetypes** | 6 种标准扑克原型 (NIT, LAG, etc.) | **是** | **是** | **训练集 (Train)** | 固定先验 |
| **Hall of Fame / Clones**| 历史各代前几名镜像 | **是** | **是** | **动态训练集 (Adaptive/Self-Play)**| 混入普通对手池，边界不清晰 |
| **"Holdout Pool"** | `opponent_profiles.json` 切分的 25% + 变异原型 | **否** (无梯度更新) | **是 (致命)** | **验证集 (Validation)** | **伪称 Holdout/Test，实质用于选出终选冠军** |
| **Test Set** | 独立于验证集、完全冻结且只评测一次的测试集 | **无** | **无** | **完全缺失** | 没有任何独立盲测集能衡量最终模型的真实泛化能力 |

---

## 三、 详细基线架构审计 (11 项必须检查)

### 1. 当前训练目标
- 目标：产出兼顾在 120 人 S11 大赛中高胜率出线（Top 12）、进入 6 人决赛桌（Final Table）、斩获冠军（Champion），同时保持稳定筹码积累（BB/100）的策略超参数（23 维连续参数空间）。
- 入口：`agentpoker/cli.py` 的 `train` 子命令，核心驱动类为 `agentpoker/training.py:StrategyTrainer`。

### 2. 当前 Fitness 评估公式
位于 `agentpoker/training.py:80-140` (`_summarise` 函数)：
$$\text{Fitness} = 0.20 \cdot \text{top\_rate} + 0.20 \cdot \text{final\_rate} + 0.25 \cdot \text{champ\_rate} + 0.05 \cdot \left(1 - \frac{\overline{\text{rank}} - 1}{\text{pool} - 1}\right) + 0.30 \cdot \text{bb\_factor}$$
其中：
$$\text{bb\_factor} = \frac{1}{1 + \exp\left(-\frac{\text{clamp}(\overline{\text{bb100}}, -200, 200)}{40.0}\right)}$$

同时计算综合方差传播 $\text{Var}(\text{Fitness})$ 与标准误 $\text{SE} = \sqrt{\text{Var}}$，以及 95% 置信区间。

### 3. 每个 Fitness Component 的数据来源
- `top_rate`: 来自 `int("focal" in result["qualified"])`（预赛 120 人进前 12 名比例）。
- `final_rate`: 来自 `int("focal" in result["final"])`（进入 6 人决赛桌比例）。
- `champ_rate`: 来自 `int(result["final"][0].agent_id == "focal")`（决赛桌第 1 名比例）。
- $\overline{\text{rank}}$: 来自 `me = next(x for x in result["preliminary"] if x.agent_id == "focal")` 的 `me.rank`（**仅为预赛名次**）。
- $\overline{\text{bb100}}$: 来自 `me = next(x for x in result["preliminary"] if x.agent_id == "focal")` 的 `me.bb100`（**仅为预赛 200 手的筹码净收益率**）。
- **严重漏洞**：半决赛（Round 11）与决赛（Round 12）的实际对局手数、净筹码得失、BB/100 全部被丢弃，完全没有流入 Fitness 计算！

### 4. Opponent Pool（对手池）构成
位于 `agentpoker/training.py:532-580` (`_draw_pool` 函数)：
- 一场 120 人锦标赛，Focal 候选需要 119 名对手。
- 构成比例由 `profile_share` 控制（默认 0.5）：
  1. `n_profile`（最多 50%）：从真实画像库（`_train_profile_params`）中随机抽取并施加小幅高斯扰动（Jitter $\sigma=0.015$）。
  2. `n_shadow`（若启用 `self_play`）：从名人堂或当前种群中抽取最多 2 个影子克隆体。
  3. 剩余名额：从基础原型（ARCHETYPES 6 种）+ 当前种群（Population）+ 名人堂（Hall of Fame）的混合大池中抽取。
- **缺陷**：Fixed 生态与 Adaptive 种群混同，无法独立测算对固定风格 vs 适应性对手的表现。

### 5. Self-Play（自我博弈）行为
- 标志位：`--self-play`，由 `shadow_clones` 控制数量（默认 2 个席位）。
- 逻辑：如果启用，在每桌对手中常驻当前种群或名人堂的克隆体，并施加轻微 Jitter。
- **缺陷**：虽然排除了完全相同的引用 `p is not exclude`，但没有严格防御同一 Candidate 的未经变异克隆体作为对手登场；且自博弈未单独计量 exploitability 分数，只是混在一起算总排名。

### 6. Train / Validation / Holdout / Test 的真实关系
- 代码划分 (`training.py:412-425`)：
  - 加载 `opponent_profiles.json` 后，以 `seed + 4242` 将 profile 按 `holdout_frac=0.25` 切为 75% `_train_profile_params` 与 25% `_holdout_profile_params`。
  - `_holdout_archetypes`：对 6 大原型各自施加 $\sigma=0.12$ 变异生成 12 个扰动原型。
- **致命泄漏点**：
  - 在代际演化结束后（`training.py:885-920`），构造了 3 个候选策略：`平滑精英策略`、`末代冠军策略`、`全周期峰值冠军`。
  - 这 3 个候选策略全部在 `holdout_pool` 上跑 `final_race` 场比赛。
  - **谁在 holdout_pool 上的 fitness 最高，谁就被选为最终 Champion 输出保存！**
  - 这意味着所谓的“Holdout”从定义上直接变成了“Validation”，而系统在选出最终模型后，**根本没有真正的独立 Test 集进行冻结评估**。

### 7. Candidate Selection（候选选择）机制
- **代内筛选**：
  1. 初评：种群 $N$ 个个体，每人打 `runs`（如 30~80 场）。
  2. 排序：按元组 `(fitness, top12_rate, champion_rate, -avg_rank)` 降序。
  3. 精选：取前 $\max(3, N/4)$ 名作为精英（Elites）。
- **复评（Elite Re-Evaluation）**：
  - 精英策略在全新的随机种子基准（`seed + 77000000 + g*1009`）和全新抽取的对手池上打 `reeval_runs` 场。
  - 重新排序后，排名第 1 的成为该代 Champion。
- **繁殖机制**：
  - 保留历史全周期最高冠军（Strict Elitism）；
  - 65% 概率执行参数 Crossover（单点参数随机交叉）；
  - 35% 概率直接突变（高斯变异，受参数生理边界与扑克单调性约束剪裁）。

### 8. Random Seed（随机数与 Common Random Numbers）机制
- 采用通用随机数（Common Random Numbers, CRN）：
  - 每场初评对局种子为 `s = seed_base + r * 7919`，同一个 generation 中所有 candidate 使用相同的对手阵容和相同的牌局发牌序列。
  - 这极大削减了候选人之间的抽样方差，属于优秀的基线设计，在重构中必须严格予以继承保留。

### 9. Checkpoint / Resume 机制
- 存档路径：`models/archive/gen_xxx.json`。
- 续训机制（`training.py:755-778`）：
  - 能够读取存档中最后一代理论指标与历史最优指标。
  - 若末代落后历史最优超过 `resume_revert_margin`（0.05），会自动回滚至历史最优并重置变异步长（Sigma Schedule）。
  - 该机制设计严谨，重构中需完整保留。

### 10. 当前已发现的问题清单
1. **数据泄漏与测试集缺位**：Holdout 数据参与了最终 Champion 的三选一仲裁，导致真实泛化指标失真，且缺失最终冻结盲测集（Test Set）。
2. **后程连续反馈缺失（Preliminary-Only Metric）**：半决赛与决赛的 BB/100 和筹码轨迹被彻底丢弃，仅依赖 0/1 的出线/夺冠布尔值，使得模型在锦标赛深水区失去演化梯度。
3. **对手池职能过度混同**：Fixed 原型、Adaptive 种群、Self-play 克隆体全部揉合在单个 `_draw_pool` 中，无法解耦“对未知泛化能力”与“自我防剥削稳定性”。
4. **小样本高方差与固定预算浪费**：初评阶段对明显劣质的候选策略仍然跑满全部 `runs`，而对头部胶着的精英候选缺乏统计显著性检验（SE 未参与置信截断）。
5. **画像未做贝叶斯置信度收缩**：`profile_to_params` 直接读取低手数画像的原始点估计（如 15 手 VPIP=67%），向对手池注入了极端噪声。
6. **Equity 计算缺乏分级加速/校准机制**：初筛演化与终极仲裁使用相同的胜率评估方式，未能形成“演化查表加速 -> 决选高精 Monte Carlo”的合理算力分级。

### 11. 每个问题的严重程度分级

| 序号 | 问题描述 | 严重级别 | 影响阶段 | 重构优先级 |
| :--- | :--- | :---: | :---: | :---: |
| **P1** | Holdout 参与 Champion 选择，无真正 Test 集（数据泄漏） | **CRITICAL (致命)** | Stage 1 | **第 1 优先级** |
| **P2** | 后程比赛（半决赛/决赛）筹码连续指标被彻底丢弃 | **CRITICAL (致命)** | Stage 2 | **第 2 优先级** |
| **P3** | 对手池职能混同，缺少独立的生态切分与克隆隔离 | **HIGH (严重)** | Stage 3 | **第 3 优先级** |
| **P4** | 固定评估预算无早停，SE 未用于统计置信度决策 | **HIGH (严重)** | Stage 4 | **第 4 优先级** |
| **P5** | 低手数真实画像未做贝叶斯收缩直接入池 | **MEDIUM (中度)** | Stage 5 | **第 5 优先级** |
| **P6** | 终验阶段缺少高精度 Monte Carlo Equity 校验 | **MEDIUM (中度)** | Stage 5 | **第 5 优先级** |

---

## 四、 编译与测试收集基线结果

执行命令：
```bash
uv run python -m compileall agentpoker tests
uv run pytest --collect-only -q
```
**结果状态**:
- 编译状态: 全部通过 (Exit Code 0)
- 测试收集: `183 tests collected in 0.14s` (Exit Code 0)
- 代码库完整性验证正常，基线状态完全锁定。
