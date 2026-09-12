# AgentPoker v2 核心架构改造工程规范 (TRANSFORMATION SPEC)

> **版本**：v2.0-Draft  
> **适用环境**：120 人锦标赛（200 手预赛 + 瑞士动态分桌 + 20 手半决赛 + 30 手总决赛，无限买入，BB/100 排名）  
> **目标**：在保留现有模拟器与牌力评估底座的前提下，彻底重构策略决策层，消除代际退化，实现 120 人大奖赛高胜率出线与夺冠。

---

## 一、改造目标与总体架构拓扑

```mermaid
graph TD
    subgraph 1. 状态感知层 (State Layer)
        S1[Poker State: 位置/SPR/底池赔率/牌面干燥度]
        S2[Opponent State: Dirichlet 软概率画像]
        S3[Tournament State: 距Top12截断线差距/剩余手数]
        S4[Table State: 瑞士轮全桌加权强度]
    end

    subgraph 2. 策略决策层 (Policy Layer - 3-Tier Decoupling)
        T1[Tier 1: GTO 起手与下注基线 - 6位置矩阵]
        T2[Tier 2: 贝叶斯单向剥削调制 - 针对鱼/鲨鱼]
        T3[Tier 3: 锦标赛效用整流器 - 领先控池/落后搏命]
        MW[Multiway Filter: 多人底池衰减与纯空气诈唬熔断]
    end

    subgraph 3. 训练与演化层 (Evolution & Benchmark)
        E1[Strict Elitism: 历史最强者终生锚定]
        E2[High-SNR Fitness: 30% BB/100 提权去噪]
        E3[Pyramid Opponent Pool: 11鲨:14中:11鱼]
    end

    S1 & S2 --> T1
    T1 --> T2
    S3 & S4 --> T3
    T2 & T3 --> MW
    MW --> Action[输出合法决策 Action]
    Action --> E1 & E2 & E3
```

---

## 二、P0 级核心改造详细技术规范（立即交付）

### 1. P0-1: 严格精英锚定（Strict Elitism）与抗回滚
* **当前病灶**：历史最优未强行注入每代种群，导致第 25~28 代在错误方向连续盲目漂移 4 代。
* **工程实现**（位于 `agentpoker/training.py`）：
  ```python
  # 严格精英锚定: 无论当前代评分如何，历史最优 champion 必须占有下一代新种群的第 1 席位
  new = [replace(best_ever_champion)] if best_ever_champion is not None else []
  for p in elites:
      if len(new) < elite_n + (1 if best_ever_champion is not None else 0):
          if not any(asdict(p) == asdict(x) for x in new):
              new.append(replace(p))
  # 杂交父代池必须强制包含历史最优
  parent_pool = [best_ever_champion] + elites if best_ever_champion is not None else elites
  while len(new) < population:
      child = self.crossover(self.rng.choice(parent_pool), self.rng.choice(parent_pool)) \
              if self.rng.random() < 0.65 else self.rng.choice(parent_pool)
      new.append(self.mutate(child, sigma))
  pop = new
  ```

---

### 2. P0-2: 高信噪比 Fitness 适应度函数
* **当前病灶**：70% 权重押在 40 场里极其随机的夺冠/决赛上，真正体现牌技的 BB/100 仅占 5%。
* **重构公式**（位于 `agentpoker/training.py` `_summarise`）：
  $$\text{Fitness} = 0.30 \cdot \text{bb\_factor} + 0.25 \cdot \text{champ\_rate} + 0.20 \cdot \text{final\_rate} + 0.20 \cdot \text{top12\_rate} + 0.05 \cdot \text{rank\_score}$$
  其中：
  $$\text{bb\_factor} = \frac{1}{1 + \exp\left(-\frac{\text{avg\_bb100}}{40.0}\right)}$$
* **标准误 SE 传播修正**：
  $$\text{Var} = 0.20^2 \text{Var}(top) + 0.20^2 \text{Var}(final) + 0.25^2 \text{Var}(champ) + 2\sum \text{Cov} + \left(\frac{0.30}{160.0}\right)^2 \frac{\sigma_{\text{bb}}^2}{N}$$

---

### 3. P0-3: 战术强约束与参数边界硬钳制
* **当前病灶**：28 个参数各自独立随机变异，产生“翻前 3-Bet 20% 疯狗 + 翻后 Attack 0.56 怂包”的畸形策略。
* **物理边界与联动代码**（位于 `agentpoker/training.py` `_clamp_and_validate`）：
  ```python
  PARAM_BOUNDS = {
      "threebet_frequency": (0.04, 0.14), # 限高 14%，切断自杀式 3-Bet 突变
      "steal_frequency": (0.55, 0.85),    # 限高 85%，防止连垃圾牌都无脑偷盲
  }
  # 战术联动硬约束: 敢造大底池翻后就必须敢开枪掩护
  if d["threebet_frequency"] >= 0.09:
      d["attack"] = max(d["attack"], min(0.92, 0.65 + (d["threebet_frequency"] - 0.09) * 2.5))
  ```

---

### 4. P0-4: 多人底池保护层（Multiway Layer）
* **当前病灶**：4 人底池依然以单挑的 51% 频率 C-Bet、16% 频率河牌纯空气诈唬，被多张成牌和跟注站击溃。
* **技术实现**（注入 `agentpoker/strategy.py`）：
  ```python
  def apply_multiway_safety(action: dict, active_opponents: int, board_wetness: float, has_blocker: bool) -> dict:
      if active_opponents <= 1:
          return action
      
      # 1. 下注频率按人数几何衰减 (两人 50%, 三人 25%)
      decay = 0.50 ** (active_opponents - 1)
      
      # 2. 纯空气诈唬强行熔断
      if action.get("is_pure_bluff", False):
          if not has_blocker or active_opponents >= 3:
              return {"type": "check"} if "check" in action.get("legal", {}) else {"type": "fold"}
      
      # 3. 价值下注门槛随人数提升
      if not action.get("is_pure_bluff", False) and action.get("type") in ("bet", "raise"):
          min_equity = 0.60 + (active_opponents - 1) * 0.06
          if action.get("equity", 1.0) < min_equity:
              return {"type": "check"}
      return action
  ```

---

### 5. P0-5: 翻前 6 位置独立起手牌矩阵（Position Model）
* **当前病灶**：全位置共用 `open_frequency`，无法体现 UTG 15% 与 BTN 50% 的巨大位置鸿沟。
* **重构方案**：
  在 `StrategyParams` 中引入 6 个独立阈值，直接对照 169 类起手牌标准手力评分表 $S(\text{hand}) \in [0, 100]$：
  - `open_thresh_utg`：初始 82（仅开前 15% 强牌：77+, ATs+, KQs, AJo+）；
  - `open_thresh_hj`：初始 78（前 19%）；
  - `open_thresh_co`：初始 70（前 27%）；
  - `open_thresh_btn`：初始 50（前 48% 狂偷盲）；
  - `open_thresh_sb`：初始 62（BvB 激进加注）；
  - `defend_thresh_bb`：初始 55（宽范围防守盲注）。

---

## 三、P1 级进阶架构设计详细技术规范

### 1. P1-1: 锦标赛宏观效用引擎（Tournament State Engine）
* **数学建模**：废除经验性的 `safety/attack` 加减法，引入正态累积分布出线概率导数：
  $$\gamma_{\text{risk}} = \begin{cases}
  -\min\left(1.0, \frac{\text{gap}}{25.0}\right) \times \left(1 - \frac{N_{\text{rem}}}{200}\right) & \text{当 } \text{gap} > 0 \text{ (领先区: 极度风险厌恶)} \\
  +\min\left(1.5, \frac{|\text{gap}|}{15.0} \times \sqrt{\frac{50}{\max(1, N_{\text{rem}})}}\right) & \text{当 } \text{gap} \le 0 \text{ (落后区: 极度风险偏好)}
  \end{cases}$$
* **动作传导**：
  - $\gamma_{\text{risk}} < -0.4$ 时：价值阈值上调 $+0.08$，强制过牌控池，拒绝任何边缘对抽；
  - $\gamma_{\text{risk}} > +0.5$ 且 $N_{\text{rem}} \le 10$ 时：强行开启 **Nash Push/Fold 矩阵** 搏命。

---

### 2. P1-2: 瑞士轮全桌强度自适应（Table Strength Model）
* **定义指标**：
  $$\mathcal{S}_{\text{table}} = \frac{1}{5} \sum_{j=1}^{5} \tanh\left(\frac{\text{BB100}_j}{40.0}\right)$$
* **策略响应**：
  - **鱼塘桌 ($\mathcal{S}_{\text{table}} < -0.3$)**：Open 范围放大 20%，湿润面重注 80%~90% Pot 强收过路费，零诈唬；
  - **鲨鱼桌 ($\mathcal{S}_{\text{table}} > +0.3$)**：严控 3-Bet $\le 9\%$，翻后 20%~33% 小注控池，强化防守。

---

### 3. P1-3: 贝叶斯 Dirichlet 软画像与样本收缩（Soft Opponent Mixture）
* **概率向量**：$\mathbf{P} = [P_{\text{Fish}}, P_{\text{TAG}}, P_{\text{LAG}}, P_{\text{Maniac}}, P_{\text{Nit}}]$；
* **收缩公式**：在当前赛局手数 $N < 40$ 时，平滑向全场先验收缩：
  $$\mathbf{P}_{\text{effective}} = \frac{N}{N + 25} \mathbf{P}_{\text{empirical}} + \frac{25}{N + 25} \mathbf{P}_{\text{prior}}$$
  绝不允许在样本不足 20 手时对真人做极端过度剥削。

---

## 四、参数矩阵升级对照全表

| 现有参数 (v1) | 动作 | v2 新系统处理方式 |
| :--- | :---: | :--- |
| `vpip` | ❌ 删除 | 废除独立控制旋钮。由各位置起手牌开池自然统计涌现 |
| `open_frequency` | ❌ 删除 | 拆解为 `open_thresh_[pos]` 六个位置独立阈值 |
| `threebet_frequency` | ⚠️ 修改 | 废除盲目全局频率，改为基于对手 `fold_to_3bet` 剥削触发 |
| `steal_frequency` | ❌ 删除 | 完全合并至 CO / BTN / SB 的起手牌矩阵 |
| `squeeze_frequency` | ⚠️ 修改 | 改为由 Pot Odds 与 Squeeze Equity 阈值动态触发 |
| `cbet_frequency` | ❌ 删除 | 废除固定摇号，由 Board Texture 与 Range Advantage 计算产生 |
| `turn_barrel_frequency` | ❌ 删除 | 由转牌惊悚牌（Scare Card）与胜率变动动态决策 |
| `river_bluff_frequency` | ❌ 删除 | 升级为基于 Alpha 底池赔率与坚果阻断牌评分 |
| `value_threshold` 等 | ⚠️ 精简 | 7 个胜率阈值合并为基准价值门槛与薄价值差值 |
| `safety` / `attack` | ❌ 删除 | 替换为 Tournament State Engine 输出的风险因子 $\gamma_{\text{risk}}$ |
| `bubble_aggression` | ❌ 删除 | 替换为 Horizon 倒计时动态解析函数 |
| `late_aggression` | ❌ 删除 | 替换为 Horizon 倒计时动态解析函数 |
| `open_size` | ✅ 保留 | 固化为 2.15~2.25 BB 的高效率 Min-raise |
| `dry/wet_board_size` | ✅ 保留 | 保留干面 0.20~0.30、湿面 0.60~0.75 的极佳尺度分化 |
| `temperature` | ✅ 保留 | 动作随机性参数，保留并加入训练代数退火 |
| `equity_samples` | ✅ 保留 | 保留离线快速查表与在线实时蒙特卡洛采样的切换 |
