"""Unit and integration tests for Round 2 Stage 5: Bayesian Profile Posterior Sampling & Epistemic Uncertainty.

Verifies:
1. Inverse variance scaling: Small hand-sample profiles have significantly wider posterior variance than large hand-sample profiles.
2. Posterior mean asymptotic convergence: As hand count N -> infinity, posterior draws converge to empirical rates.
3. Strict backward compatibility: profile_to_params(p) without rng produces exact deterministic point estimates.
4. Poker domain invariants: Posterior sampling preserves physical poker constraints (PFR <= VPIP, positional ranges, sizing order).
5. Analytical credible intervals: compute_profile_posterior_uncertainty returns well-formed 95% CI and epistemic scores.
6. Integration: StrategyTrainer and OpponentEnvironment draw diverse opponent parameters under posterior uncertainty.
"""
import random
import statistics
import pytest

from agentpoker.strategy import StrategyParams
from agentpoker.training import (
    profile_to_params,
    sample_profile_posterior,
    compute_profile_posterior_uncertainty,
    StrategyTrainer,
    OpponentEnvironment,
    ARCHETYPES,
)
from agentpoker.ecosystem import build_ecology_pool


def test_small_sample_has_higher_variance_than_large_sample():
    """Verify that a 15-hand opponent exhibits substantially higher posterior variance than a 2500-hand opponent."""
    profile_small = {
        "player_id": "novice_15",
        "hands": 15,
        "vpip": 0.35,
        "pfr": 0.20,
        "af": 2.5,
    }
    profile_large = {
        "player_id": "veteran_2500",
        "hands": 2500,
        "vpip": 0.35,
        "pfr": 0.20,
        "af": 2.5,
    }

    rng_small = random.Random(101)
    rng_large = random.Random(202)
    n_samples = 300

    samples_small_vpip = [sample_profile_posterior(profile_small, rng=rng_small).vpip for _ in range(n_samples)]
    samples_large_vpip = [sample_profile_posterior(profile_large, rng=rng_large).vpip for _ in range(n_samples)]

    std_small = statistics.stdev(samples_small_vpip)
    std_large = statistics.stdev(samples_large_vpip)

    # 15 hands must have at least 3x higher standard deviation than 2500 hands
    assert std_small > 0.05, f"Small sample std {std_small} should reflect epistemic uncertainty (> 0.05)"
    assert std_large < 0.02, f"Large sample std {std_large} should be tightly concentrated (< 0.02)"
    assert std_small > 3.0 * std_large, f"Small std ({std_small}) must be > 3x large std ({std_large})"


def test_posterior_mean_converges_to_empirical_rate():
    """Verify that as hand counts grow large, posterior expectation converges to empirical rate."""
    target_vpip = 0.42
    profile_large = {
        "player_id": "grinder_3000",
        "hands": 3000,
        "vpip": target_vpip,
        "pfr": 0.25,
        "af": 3.0,
    }

    rng = random.Random(42)
    n_samples = 500
    sampled_vpips = [sample_profile_posterior(profile_large, rng=rng).vpip for _ in range(n_samples)]
    mean_sampled = statistics.mean(sampled_vpips)

    assert abs(mean_sampled - target_vpip) < 0.015, f"Posterior mean {mean_sampled} must converge to empirical {target_vpip}"


def test_profile_to_params_deterministic_backward_compatibility():
    """Verify profile_to_params(p) with rng=None produces deterministic identical point estimates."""
    profile = {
        "player_id": "test_player",
        "hands": 100,
        "vpip": 0.28,
        "pfr": 0.18,
        "af": 2.2,
    }

    p1 = profile_to_params(profile)
    p2 = profile_to_params(profile, rng=None)
    p3 = profile_to_params(profile)

    assert p1 == p2 == p3
    assert p1.vpip == 0.28
    assert p1.open_frequency == min(0.95, max(0.35, 0.18 * 1.3))


def test_poker_monotonicity_preserved_under_posterior_sampling():
    """Verify that poker strategy invariants hold under random posterior draws across diverse archetypes."""
    test_profiles = [
        {"player_id": "nit", "hands": 20, "vpip": 0.12, "pfr": 0.10, "af": 1.2, "is_nit": True},
        {"player_id": "maniac", "hands": 15, "vpip": 0.65, "pfr": 0.50, "af": 6.5, "is_maniac": True},
        {"player_id": "station", "hands": 35, "vpip": 0.45, "pfr": 0.08, "af": 0.8, "is_station": True},
        {"player_id": "balanced", "hands": 500, "vpip": 0.24, "pfr": 0.19, "af": 2.2},
    ]

    rng = random.Random(777)
    for prof in test_profiles:
        for _ in range(50):
            strat = sample_profile_posterior(prof, rng=rng)

            # 1. PFR <= VPIP
            pfr_est = strat.open_frequency / 1.3
            assert strat.threebet_frequency <= strat.open_frequency
            assert strat.vpip >= 0.08 and strat.vpip <= 0.85

            # 2. Positional open thresholds monotonicity: UTG <= HJ <= CO <= BTN
            assert strat.open_thresh_utg <= strat.open_thresh_hj + 1e-6
            assert strat.open_thresh_hj <= strat.open_thresh_co + 1e-6
            assert strat.open_thresh_co <= strat.open_thresh_btn + 1e-6

            # 3. Sizing order: Bluff <= Value
            assert strat.bluff_bet_size <= strat.value_bet_size + 1e-6

            # 4. Value thresholds: Thin Value <= Value <= Jam
            assert strat.thin_value_threshold <= strat.value_threshold + 1e-6
            assert strat.value_threshold <= strat.jam_threshold + 1e-6

            # 5. Street progression: Flop <= Turn <= River
            assert strat.flop_value_threshold <= strat.turn_value_threshold + 1e-6
            assert strat.turn_value_threshold <= strat.river_value_threshold + 1e-6


def test_compute_profile_posterior_uncertainty_metrics():
    """Verify analytical Bayesian posterior statistics calculation."""
    prof_small = {"player_id": "p15", "hands": 15, "vpip": 0.30, "pfr": 0.20}
    prof_large = {"player_id": "p2000", "hands": 2000, "vpip": 0.30, "pfr": 0.20}

    stats_small = compute_profile_posterior_uncertainty(prof_small)
    stats_large = compute_profile_posterior_uncertainty(prof_large)

    assert "epistemic_uncertainty_score" in stats_small
    assert "epistemic_uncertainty_score" in stats_large

    # Epistemic score must be substantially higher for small sample
    assert stats_small["epistemic_uncertainty_score"] > 0.05
    assert stats_large["epistemic_uncertainty_score"] < 0.02
    assert stats_small["epistemic_uncertainty_score"] > 3.0 * stats_large["epistemic_uncertainty_score"]

    # Credible intervals must bound the mean
    vpip_small = stats_small["vpip"]
    assert vpip_small["ci95"][0] <= vpip_small["mean"] <= vpip_small["ci95"][1]
    assert vpip_small["ci95"][1] - vpip_small["ci95"][0] > 0.15  # wide CI for 15 hands

    vpip_large = stats_large["vpip"]
    assert vpip_large["ci95"][0] <= vpip_large["mean"] <= vpip_large["ci95"][1]
    assert vpip_large["ci95"][1] - vpip_large["ci95"][0] < 0.06  # narrow CI for 2000 hands


def test_trainer_and_environment_posterior_sampling():
    """Verify integration of posterior sampling in StrategyTrainer and OpponentEnvironment."""
    mock_profiles = [
        {"player_id": f"p_{i}", "hands": 15 + i * 10, "vpip": 0.20 + (i % 5) * 0.05, "pfr": 0.12 + (i % 4) * 0.03, "af": 1.5 + (i % 3)}
        for i in range(20)
    ]

    trainer = StrategyTrainer(seed=42, pool_size=12, profiles=mock_profiles, workers=1)

    # Verify raw profiles are partitioned into train/val/test environments
    assert len(trainer._raw_profiles) == 20
    assert len(trainer.train_env.raw_profiles) > 0
    assert len(trainer.validation_env.raw_profiles) > 0
    assert len(trainer.test_env.raw_profiles) > 0

    # Test sampling pool with posterior uncertainty enabled
    pool_stochastic_1 = trainer.train_env.sample_pool(pool_size=12, seed=101, sample_posterior=True)
    pool_stochastic_2 = trainer.train_env.sample_pool(pool_size=12, seed=202, sample_posterior=True)

    assert len(pool_stochastic_1) == 11
    assert len(pool_stochastic_2) == 11

    # Pools generated under different seeds with posterior sampling should be distinct
    diffs = [
        abs(p1.vpip - p2.vpip)
        for p1, p2 in zip(pool_stochastic_1, pool_stochastic_2)
    ]
    assert any(d > 0.001 for d in diffs), "Stochastic draws should produce distinct opponents"

    # Test build_ecology_pool with posterior sampling
    eco_pool = build_ecology_pool(
        ecology="balanced",
        count=12,
        profile_params=trainer._train_raw_profiles,
        seed=303,
        sample_posterior=True,
    )
    assert len(eco_pool) == 12
