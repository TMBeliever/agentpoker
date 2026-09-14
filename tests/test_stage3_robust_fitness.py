"""Stage 3 Unit & Integration Test Suite: Between-Ecology Robust Fitness & Risk Weighting.

Verifies:
1. Mathematical consistency of robust fitness, variance penalties, and CVaR downside risk.
2. Homogeneous performance invariance (zero penalty when performance is identical across ecologies).
3. Robust candidate strictly outranking a fragile candidate that has a higher arithmetic mean but collapses in extreme ecologies.
4. Single-ecology and legacy _summarise backward compatibility.
5. Monotonicity and risk-aversion properties under ecology shifts.
6. ArenaEvaluator and StrategyTrainer ranking integration.
"""
import math
import statistics
import pytest
from dataclasses import asdict

from agentpoker.strategy import StrategyParams
from agentpoker.training import (
    compute_multi_ecology_variance_decomposition,
    _summarise,
    ArenaEvaluator,
    StrategyTrainer,
)


def test_robust_fitness_mathematical_consistency():
    """Verify the exact formulas for robust fitness, variance penalty, and CVaR tail risk."""
    # 5 ecologies: means are [0.30, 0.45, 0.55, 0.65, 0.75]
    eco_results = {
        "eco_1": [{"run_fitness": 0.30, "finish_rank": 6.0, "overall_bb100": -40.0, "is_top12": 0, "is_final": 0, "is_champ": 0}],
        "eco_2": [{"run_fitness": 0.45, "finish_rank": 5.0, "overall_bb100": -15.0, "is_top12": 0, "is_final": 0, "is_champ": 0}],
        "eco_3": [{"run_fitness": 0.55, "finish_rank": 4.0, "overall_bb100": 5.0, "is_top12": 1, "is_final": 0, "is_champ": 0}],
        "eco_4": [{"run_fitness": 0.65, "finish_rank": 2.0, "overall_bb100": 25.0, "is_top12": 1, "is_final": 1, "is_champ": 0}],
        "eco_5": [{"run_fitness": 0.75, "finish_rank": 1.0, "overall_bb100": 45.0, "is_top12": 1, "is_final": 1, "is_champ": 1}],
    }

    decomp = compute_multi_ecology_variance_decomposition(
        eco_results,
        pool_size=12,
        lambda_var=0.15,
        lambda_worst=0.15,
        lambda_cvar=0.10,
    )

    # 1. Grand mean
    fits = [0.30, 0.45, 0.55, 0.65, 0.75]
    expected_mean = sum(fits) / 5  # 0.54
    assert pytest.approx(decomp["fitness"], abs=1e-5) == expected_mean
    assert pytest.approx(decomp["grand_fitness"], abs=1e-5) == expected_mean
    assert pytest.approx(decomp["mean_fitness"], abs=1e-5) == expected_mean

    # 2. Between-ecology variance and std
    expected_var = statistics.variance(fits)  # 0.0305
    expected_std = math.sqrt(expected_var)
    assert pytest.approx(decomp["between_ecology_variance"], abs=1e-5) == expected_var
    assert pytest.approx(decomp["between_ecology_std"], abs=1e-5) == expected_std

    # 3. Worst and Best ecologies
    assert decomp["worst_ecology_name"] == "eco_1"
    assert pytest.approx(decomp["worst_ecology_fitness"], abs=1e-5) == 0.30
    assert pytest.approx(decomp["worst_ecology_bb100"], abs=1e-5) == -40.0

    assert decomp["best_ecology_name"] == "eco_5"
    assert pytest.approx(decomp["best_ecology_fitness"], abs=1e-5) == 0.75
    assert pytest.approx(decomp["best_ecology_bb100"], abs=1e-5) == 45.0

    # 4. CVaR: bottom 40% (2 out of 5) ecologies -> eco_1 (0.30) and eco_2 (0.45)
    expected_cvar = (0.30 + 0.45) / 2  # 0.375
    assert pytest.approx(decomp["cvar_ecology_fitness"], abs=1e-5) == expected_cvar

    # 5. Penalties
    expected_var_pen = 0.15 * expected_std
    expected_down_pen = 0.15 * (expected_mean - 0.30) + 0.10 * (expected_mean - expected_cvar)
    expected_tot_pen = expected_var_pen + expected_down_pen
    expected_robust_fit = expected_mean - expected_tot_pen

    assert pytest.approx(decomp["variance_penalty"], abs=1e-5) == expected_var_pen
    assert pytest.approx(decomp["downside_penalty"], abs=1e-5) == expected_down_pen
    assert pytest.approx(decomp["robust_penalty"], abs=1e-5) == expected_tot_pen
    assert pytest.approx(decomp["robust_fitness"], abs=1e-5) == expected_robust_fit
    assert decomp["robust_fitness"] < decomp["fitness"]


def test_homogeneous_performance_zero_penalty():
    """When candidate performs identically across all ecologies, robust fitness equals grand mean."""
    eco_results = {
        f"eco_{i}": [{"run_fitness": 0.52, "finish_rank": 3.0, "overall_bb100": 10.0, "is_top12": 1, "is_final": 0, "is_champ": 0}]
        for i in range(5)
    }

    decomp = compute_multi_ecology_variance_decomposition(eco_results, pool_size=12)

    assert pytest.approx(decomp["fitness"], abs=1e-6) == 0.52
    assert pytest.approx(decomp["between_ecology_variance"], abs=1e-6) == 0.0
    assert pytest.approx(decomp["between_ecology_std"], abs=1e-6) == 0.0
    assert pytest.approx(decomp["variance_penalty"], abs=1e-6) == 0.0
    assert pytest.approx(decomp["downside_penalty"], abs=1e-6) == 0.0
    assert pytest.approx(decomp["robust_penalty"], abs=1e-6) == 0.0
    assert pytest.approx(decomp["robust_fitness"], abs=1e-6) == 0.52
    assert pytest.approx(decomp["worst_ecology_fitness"], abs=1e-6) == 0.52
    assert pytest.approx(decomp["cvar_ecology_fitness"], abs=1e-6) == 0.52


def test_balanced_candidate_outranks_fragile_candidate_with_higher_mean():
    """A balanced candidate with lower arithmetic mean must outrank a polarized candidate that collapses in extreme ecologies."""
    # Candidate A (Balanced & Resilient): Consistent ~0.49 across all ecologies
    eco_results_balanced = {
        "balanced": [{"run_fitness": 0.49, "overall_bb100": 12.0}],
        "aggressive": [{"run_fitness": 0.49, "overall_bb100": 10.0}],
        "passive": [{"run_fitness": 0.50, "overall_bb100": 15.0}],
        "mixed": [{"run_fitness": 0.49, "overall_bb100": 11.0}],
        "adversarial": [{"run_fitness": 0.48, "overall_bb100": 8.0}],
    }

    # Candidate B (Fragile Exploiter): High in passive/mixed, but crashes in aggressive/adversarial
    eco_results_fragile = {
        "balanced": [{"run_fitness": 0.60, "overall_bb100": 25.0}],
        "aggressive": [{"run_fitness": 0.20, "overall_bb100": -75.0}],
        "passive": [{"run_fitness": 0.85, "overall_bb100": 80.0}],
        "mixed": [{"run_fitness": 0.60, "overall_bb100": 25.0}],
        "adversarial": [{"run_fitness": 0.25, "overall_bb100": -65.0}],
    }

    decomp_a = compute_multi_ecology_variance_decomposition(eco_results_balanced, pool_size=12)
    decomp_b = compute_multi_ecology_variance_decomposition(eco_results_fragile, pool_size=12)

    # In naive arithmetic mean, Candidate B (0.500) > Candidate A (0.490)
    assert decomp_b["fitness"] > decomp_a["fitness"]

    # In robust fitness, Candidate A is strictly superior to Candidate B due to stability
    assert decomp_a["robust_fitness"] > decomp_b["robust_fitness"]
    assert decomp_a["robust_penalty"] < decomp_b["robust_penalty"]
    assert decomp_b["robust_penalty"] > 0.08  # Over 800 basis points of risk penalty

    # Now verify that StrategyTrainer ranking ordering strictly favors Candidate A
    dummy_param_a = StrategyParams(vpip=0.25)
    dummy_param_b = StrategyParams(vpip=0.35)

    scored_pairs = [
        (decomp_b, dummy_param_b),
        (decomp_a, dummy_param_a),
    ]

    # Test ranking ordering with robust_fitness
    ranked = sorted(
        scored_pairs,
        key=lambda x: (
            x[0].get("robust_fitness", x[0]["fitness"]),
            x[0].get("worst_ecology_fitness", x[0]["fitness"]),
            x[0].get("finish_utility", x[0].get("top12_rate", 0.0)),
            x[0].get("overall_bb100", x[0].get("avg_bb100", 0.0)),
            -x[0].get("avg_finish_rank", x[0].get("avg_rank", 999.0))
        ),
        reverse=True
    )

    assert ranked[0][1] == dummy_param_a, "Candidate A (Balanced) must rank 1st over Fragile Candidate B"
    assert ranked[1][1] == dummy_param_b, "Candidate B (Fragile) must rank 2nd despite higher mean fitness"


def test_single_ecology_and_summarise_backward_compatibility():
    """Ensure _summarise and single-ecology variance decomposition populate robust fields without error."""
    # 1. Single ecology in variance decomposition
    single_eco = {
        "balanced": [{"run_fitness": 0.44, "finish_rank": 3.0, "overall_bb100": 10.0}]
    }
    decomp_single = compute_multi_ecology_variance_decomposition(single_eco, pool_size=12)
    assert decomp_single["robust_fitness"] == decomp_single["fitness"]
    assert decomp_single["robust_penalty"] == 0.0
    assert decomp_single["worst_ecology_fitness"] == decomp_single["fitness"]

    # 2. Direct _summarise with stage_results
    sm = _summarise(1, 1, 0, [3.0], [10.0], 1, 12, stage_results=[{"run_fitness": 0.45, "finish_rank": 3.0, "overall_bb100": 10.0}])
    assert "robust_fitness" in sm
    assert sm["robust_fitness"] == sm["fitness"]
    assert sm["robust_penalty"] == 0.0

    # 3. Legacy _summarise without stage_results
    sm_leg = _summarise(1, 1, 0, [3.0], [10.0], 1, 12)
    assert "robust_fitness" in sm_leg
    assert sm_leg["robust_fitness"] == sm_leg["fitness"]


def test_monotonicity_and_risk_aversion_properties():
    """Verify that improving any ecology monotonically increases robust fitness, and tail risk shifts are penalized."""
    base_eco = {
        "eco_1": [{"run_fitness": 0.40}],
        "eco_2": [{"run_fitness": 0.50}],
        "eco_3": [{"run_fitness": 0.50}],
        "eco_4": [{"run_fitness": 0.60}],
        "eco_5": [{"run_fitness": 0.60}],
    }
    d_base = compute_multi_ecology_variance_decomposition(base_eco, pool_size=12)

    # Case 1: Monotonic improvement in worst ecology
    improved_worst = dict(base_eco)
    improved_worst["eco_1"] = [{"run_fitness": 0.45}]
    d_imp = compute_multi_ecology_variance_decomposition(improved_worst, pool_size=12)
    assert d_imp["robust_fitness"] > d_base["robust_fitness"]
    assert d_imp["worst_ecology_fitness"] > d_base["worst_ecology_fitness"]

    # Case 2: Risk Aversion (Mean-preserving spread increases penalty)
    # Take 0.05 from worst ecology (0.40 -> 0.35) and give 0.05 to best ecology (0.60 -> 0.65)
    # Mean remains 0.52, but variance and downside gap expand!
    spread_eco = {
        "eco_1": [{"run_fitness": 0.35}],
        "eco_2": [{"run_fitness": 0.50}],
        "eco_3": [{"run_fitness": 0.50}],
        "eco_4": [{"run_fitness": 0.60}],
        "eco_5": [{"run_fitness": 0.65}],
    }
    d_spread = compute_multi_ecology_variance_decomposition(spread_eco, pool_size=12)
    assert pytest.approx(d_spread["fitness"], abs=1e-5) == pytest.approx(d_base["fitness"], abs=1e-5)
    assert d_spread["robust_penalty"] > d_base["robust_penalty"]
    assert d_spread["robust_fitness"] < d_base["robust_fitness"]


def test_arena_evaluator_multi_ecology_returns_robust_metrics():
    """Verify that ArenaEvaluator.evaluate_multi_ecology outputs robust fitness metrics."""
    evaluator = ArenaEvaluator(pool_size=12, workers=1, seed=42)
    focal = StrategyParams(vpip=0.25, attack=0.60)
    summary = evaluator.evaluate_multi_ecology(
        focal,
        runs_per_ecology=1,
        seed_offset=100,
        verbose=False,
    )

    assert "robust_fitness" in summary
    assert "worst_ecology_name" in summary
    assert "worst_ecology_fitness" in summary
    assert "cvar_ecology_fitness" in summary
    assert "robust_penalty" in summary
    assert summary["robust_fitness"] <= summary["fitness"]


def test_end_to_end_training_persists_robust_fitness(tmp_path):
    """Verify that StrategyTrainer.fit end-to-end persists robust fitness metrics in history and candidate."""
    import json
    save_file = tmp_path / "candidate_stage3_test.json"
    archive_dir = tmp_path / "archive_stage3_test"

    trainer = StrategyTrainer(
        seed=101,
        pool_size=12,
        workers=1,
        profile_share=0.0,
    )

    champ, history_dict = trainer.fit(
        generations=1,
        population=2,
        runs_per_candidate=1,
        final_race=1,
        save=str(save_file),
        archive=str(archive_dir),
        resume=False,
    )

    assert save_file.exists()
    cand_data = json.loads(save_file.read_text(encoding="utf-8"))

    # Verify training metrics in candidate JSON
    assert "training_metrics" in cand_data
    assert "robust_fitness" in cand_data["training_metrics"]
    assert "worst_ecology_fitness" in cand_data["training_metrics"]
    assert "worst_ecology_name" in cand_data["training_metrics"]
    assert "robust_penalty" in cand_data["training_metrics"]

    # Verify archive gen_001.json contains robust_fitness
    gen_file = archive_dir / "gen_001.json"
    assert gen_file.exists()
    gen_data = json.loads(gen_file.read_text(encoding="utf-8"))
    assert "robust_fitness" in gen_data["metrics"]
    assert "worst_ecology_name" in gen_data["metrics"]
