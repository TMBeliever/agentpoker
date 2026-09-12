# Stage 9 Audit & Verification Report: Tournament Evolution Engine Calibration

> **Status**: **PASS (Gate 9 Evaluated and Passed)**  
> **Evaluation Date**: 2026-09-12  
> **Target Gate**: Gate 9 (Tournament Evolution Engine Calibration)

---

## 1. Executive Summary

Stage 9 upgraded and calibrated the tournament evolutionary training engine ([`agentpoker/training.py`](file:///Users/liang/Downloads/agentpoker_final%202/agentpoker/training.py)) to conform strictly with the official 120-player tournament format. 

In a 120-player field, random baseline probabilities are mathematically fixed:
- **Top 12 (Preliminary Advance)**: $\frac{12}{120} = 10.0\%$
- **Final Table (Semifinal Advance)**: $\frac{6}{120} = 5.0\%$
- **Champion (Winner-Take-All)**: $\frac{1}{120} \approx 0.833\%$

Uncalibrated fitness functions that sum raw rates (e.g. $0.25 \times \text{champ\_rate}$) underweighted championship wins in 120-player fields because raw champion rates ($\approx 2\% - 4\%$) were orders of magnitude smaller than small-pool simulations ($\approx 10\% - 20\%$).

### Key Deliverables in Stage 9
1. **Field-Size Equilibrium Calibrated Fitness (`_summarise`)**:
   - Calculates exact baseline expectations ($p_{\text{top}}^*, p_{\text{final}}^*, p_{\text{champ}}^*$) for any field size $N$.
   - Computes normalized advantage multipliers ($\text{adv\_top}, \text{adv\_final}, \text{adv\_champ}$) that measure performance relative to game-theoretic baseline equilibrium.
   - Outputs both legacy `fitness` (for backward-compatibility) and `calibrated_fitness`.
2. **Domain-Specific Constraints & Parameter Clamping (`_clamp_and_validate`)**:
   - Strictly enforces positional hierarchy: $\text{UTG} < \text{HJ} < \text{CO} < \text{BTN}$.
   - Strictly enforces value order: $\text{thin\_value} < \text{value\_threshold} < \text{jam\_threshold}$, and $\text{dry\_board\_size} < \text{wet\_board\_size}$.
   - Tactical coupling: high preflop 3-bet frequency ($\ge 0.09$) enforces minimum postflop aggression ($\text{attack} \ge 0.65$).
3. **Resilient Evolutionary Lifecycle & Checkpointing**:
   - Multi-generation archive checkpointing (`gen_XXX.json`) with automatic generation resumption.
   - Stagnation escape hatch: when fitness improvement stalls for `stagnation_patience` generations, the population resets variance and branches from the all-time peak champion rather than drifting into local minima.
4. **Automated Verification Suite (`tests/test_stage9_evolution.py`)**:
   - Validated 120-player equilibrium rates and advantage factors.
   - Validated poker constraint clamping.
   - Validated generation 1 -> generation 2 checkpoint resumption.
   - Validated robust parameter loading ignoring legacy/extraneous keys.

---

## 2. Gate 9 Verification Checklist & Evidence

| Gate ID | Verification Item | Test Function | Result | Evidence |
| :--- | :--- | :--- | :---: | :--- |
| **G9.1** | 120-Player Equilibrium Baseline | `test_summarise_with_120_player_equilibrium` | **PASS** | $p_{\text{top}}^* = 0.10, p_{\text{final}}^* = 0.05, p_{\text{champ}}^* = 0.00833$; advantage multipliers accurately calculated |
| **G9.2** | Parameter Bounds & Invariant Clamping | `test_clamp_and_validate_enforces_poker_invariants` | **PASS** | Enforces UTG < HJ < CO < BTN, thin_value < value, dry < wet; prevents degenerate strategies |
| **G9.3** | Checkpoint Save & Auto-Resumption | `test_checkpoint_save_and_resumption` | **PASS** | Saves `gen_001.json`, successfully detects and resumes into `gen_002.json` |
| **G9.4** | Robust Parameter Deserialization | `test_safe_load_params_with_extraneous_keys` | **PASS** | `_load_params_safe` cleanly filters out invalid/legacy attributes |

---

## 3. Test Suite Status

```
============================= test session starts ==============================
platform darwin -- Python 3.11.16, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/liang/Downloads/agentpoker_final 2
configfile: pyproject.toml
collected 111 items

tests/test_battle.py ....                                                [  3%]
tests/test_calibration.py ..........                                     [ 12%]
tests/test_engine.py ......                                              [ 18%]
tests/test_live_body.py .                                                [ 18%]
tests/test_live_controller.py ..                                         [ 20%]
tests/test_optimization.py ..........                                    [ 29%]
tests/test_protocol.py .                                                 [ 30%]
tests/test_resumable_training.py ....                                    [ 34%]
tests/test_stage1_accounting.py ...........                              [ 44%]
tests/test_stage2_config.py ........                                     [ 51%]
tests/test_stage3_context.py ......                                      [ 56%]
tests/test_stage4_ecosystem.py .....                                     [ 61%]
tests/test_stage5_swiss.py .....                                         [ 65%]
tests/test_stage6_strategy.py .....                                      [ 70%]
tests/test_stage7_calibration.py ......                                  [ 75%]
tests/test_stage8_live.py .....                                          [ 80%]
tests/test_stage9_evolution.py ....                                      [ 83%]
tests/test_strategy_params_live.py ....                                  [ 87%]
tests/test_tournament.py .                                               [ 88%]
tests/test_training_statistics.py .......                                [ 94%]
tests/test_v2_architecture.py ......                                     [100%]

======================== 111 passed in 86.65s (0:01:26) ========================
```

**Gate 9 Verdict: PASS.** Evolutionary training engine calibrated and verified with 111/111 passing tests. Ready for Stage 10 (Arena Battle & Champion Certification Gate).
