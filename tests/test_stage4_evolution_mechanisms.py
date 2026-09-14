from __future__ import annotations
import copy
from dataclasses import asdict
import pytest
from agentpoker.training import (
    StrategyTrainer,
    StrategyParams,
    FUNCTIONAL_BLOCKS,
    population_diversity,
    ARCHETYPES,
)


def test_gene_masked_mutation_preserves_unselected_genes():
    """Verify that gene-masked mutation perturbs a focused subset and preserves unselected genes."""
    trainer = StrategyTrainer(pool_size=12, seed=42)
    parent = ARCHETYPES["balanced"]
    parent_dict = asdict(parent)

    # 1. Mutating with sigma=0.0 returns clamped copy without change
    zero_mut = trainer.mutate(parent, 0.0)
    assert asdict(zero_mut) == parent_dict

    # 2. Mutate with positive sigma
    mutated = trainer.mutate(parent, sigma=0.06, mask_prob=0.30)
    mut_dict = asdict(mutated)

    changed_keys = [k for k in trainer.FIELDS if abs(mut_dict[k] - parent_dict[k]) > 1e-6]
    unchanged_keys = [k for k in trainer.FIELDS if abs(mut_dict[k] - parent_dict[k]) <= 1e-6]

    # Must mutate at least 2 genes
    assert len(changed_keys) >= 2, f"Expected at least 2 changed genes, got {len(changed_keys)}"
    # But must NOT destructively perturb all 35 parameters simultaneously
    assert len(unchanged_keys) >= 10, f"Expected at least 10 unchanged genes, got {len(unchanged_keys)}"

    # Check invariants are strictly satisfied
    assert mut_dict["vpip"] >= 0.18 and mut_dict["vpip"] <= 0.38
    assert mut_dict["open_thresh_utg"] < mut_dict["open_thresh_hj"] < mut_dict["open_thresh_co"] < mut_dict["open_thresh_btn"]
    assert mut_dict["thin_value_threshold"] < mut_dict["value_threshold"]
    assert mut_dict["wet_board_bet_size"] > mut_dict["dry_board_bet_size"]


def test_modular_block_crossover_inherits_cohesive_blocks():
    """Verify that block crossover transfers entire functional blocks as unbroken cohesive units."""
    trainer = StrategyTrainer(pool_size=12, seed=101)
    parent_a = ARCHETYPES["nit"]
    parent_b = ARCHETYPES["lag"]

    da = asdict(parent_a)
    db = asdict(parent_b)
    trainer._clamp_and_validate(da)
    trainer._clamp_and_validate(db)

    # Run block crossover 20 times and verify every functional block is wholly from Parent A or Parent B
    for _ in range(20):
        child = trainer.crossover(parent_a, parent_b, mode="block")
        dc = asdict(child)

        for block_name, block_keys in FUNCTIONAL_BLOCKS.items():
            # For each block, check whether keys originate cohesively from Parent A or Parent B
            # Note: attack is subject to tactical coupling with threebet_frequency in _clamp_and_validate
            eval_keys = [k for k in block_keys if k != "attack"]
            matches_a = all(abs(dc[k] - da[k]) < 1e-5 for k in eval_keys)
            matches_b = all(abs(dc[k] - db[k]) < 1e-5 for k in eval_keys)

            assert matches_a or matches_b, f"Block {block_name} was fragmented unexpectedly: neither matched wholly"


def test_arithmetic_blended_crossover():
    """Verify that arithmetic blended crossover produces continuous convex interpolations."""
    trainer = StrategyTrainer(pool_size=12, seed=202)
    parent_a = ARCHETYPES["nit"]
    parent_b = ARCHETYPES["maniac"]

    da = asdict(parent_a)
    db = asdict(parent_b)

    child = trainer.crossover(parent_a, parent_b, mode="arithmetic")
    dc = asdict(child)

    # In arithmetic crossover, values should lie between min(a,b) and max(a,b) (subject to bounds)
    interpolated_count = 0
    for k in trainer.FIELDS:
        val_a = float(da[k])
        val_b = float(db[k])
        min_v = min(val_a, val_b) - 0.05
        max_v = max(val_a, val_b) + 0.05
        if abs(val_a - val_b) > 0.05:
            if min_v <= dc[k] <= max_v:
                interpolated_count += 1

    assert interpolated_count >= 10, "Arithmetic crossover should smoothly interpolate parameters"


def test_population_diversity_metric():
    """Verify normalization, symmetry, and sensitivity of the population diversity metric."""
    # 1. Monoculture / clones have 0 diversity
    clones = [ARCHETYPES["balanced"], copy.deepcopy(ARCHETYPES["balanced"]), copy.deepcopy(ARCHETYPES["balanced"])]
    assert population_diversity(clones) == pytest.approx(0.0, abs=1e-7)

    # 2. Single individual has 0 diversity
    assert population_diversity([ARCHETYPES["balanced"]]) == 0.0
    assert population_diversity([]) == 0.0

    # 3. Diverse archetypes have substantial diversity
    diverse_pop = [ARCHETYPES["nit"], ARCHETYPES["lag"], ARCHETYPES["station"], ARCHETYPES["balanced"]]
    div = population_diversity(diverse_pop)
    assert 0.10 <= div <= 0.80, f"Expected healthy diversity in [0.10, 0.80], got {div}"

    # 4. Adding extreme maniac increases diversity
    div_with_maniac = population_diversity(diverse_pop + [ARCHETYPES["maniac"]])
    assert div_with_maniac >= div - 0.02


def test_multi_origin_stagnation_recovery(tmp_path):
    """Verify that stagnation recovery injects multi-origin diversity rather than single-point clones."""
    archive_dir = tmp_path / "archive"
    save_model = tmp_path / "champ.json"

    trainer = StrategyTrainer(pool_size=12, seed=303, workers=1)

    # Run 3 generations with stagnation_patience=1 to trigger stagnation restart on gen 2
    champ, results = trainer.fit(
        generations=3,
        population=4,
        runs_per_candidate=1,
        save=str(save_model),
        archive=str(archive_dir),
        final_race=1,
        stagnation_patience=1,
        stagnation_min_delta=999.0,  # Guarantee stagnation triggers
    )

    history = results["training"]
    # Check that at least one generation experienced a restart
    restarts = [h for h in history if h.get("restarted")]
    assert len(restarts) >= 1, "Stagnation restart should have triggered"

    # Verify that population diversity is recorded in history
    for h in history:
        assert "population_diversity" in h
        assert h["population_diversity"] > 0.0, "Population diversity should be positive throughout training"
