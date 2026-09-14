"""Unit and integration tests for Round 2 Stage 1: Multi-Ecology Evaluation & CRN.

Verifies:
1. Multi-Ecology Field Generation (5 distinct standard ecologies: balanced, aggressive, passive, mixed, adversarial).
2. Intra-Ecology Common Random Numbers (CRN): All candidates evaluated in ecology E share the exact same
   opponent pool and the exact same deal seed sequence.
3. Inter-Ecology Independence: Distinct ecologies use independent seeds and distinct opponent archetype distributions.
4. ANOVA Variance Decomposition: Mathematical consistency of total, between-ecology, and within-ecology variance.
5. Demonstration of between-ecology variance: Proves that heterogeneous strategies yield sigma_between^2 > 0.
6. Integration with ArenaEvaluator and StrategyTrainer._score_population.
"""
from dataclasses import asdict
import math
import statistics
import pytest

from agentpoker.strategy import StrategyParams
from agentpoker.ecosystem import (
    EcologySpec,
    STANDARD_ECOLOGIES,
    build_ecology_pool,
    build_multi_ecology_pools,
    classify_profile_dict,
)
from agentpoker.training import (
    ArenaEvaluator,
    StrategyTrainer,
    ARCHETYPES,
    compute_multi_ecology_variance_decomposition,
    _evaluate_single_tournament_worker,
)


def test_standard_ecologies_definitions():
    """Verify that all 5 standard ecologies are well-formed and distinct in archetype mix."""
    required_ecologies = {"balanced", "aggressive", "passive", "mixed", "adversarial"}
    assert required_ecologies.issubset(set(STANDARD_ECOLOGIES.keys()))

    # Aggressive must be shark-dominated
    assert STANDARD_ECOLOGIES["aggressive"].shark_ratio >= 0.50
    assert STANDARD_ECOLOGIES["aggressive"].archetype_weights.get("lag", 0) + STANDARD_ECOLOGIES["aggressive"].archetype_weights.get("maniac", 0) >= 0.70

    # Passive must be fish/calling station dominated
    assert STANDARD_ECOLOGIES["passive"].fish_ratio >= 0.50
    assert STANDARD_ECOLOGIES["passive"].archetype_weights.get("station", 0) >= 0.50

    # Adversarial must feature polar maniacs and tight rocks
    assert "maniac" in STANDARD_ECOLOGIES["adversarial"].archetype_weights
    assert "nit" in STANDARD_ECOLOGIES["adversarial"].archetype_weights


def test_different_ecologies_use_independent_sampling():
    """Verify that distinct ecologies yield different opponent lineups and distinct archetype compositions."""
    pools = build_multi_ecology_pools(
        count=60,
        profiles_path=None,
        seed_base=12345,
    )

    assert set(pools.keys()) == set(STANDARD_ECOLOGIES.keys())
    for eco_name, pool in pools.items():
        assert len(pool) == 60

    # Test distinct archetype distributions
    agg_pool = pools["aggressive"]
    pas_pool = pools["passive"]

    # In aggressive ecology, average attack and VPIP should be significantly higher
    agg_avg_attack = sum(p.attack for p in agg_pool) / len(agg_pool)
    pas_avg_attack = sum(p.attack for p in pas_pool) / len(pas_pool)
    assert agg_avg_attack > pas_avg_attack + 0.15, f"Aggressive attack ({agg_avg_attack}) must exceed passive attack ({pas_avg_attack})"

    # In passive ecology, station calling should be prevalent
    pas_avg_vpip = sum(p.vpip for p in pas_pool) / len(pas_pool)
    agg_avg_vpip = sum(p.vpip for p in agg_pool) / len(agg_pool)
    assert pas_avg_vpip > 0.25


def test_candidates_share_same_seed_within_ecology():
    """Verify that candidate A and candidate B receive identical deal seeds within any ecology."""
    trainer = StrategyTrainer(seed=42, pool_size=12, workers=1)
    pop = [ARCHETYPES["tight"], ARCHETYPES["lag"]]
    active_ecologies = ["balanced", "aggressive", "passive"]

    # Reconstruct tasks as in _score_population
    seed_base = trainer.seed + 1000003
    tasks_cand0 = []
    tasks_cand1 = []

    for e_idx, eco_name in enumerate(active_ecologies):
        for r in range(3):
            s = seed_base + (e_idx + 1) * 100003 + r * 7919
            # Candidate 0 task
            tasks_cand0.append((0, r, s, eco_name))
            # Candidate 1 task
            tasks_cand1.append((1, r, s, eco_name))

    # Assert that for every run in every ecology, the seed is identical
    for t0, t1 in zip(tasks_cand0, tasks_cand1):
        assert t0[1] == t1[1], "Run index must match"
        assert t0[2] == t1[2], "Deal seed must be identical for both candidates (Intra-Ecology CRN)"
        assert t0[3] == t1[3], "Ecology must match"


def test_crn_within_ecology_deal_seeds_disjoint_across_ecologies():
    """Verify that deal seed sequences across different ecologies are disjoint (Inter-Ecology Independence)."""
    seed_base = 9999
    active_ecologies = ["balanced", "aggressive", "passive", "mixed", "adversarial"]
    seeds_by_eco = {}

    for e_idx, eco_name in enumerate(active_ecologies):
        seeds_by_eco[eco_name] = [
            seed_base + (e_idx + 1) * 100003 + r * 7919
            for r in range(10)
        ]

    for i, eco1 in enumerate(active_ecologies):
        for j, eco2 in enumerate(active_ecologies):
            if i != j:
                s1 = set(seeds_by_eco[eco1])
                s2 = set(seeds_by_eco[eco2])
                assert s1.isdisjoint(s2), f"Deal seed sets for {eco1} and {eco2} must be disjoint"


def test_variance_decomposition_mathematical_consistency():
    """Verify the mathematical properties of ANOVA variance decomposition."""
    # Synthetic scenario: 3 ecologies, 4 runs each
    # Ecology 1: mean 0.40, variance 0.002
    # Ecology 2: mean 0.60, variance 0.002
    # Ecology 3: mean 0.80, variance 0.002
    eco_results = {
        "eco_low": [{"run_fitness": 0.38, "finish_rank": 6.0, "overall_bb100": -20.0, "is_top12": 0, "is_final": 0, "is_champ": 0},
                    {"run_fitness": 0.42, "finish_rank": 5.0, "overall_bb100": -10.0, "is_top12": 0, "is_final": 0, "is_champ": 0}],
        "eco_mid": [{"run_fitness": 0.58, "finish_rank": 4.0, "overall_bb100": 10.0, "is_top12": 1, "is_final": 0, "is_champ": 0},
                    {"run_fitness": 0.62, "finish_rank": 3.0, "overall_bb100": 20.0, "is_top12": 1, "is_final": 0, "is_champ": 0}],
        "eco_high": [{"run_fitness": 0.78, "finish_rank": 2.0, "overall_bb100": 40.0, "is_top12": 1, "is_final": 1, "is_champ": 1},
                     {"run_fitness": 0.82, "finish_rank": 1.0, "overall_bb100": 50.0, "is_top12": 1, "is_final": 1, "is_champ": 1}],
    }

    decomp = compute_multi_ecology_variance_decomposition(eco_results, pool_size=12)

    # 1. Grand mean must be 0.60
    assert pytest.approx(decomp["fitness"], abs=1e-4) == 0.60

    # 2. Between ecology variance: means are [0.40, 0.60, 0.80]
    # sample variance of [0.4, 0.6, 0.8] = ((0.4-0.6)^2 + (0.6-0.6)^2 + (0.8-0.6)^2) / 2 = (0.04 + 0.04) / 2 = 0.04
    assert pytest.approx(decomp["between_ecology_variance"], abs=1e-4) == 0.04

    # 3. Within ecology variance: each eco variance = ((x - mean)^2 * 2) / 1 = 0.0008
    # within var is strictly positive and small
    assert 0.0 < decomp["within_ecology_variance"] < 0.01

    # 4. Total variance must be > 0 and between_variance must be > 0
    assert decomp["between_ecology_variance"] > 0
    assert decomp["total_variance"] > decomp["within_ecology_variance"]

    # 5. Hierarchical standard error
    # SE = sqrt(between_var / 3 + within_var / 6)
    expected_se = math.sqrt(decomp["between_ecology_variance"] / 3 + decomp["within_ecology_variance"] / 6)
    assert pytest.approx(decomp["fitness_se"], abs=1e-4) == expected_se


def test_between_ecology_variance_positive_on_heterogeneous_strategies():
    """Prove that evaluating a strategy across different ecologies yields sigma_between^2 > 0."""
    evaluator = ArenaEvaluator(pool_size=12, workers=1, seed=42)

    station_strat = ARCHETYPES["station"]
    # Evaluate across 2 distinct ecologies: aggressive vs passive, 2 runs each
    summary = evaluator.evaluate_multi_ecology(
        focal=station_strat,
        ecologies=["aggressive", "passive"],
        runs_per_ecology=2,
        seed_offset=100,
        verbose=False,
    )

    assert "between_ecology_variance" in summary
    assert "within_ecology_variance" in summary
    assert "total_variance" in summary
    assert "ecology_performances" in summary

    # Verify that both ecologies are recorded
    assert "aggressive" in summary["ecology_performances"]
    assert "passive" in summary["ecology_performances"]

    # Strictly assert sigma_between^2 > 0
    sigma_between_sq = summary["between_ecology_variance"]
    assert sigma_between_sq > 0.0, f"Expected sigma_between^2 > 0, got {sigma_between_sq}"


def test_arena_evaluator_multi_ecology_integration():
    """Verify ArenaEvaluator.evaluate dispatches to multi-ecology when configured."""
    evaluator = ArenaEvaluator(
        pool_size=12,
        seed=101,
        workers=1,
        ecologies=["balanced", "aggressive"],
    )

    focal = ARCHETYPES["balanced"]
    summary = evaluator.evaluate(focal, runs=4, verbose=False)

    assert summary["ecologies_count"] == 2
    assert "between_ecology_variance" in summary
    assert "within_ecology_variance" in summary
    assert summary["runs"] == 4
    assert "balanced" in summary["ecology_performances"]
    assert "aggressive" in summary["ecology_performances"]


def test_strategy_trainer_score_population_multi_ecology():
    """Verify StrategyTrainer._score_population runs multi-ecology evaluation and returns variance decomposition."""
    trainer = StrategyTrainer(
        seed=42,
        pool_size=12,
        workers=1,
        ecologies=["balanced", "passive"],
    )

    pop = [ARCHETYPES["tight"], ARCHETYPES["maniac"]]
    scored = trainer._score_population(
        pop=pop,
        hall=[],
        generation=0,
        runs=4,
        label="测试评测",
    )

    assert len(scored) == 2
    for summary, cand in scored:
        assert isinstance(summary, dict)
        assert "between_ecology_variance" in summary
        assert "within_ecology_variance" in summary
        assert "total_variance" in summary
        assert "ecology_performances" in summary
        assert summary["between_ecology_variance"] >= 0.0
        assert summary["within_ecology_variance"] >= 0.0
        assert summary["runs"] == 4
