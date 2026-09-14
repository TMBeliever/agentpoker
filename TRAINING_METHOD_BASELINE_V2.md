# AgentPoker 训练系统第二轮训练方法基线审计报告 (TRAINING_METHOD_BASELINE_V2)

> **审计执行阶段**：Stage 0（第二轮训练方法优化基线重构）  
> **审计代码基线**：Git Commit `HEAD` (`agentpoker/training.py`, `agentpoker/tournament.py`, `agentpoker/profiler.py`, `agentpoker/strategy.py`, `agentpoker/battle.py`)  
> **审计核心目标**：针对“单一对手生态过拟合、CRN 掩盖生态间方差、Validation/Test 扰动过弱、Self-Play 近亲回音壁、Profile 缺乏后验分布采样”等剩余结构性缺陷，进行代码级深度数据流复盘与定性定量分析。

---

## 1. 当前 CRN（公共随机数）数据流审计

### 1.1 核心实体映射与流转关系
在 `agentpoker/training.py` 的 `_score_population` 与 `_evaluate_single_tournament_worker` 中，CRN 的数据流如下：

```
Generation g
  │
  ├─► pool = _draw_pool(pop, hall, seed = self.seed * 7919 + g, ...)  [单次生成 119 个固定对手]
  │
  ├─► seed_base = self.seed + g * 1000003
  │
  └─► For run r in 0 .. runs-1:
        s_r = seed_base + r * 7919
        ├── Candidate 0 ──► Task(c0, pool, s_r) ──► LeagueSimulator(seed = s_r, agents=[c0, opp0..opp118])
        ├── Candidate 1 ──► Task(c1, pool, s_r) ──► LeagueSimulator(seed = s_r, agents=[c1, opp0..opp118])
        └── Candidate k ──► Task(ck, pool, s_r) ──► LeagueSimulator(seed = s_r, agents=[ck, opp0..opp118])
```

1. **Candidate 与 Seed 的绑定**：
   对于第 $r$ 场比赛，所有 Candidate $c_0, c_1, \dots, c_k$ 接收到严格相同的整数随机种子 $s_r = \text{seed\_base} + r \times 7919$。
2. **Opponent Pool 绑定**：
   在单代演化内，所有 Candidate 在全部 $R$ 场比赛中面对的 119 个对手参数（`opp0` 到 `opp118`）是**同一个内存列表 `pool`**。
3. **Opponent Ordering（排位顺序）**：
   在 `_evaluate_single_tournament_worker` 中，参赛选手列表固定组装为 `agents = [focal, opp0, opp1, ..., opp118]`。初始分桌时，`random_groups(ids, seats, rng)` 使用由 $s_r$ 初始化的 `Random` 生成排列。因此，不同 Candidate 在同一 $s_r$ 下的初始座位映射是完全等价的。
4. **Cards（手牌流与公共牌流）**：
   比赛引擎由 `NLHEngine(..., seed=s_r)` 驱动。每局发牌的洗牌状态完全由 $s_r$ 决定。
   *分叉性（Divergence）*：虽然初始发牌序列一致，但一旦 Candidate A 与 Candidate B 在第 1 手做出不同行动（例如 A 弃牌而 B 跟注看翻牌），后续公共牌的消耗数量即刻改变，且在 Swiss 赛制（R4-R10）中会因累积筹码分歧导致换桌编排分流。

### 1.2 关键问题专项核查回答
| 关键问题 | 判定 | 代码证据与分析 |
| :--- | :---: | :--- |
| **同一 pool 是否被多个 candidate 使用？** | **是** | `_score_population`（L1076-1077）在循环外调用一次 `_draw_pool`，生成一个 `pool` 传给本代所有 candidate 的初评/复评任务。 |
| **同一 pool 是否被同一 candidate 的所有 run 使用？** | **是** | 单个 candidate 评估 30 场时，30 场面对的 119 个对手参数完全不变，只有对局发牌种子 $s_r$ 递增变化。 |
| **不同 generation 是否复用 pool？** | **否** | 每一代 $g$ 的抽样种子为 `self.seed * 7919 + g`，且随着代数增加切换动态课程配比（早期鱼多、晚期常规多）。但每代内部的 30 场依然面对同一个静态 pool。 |
| **validation 是否复用 pool？** | **否** | `validation_pool = self.validation_env.sample_pool(..., seed=self.seed + 90210)`。所有决选候选者共享此独立池，但该池与训练池独立。 |
| **test 是否复用 train/validation pool？** | **否** | `test_pool = self.test_env.sample_pool(..., seed=self.seed + 777777)`。与训练池和验证池均物理隔离。 |

---

## 2. 当前 Opponent Ecology 架构与独立性分析

### 2.1 5 类 Ecology 结构对比图
```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           5 类 Ecology 对比全景图                            │
├───────────────────┬───────────────────────────┬─────────────────────────────┤
│ 生态类型          │ 构成比例 (Composition)     │ 对手来源 (Source)           │
├───────────────────┼───────────────────────────┼─────────────────────────────┤
│ 1. Train Ecology  │ 早期: 30%鲨鱼, 35%常, 35%鱼 │ 内置 6 大基础原型 +          │
│                   │ 中期: 30%鲨鱼, 40%常, 30%鱼 │ Train 画像 (无抖动/固定值)   │
│                   │ 晚期: 25%鲨鱼, 55%常, 20%鱼 │                             │
├───────────────────┼───────────────────────────┼─────────────────────────────┤
│ 2. Validation     │ 固定: 30%鲨鱼, 40%常, 30%鱼 │ 6 大原型 + 10% 高斯变异 +    │
│    Ecology        │                           │ Val 画像 (独立拆分)         │
├───────────────────┼───────────────────────────┼─────────────────────────────┤
│ 3. Test Ecology   │ 固定: 30%鲨鱼, 40%常, 30%鱼 │ 6 大原型 + 15% 高斯变异 +    │
│    (Frozen)       │                           │ Test 画像 (独立拆分)        │
├───────────────────┼───────────────────────────┼─────────────────────────────┤
│ 4. Adaptive       │ 动态金字塔比例随着世代平滑 │ 种群存活个体 (Population) +  │
│    Ecology        │ 递进 (与 Train 一致)      │ 历史名人堂 (Hall of Fame)   │
├───────────────────┼───────────────────────────┼─────────────────────────────┤
│ 5. Self-Play      │ 替换上述生态中不超过 20%   │ 选自 Hall 或当前 Population  │
│    Ecology        │ (最多 min(shadow, n//4))  │ 施加固定 σ=0.015 参数抖动   │
└───────────────────┴───────────────────────────┴─────────────────────────────┘
```

### 2.2 独立性缺陷审计：哪些东西依然完全相同？
* **原型家族完全相同 (Archetype Family)**：所有生态底层均衍生自相同的 6 个硬编码原型（`tight`, `balanced`, `lag`, `station`, `maniac`, `nit`）。
* **参数空间上下界完全相同 (Parameter Range)**：全部受限于 `StrategyTrainer.PARAM_BOUNDS`。
* **变异扰动机制雷同 (Jitter Mechanism)**：
  * Validation 只等于 `base_archetypes` 施加 $\sigma = 0.10$ 基因变异；
  * Test 只等于 `base_archetypes` 施加 $\sigma = 0.15$ 基因变异。
  * **结论**：验证集和测试集只是原型的“浅层高斯毛刺”，并没有改变打法逻辑结构。
* **宏观配比高度雷同 (Composition Invariance)**：
  除了训练早期的微调（35%鱼对30%鱼）外，Validation 与 Test 均严格按照 **30% 鲨鱼、40% 常规、30% 鱼** 的同一套金字塔比例组装。**系统从未测试过非对称极端环境（例如 60% Maniac 极度血腥桌，或 80% Nit 极度被动岩石桌）**。

---

## 3. 当前 Self-Play 机制与近亲回音壁（Echo Chamber）审计

代码位置：[`agentpoker/training.py:1000-1010`](file:///Users/l/files/sohu/agentpoker/agentpoker/training.py)

```python
if self.self_play and n >= 4:
    shadow_candidates = [p for _, p in hall] if hall else [p for p in population if p is not exclude]
    if not shadow_candidates and profile_pool:
        shadow_candidates = profile_pool
    if shadow_candidates:
        max_shadow = min(self.shadow_clones, max(1, n // 4))
        for _ in range(max_shadow):
            cand = rng.choice(shadow_candidates)
            out.append(self._jitter(cand, rng))
```

### 3.1 近亲排除漏洞排查
1. **Exact Duplicate（完全相同克隆）**：
   * 当前仅使用 `p is not exclude` 进行 Python 对象内存地址比较。如果种群中因交叉或变异产生了与候选者参数完全相同的副本个体，该个体**会被合法选中作为自博弈对手入池**。
2. **Near-Clone（极近突变体）**：
   * 若某个体是 Candidate 的微小突变版本（如仅有一两处参数差 0.01），`p is not exclude` 返回 `True`，该近亲个体同样入池。
3. **Previous-generation Parent（上一代父本）**：
   * `hall` 中存储的是历史世代表现优秀的模型。如果 Candidate 是从 Hall of Fame 中某个 Elite 直接衍生而来，其父本会作为影子克隆体与自己在同一张锦标赛桌面对决。
4. **Hall-of-Fame Neighbor（名人堂近亲堆叠）**：
   * 当前 `hall` 只维护前 12 名适应度最高的个体，**没有任何基因距离去重过滤**。如果算法在某种特定打法（如微紧凶 TAG）上连续演化 10 代，整个名人堂将全部充斥着同一种风格的微小变体，自博弈演化退化为“同门互刷”。

---

## 4. 当前 Profile Smoothing 与对手参数生成完整链路审计

完整调用链路追踪如下：

```
[原始牌局] Raw Hand History Actions (bet, call, raise, fold)
    │
    ▼ (OpponentProfiler.ingest_hand, profiler.py:110-180)
[频数统计] StatMetric (count, opportunities)
    │
    ▼ (OpponentProfiler.export, profiler.py:43-58)
[经验贝叶斯平滑] smoothed_rate = (count + prior_weight * population_prior) / (opportunities + prior_weight)
    │
    ▼ (models/opponent_profiles.json)
[静态文件存储] 导出的 JSON 保存单个确定性数值 (如 "vpip": 0.2450)
    │
    ▼ (profile_to_params, training.py:474-535)
[点估计映射] vpip = num("vpip", 0.25, 0.08, 0.85) ──► 转化为单一固定的 StrategyParams 对象
    │
    ▼ (_draw_pool, training.py:1000-1040)
[静态参数入池] 将 StrategyParams 加入对手池 (仅附加固定 σ=0.015 的随机微小扰动)
    │
    ▼ (LeagueSimulator, tournament.py)
[锦标赛执行] 对手以完全确定的参数执行决策
```

### 4.1 核心断层与失真诊断
* **平滑确实存在，但被单点压缩（Collapsed to Point Estimate）**：
  在 `OpponentProfiler` 中，贝叶斯先验平滑真实存在（避免了小样本极端值）。**但导出的只是后验均值（Posterior Mean）这一个标量**！
* **后验方差（Posterior Variance）被彻底丢弃**：
  * 一个只打了 15 手牌的对手（VPIP 置信度仅约 35%，后验方差极大）；
  * 与一个打了 3000 手牌的对手（VPIP 置信度达 99.7%，后验方差极小）；
  在进入 `profile_to_params` 时，被当成了**完全没有认知不确定性（Epistemic Uncertainty）的确定性常数**。
* **对手池没有后验采样**：
  `_draw_pool` 没有从 $\text{Beta}(\alpha, \beta)$ 等后验分布中抽样对手行为，小样本对手的估计误差没有转化为对手池参数的丰富性，反而让训练模型误以为该对手的打法是绝对确定性的。

---

## 5. 当前发现的结构性风险清单

| 编号 | 风险名称 | 产生根源 | 潜在危害与失效场景 |
| :---: | :--- | :--- | :--- |
| **R1** | **CRN 单生态遮蔽风险** | 30 场训练赛打的都是同一套 119 人静态对手名单，仅变换发牌种子 | 模型只学会了战胜这特定 119 人的组合，无法适应对手整体偏激进或偏保守的赛场 |
| **R2** | **泛化评估虚假安全** | Validation 与 Test 只是基础原型的 10% 与 15% 高斯抖动 | 测试集无法暴露模型面对“未见过的风格组合、极端牌风比例”时的灾难性崩溃 |
| **R3** | **均值适应度偏科惩罚缺失** | 适应度仅求所有 Run 的算术均值，缺少生态间鲁棒性指标 | 偏好“在 4 个生态打 +100，但在 1 个生态暴亏 -300”的极度偏科脆弱模型 |
| **R4** | **自博弈回音壁近亲塌陷** | 自博弈仅排除 `is not exclude`，缺乏参数欧式/哈希距离约束 | 候选策略与同胞克隆体或父本互相博弈，容易陷入自我强化的近亲局部最优 |
| **R5** | **画像确定性点估计失真** | 忽略样本量对后验不确定性的影响，小样本对手被当作确定真值 | 训练出的剥削策略基于小样本噪声，实战中面对真实对手的真实波动容易误判 |

---

## 6. 风险优先级与重构路线对应表

| 优先级 | 对应风险 | 目标重构阶段 | 关键改造措施 |
| :---: | :---: | :---: | :--- |
| **P0 (最高)** | **R1: CRN 单生态遮蔽** | **Stage 1: Multi-Ecology Evaluation** | 拆分为 5 大独立生态（均衡、激进、被动、混合、对抗），生态内用 CRN、生态间独立采样，测量 `between_ecology_variance` |
| **P1** | **R2: 泛化评估虚假安全** | **Stage 2: Validation/Test Distribution Shift** | 构造真正具备分布偏移（未见组合、未见参数空间）的 Validation/Test 生态，输出三维分布特征审计表 |
| **P2** | **R3: 均值适应度偏科** | **Stage 3: Between-Ecology Robust Fitness** | 引入生态间方差惩罚与最差生态加权，惩罚在极端赛场崩溃的候选策略 |
| **P3** | **R4: 自博弈回音壁** | **Stage 4: Self-Play 基因隔离与多样性** | 建立 `genome_distance` 与哈希签名，硬性排除近亲克隆；重构名人堂实施适应度+多样性双选 |
| **P4** | **R5: 画像点估计失真** | **Stage 5: Profile 后验分布抽样** | 建立完整贝叶斯后验分布（Beta/Dirichlet），随样本量缩放后验方差，从分布中动态采样对手参数 |
| **P5 (收官)** | **全流程基线对比** | **Stage 6: 第二轮最终泛化验收** | 执行 A/B 严格统计学检验（Seen / Unseen / Shift / Stability 4 大实验），输出完整 V3 结项报告 |

---

## 7. Stage 0 验收结论

```text
========================================
STAGE 0 ACCEPTANCE
========================================

Implementation:
1. 深入排查并量化了当前 CRN 在单代 30 场中复用静态对手池、仅变换发牌种子的具体逻辑与分叉点。
2. 绘制了 5 类 Ecology 构成全景图，证实 Validation (10% mutate) 与 Test (15% mutate) 未形成真实 Distribution Shift。
3. 证实当前 Self-Play 仅靠对象 ID 排除候选者，未设置基因距离防线，存在克隆与父本回音壁漏洞。
4. 追踪了 Profile 从原始手牌到平滑导出的全链路，证实平滑结果在进入训练时坍缩为单一确定性点估计。
5. 形成了包含 5 大结构性风险与优先级映射的完整重构路线图。

Files created:
- TRAINING_METHOD_BASELINE_V2.md

Verdict:
PASS
```
