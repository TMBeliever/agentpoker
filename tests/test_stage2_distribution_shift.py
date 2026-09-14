"""Unit and integration tests for Round 2 Stage 2: Validation/Test Distribution Shift & OOD Stress Testing.

Verifies:
1. Genuine Out-Of-Distribution (OOD) Archetypes:
   - UNSEEN_OOD_ARCHETYPES are strictly excluded from the training environment.
   - Parameter values (e.g. VPIP, open sizing, aggression) explore regions outside standard training bounds.
2. Macro Composition Shift:
   - Validation and Test environments have distinct, shifted tier ratios (not static 30/40/30%).
3. Multi-Dimensional Distribution Shift Audit:
   - compute_distribution_shift_audit calculates TV distance, Wasserstein distance, unseen share, and OOD rate.
   - Self-comparison yields 0.0; Target comparisons yield genuine non-zero shift scores.
4. Dedicated OOD Stress Regimes:
   - sample_pool supports 'extreme_aggression', 'extreme_passivity', and 'unseen_hybrids'.
5. End-to-End Training Integration:
   - fit() saves distribution shift audit records and executes the OOD stress testing suite.
"""
from dataclasses import asdict
import tempfile, shutil
from pathlib import Path
import pytest

from agentpoker.strategy import StrategyParams
from agentpoker.training import (
    StrategyTrainer,
    OpponentEnvironment,
    ARCHETYPES,
    UNSEEN_OOD_ARCHETYPES,
    compute_distribution_shift_audit,
)


def test_unseen_ood_archetypes_defined_and_not_in_train():
    """Verify UNSEEN_OOD_ARCHETYPES are well-defined and absent from train_env."""
    expected_unseen = {"ultra_rock", "hyper_whale", "tricky_trapper", "sticky_floater", "polar_overbetter"}
    assert expected_unseen.issubset(set(UNSEEN_OOD_ARCHETYPES.keys()))

    trainer = StrategyTrainer(seed=42, pool_size=12, workers=1)
    train_archetype_dicts = [asdict(p) for p in trainer.train_env.archetypes]

    # None of the unseen archetypes should exist in train_env.archetypes
    for u_name, u_strat in UNSEEN_OOD_ARCHETYPES.items():
        u_dict = asdict(u_strat)
        assert u_dict not in train_archetype_dicts, f"Unseen archetype {u_name} must NOT be in train_env.archetypes"
    assert len(trainer.train_env.unseen_archetypes) == 0


def test_unseen_parameter_ranges_explored():
    """Verify that UNSEEN_OOD_ARCHETYPES truly explore boundaries beyond standard bounds."""
    # Standard training population VPIP bounds: (0.18, 0.38)
    ultra_rock = UNSEEN_OOD_ARCHETYPES["ultra_rock"]
    assert ultra_rock.vpip <= 0.12, f"Ultra rock VPIP ({ultra_rock.vpip}) should be strictly below standard lower bound (0.18)"
    assert ultra_rock.threebet_frequency <= 0.03, f"Ultra rock 3-bet ({ultra_rock.threebet_frequency}) should be ultra low"

    hyper_whale = UNSEEN_OOD_ARCHETYPES["hyper_whale"]
    assert hyper_whale.vpip >= 0.55, f"Hyper whale VPIP ({hyper_whale.vpip}) should be strictly above standard upper bound (0.38)"
    assert hyper_whale.open_size >= 3.5, f"Hyper whale open size ({hyper_whale.open_size}) should explore extreme oversized open sizing"

    polar = UNSEEN_OOD_ARCHETYPES["polar_overbetter"]
    assert polar.cbet_size >= 0.85, f"Polar overbetter cbet size ({polar.cbet_size}) should exert massive pressure"


def test_macro_composition_shift_between_partitions():
    """Verify that train, validation, and test environments have genuinely shifted tier ratios."""
    trainer = StrategyTrainer(seed=42, pool_size=12, workers=1)

    train_ratios = (trainer.train_env.shark_ratio, trainer.train_env.regular_ratio, trainer.train_env.fish_ratio)
    val_ratios = (trainer.validation_env.shark_ratio, trainer.validation_env.regular_ratio, trainer.validation_env.fish_ratio)
    test_ratios = (trainer.test_env.shark_ratio, trainer.test_env.regular_ratio, trainer.test_env.fish_ratio)

    # Ratios must not all be identical
    assert train_ratios != val_ratios, "Validation ratios must be shifted from train ratios"
    assert train_ratios != test_ratios, "Test ratios must be shifted from train ratios"

    # Validation: shifted towards tough regulars and sharks
    assert trainer.validation_env.shark_ratio > trainer.train_env.shark_ratio
    assert trainer.validation_env.fish_ratio < trainer.train_env.fish_ratio

    # Test: high aggression test field
    assert trainer.test_env.shark_ratio >= 0.45


def test_distribution_shift_audit_metrics_computation():
    """Verify compute_distribution_shift_audit outputs multi-dimensional metrics correctly."""
    trainer = StrategyTrainer(seed=42, pool_size=12, workers=1)

    # 1. Baseline self-comparison must yield zero shift
    self_audit = compute_distribution_shift_audit(trainer.train_env, trainer.train_env, pool_size=12, seed=42)
    assert self_audit["composition_tv_distance"] == 0.0
    assert self_audit["unseen_archetype_share"] == 0.0
    assert self_audit["composite_shift_score"] == 0.0

    # 2. Validation audit must show genuine non-zero shift
    val_audit = trainer.val_distribution_shift
    assert val_audit["composition_tv_distance"] > 0.0
    assert val_audit["composite_shift_score"] >= 0.10
    assert val_audit["is_genuine_shift"] is True
    assert "parameter_shifts" in val_audit
    assert "vpip" in val_audit["parameter_shifts"]

    # 3. Test audit must show heavy OOD shift
    test_audit = trainer.test_distribution_shift
    assert test_audit["composition_tv_distance"] > 0.0
    assert test_audit["unseen_archetype_share"] > 0.15
    assert test_audit["ood_parameter_rate"] > 0.15
    assert test_audit["composite_shift_score"] >= 0.15
    assert test_audit["is_genuine_shift"] is True


def test_sample_pool_with_ood_modes():
    """Verify OpponentEnvironment.sample_pool supports dedicated OOD stress modes."""
    trainer = StrategyTrainer(seed=42, pool_size=12, workers=1)
    test_env = trainer.test_env

    # 1. Extreme aggression mode
    pool_agg = test_env.sample_pool(12, seed=100, ood_mode="extreme_aggression")
    assert len(pool_agg) == 11
    avg_attack_agg = sum(p.attack for p in pool_agg) / len(pool_agg)
    avg_3bet_agg = sum(p.threebet_frequency for p in pool_agg) / len(pool_agg)

    # 2. Extreme passivity mode
    pool_pas = test_env.sample_pool(12, seed=100, ood_mode="extreme_passivity")
    assert len(pool_pas) == 11
    avg_attack_pas = sum(p.attack for p in pool_pas) / len(pool_pas)

    assert avg_attack_agg > avg_attack_pas + 0.15, f"Aggression attack ({avg_attack_agg}) must greatly exceed passivity attack ({avg_attack_pas})"

    # 3. Unseen hybrids mode: draws from unseen archetypes
    pool_hyb = test_env.sample_pool(12, seed=100, ood_mode="unseen_hybrids")
    unseen_dicts = [asdict(u) for u in test_env.unseen_archetypes]
    for p in pool_hyb:
        assert asdict(p) in unseen_dicts, "All opponents in unseen_hybrids mode must be from unseen_archetypes"


def test_end_to_end_validation_and_test_audit_in_fit():
    """Verify that fit() runs the full pipeline with distribution shift audit and OOD stress testing."""
    tmp = Path(tempfile.mkdtemp())
    try:
        trainer = StrategyTrainer(seed=42, pool_size=12, workers=1)
        champ, report = trainer.fit(
            generations=1,
            population=4,
            runs_per_candidate=2,
            final_race=2,
            save=str(tmp / "cand.json"),
            archive=str(tmp / "arc"),
            resume=False,
        )

        # Assert report contains distribution shift audit metrics
        assert "val_distribution_shift" in report
        assert "test_distribution_shift" in report
        assert report["val_distribution_shift"]["composite_shift_score"] > 0.0
        assert report["test_distribution_shift"]["composite_shift_score"] > 0.0

        # Assert report contains OOD stress results
        assert "ood_stress_results" in report["test"]
        stress = report["test"]["ood_stress_results"]
        assert "extreme_aggression" in stress
        assert "extreme_passivity" in stress
        assert "unseen_hybrids" in stress
        for ood_k, ood_v in stress.items():
            assert "fitness" in ood_v
            assert "overall_bb100" in ood_v
    finally:
        shutil.rmtree(tmp)
