# Stage 2 Audit & Verification Report: 120-Player Tournament Consistency (`TournamentConfig`)

> **Status**: **PASS (Gate 2 Evaluated and Passed)**  
> **Evaluation Date**: 2026-09-12  
> **Target Gate**: Gate 2 (Tournament Configuration & 120-Player Consistency)

---

## 1. Executive Summary

Stage 2 eliminated fragmented hard-coded values (`36`, `24`, `10`, `20`, `30`, `100`, `200`, `seats=6`) across the codebase and introduced a centralized, immutable, and validated `TournamentConfig` class in [`agentpoker/config.py`](file:///Users/liang/Downloads/agentpoker_final%202/agentpoker/config.py). All training defaults, simulation parameters, battle arenas, CLI commands, and dashboard forms now default to the official 120-player tournament format.

### Key Deliverables in Stage 2
1. **Centralized `TournamentConfig` Dataclass (`agentpoker/config.py`)**:
   - Immutable (`frozen=True`) configuration encapsulating all official tournament specifications.
   - Comprehensive validation on initialization (`__post_init__`):
     - `field_size >= semifinal_qualifiers`
     - `field_size % seats_per_table == 0`
     - `semifinal_qualifiers == semifinal_tables * seats_per_table`
     - `final_qualifiers == seats_per_table`
     - `0.0 < min_completion_rate <= 1.0`
     - `small_blind > 0 and big_blind > small_blind`
   - Exact derived properties:
     - `starting_chips = 20,000`
     - `total_preliminary_hands = 200`
     - `min_hands_required = 160`
     - `num_tables = 20`
     - `top12_rate_baseline = 10.0%` (12 / 120)
     - `final_rate_baseline = 5.0%` (6 / 120)
     - `champion_rate_baseline = 0.833%` (1 / 120)
     - `baseline_fitness = 0.207` (zero-sum equilibrium)
   - Factory profiles: `official_120()`, `fast_36()`, `smoke_24()`.
   - Complete YAML serialization (`from_yaml()`, `to_yaml()`).
2. **Official Tournament Specification File (`configs/tournament.yaml`)**:
   - Fully aligned with official 120-player tournament specifications.
3. **LeagueSimulator Configuration Refactor (`agentpoker/tournament.py`)**:
   - `LeagueSimulator` accepts `TournamentConfig`.
   - Parameterized hardcoded semifinal hands (`self.config.semifinal_hands`), final hands (`self.config.final_hands`), and semifinal qualifiers (`self.config.semifinal_qualifiers`).
   - Retains 100% backward compatibility for existing callers.
4. **Codebase-Wide 120-Player Default Alignment**:
   - `agentpoker/cli.py`: `--agents default=120` across `simulate`, `train`, `evaluate`, and `battle`.
   - `agentpoker/battle.py`: `field_size: int = 120`, `default_field = max(120, min_field)`.
   - `agentpoker/training.py`: `ArenaEvaluator` and `StrategyTrainer` default `pool_size = 120`.
   - `agentpoker/dashboard.py`: Default `agents = 120` in training starter and HTML input form.
   - `run_train.sh`: Default `AGENTS:-120`.

---

## 2. Gate 2 Verification Checklist & Evidence

| Gate ID | Verification Item | Test Function | Result | Evidence |
| :--- | :--- | :--- | :---: | :--- |
| **G2.1** | Official 120-Player Default Structure | `test_default_config_is_official_120` | **PASS** | Field=120, SB=100, BB=200, Stack=100BB, R=10, HPR=20, SF=20, Final=30 |
| **G2.2** | Config Immutability | `test_config_immutability` | **PASS** | `FrozenInstanceError` raised on mutation attempts |
| **G2.3** | Config Validation Invariants | `test_config_validation` | **PASS** | Invalid fields, blinds, ratios, and completion rates raise `ValueError` |
| **G2.4** | Derived Mathematical Properties | `test_derived_properties` | **PASS** | `starting_chips=20000`, `min_hands=160`, `num_tables=20`, `top12_rate=10%`, `baseline_fitness=0.207` |
| **G2.5** | Named Profiles Availability | `test_named_profiles` | **PASS** | `official_120` (120p), `fast_36` (36p), `smoke_24` (24p) verified |
| **G2.6** | YAML Round-Trip Serialization | `test_yaml_round_trip` | **PASS** | `to_yaml` and `from_yaml` preserve identical configuration |
| **G2.7** | Repository Config File Integrity | `test_configs_tournament_yaml_loads` | **PASS** | `configs/tournament.yaml` cleanly loads into `TournamentConfig` |
| **G2.8** | LeagueSimulator Integration | `test_league_simulator_uses_config` | **PASS** | Custom config parameters respected across preliminary, semifinal, and final stages |

---

## 3. Test Suite Status

```
============================= test session starts ==============================
platform darwin -- Python 3.11.16, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/liang/Downloads/agentpoker_final 2
configfile: pyproject.toml
collected 75 items

tests/test_battle.py ....                                                [  5%]
tests/test_calibration.py ..........                                     [ 18%]
tests/test_engine.py ......                                              [ 26%]
tests/test_live_body.py .                                                [ 28%]
tests/test_live_controller.py ..                                         [ 30%]
tests/test_optimization.py ..........                                    [ 44%]
tests/test_protocol.py .                                                 [ 45%]
tests/test_resumable_training.py ....                                    [ 50%]
tests/test_stage1_accounting.py ...........                              [ 65%]
tests/test_stage2_config.py ........                                     [ 76%]
tests/test_strategy_params_live.py ....                                  [ 81%]
tests/test_tournament.py .                                               [ 82%]
tests/test_training_statistics.py .......                                [ 92%]
tests/test_v2_architecture.py ......                                     [100%]

============================== 75 passed in 9.66s ==============================
```

**Gate 2 Verdict: PASS.** Proceeding to **Stage 3: Stage-Aware Context Vector Expansion (`agentpoker/context.py`)**.
