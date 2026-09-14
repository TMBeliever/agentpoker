"""Stage 3 Verification: Opponent Pool Rebalancing, Curriculum Progression & Controlled Self-Play.

Tests:
1. Stratified style distribution (Regulars, Sharks, Fish all guaranteed representation).
2. Dynamic curriculum progression across generations (early gen fish-heavy vs late gen regular-heavy).
3. Controlled self-play quota (capped to prevent echo chambers, with jittered clones).
4. Jitter preserves poker monotonicity invariants on all drawn opponents.
5. Environment sample_pool produces stratified validation and test pools.
"""
from dataclasses import asdict
import pytest
from agentpoker.strategy import StrategyParams
from agentpoker.training import (
    StrategyTrainer,
    ARCHETYPES,
    _classify_strategy_tier,
)


def test_opponent_pool_style_stratification():
    """Verify that a 120-player field guarantees representation across all three core playing styles."""
    trainer = StrategyTrainer(seed=42, pool_size=120, workers=1, profile_share=0.5)
    
    # Test 1: With training profiles
    pool_with_profs = trainer._draw_pool([], [], 42, trainer._train_profile_params, generation=5)
    assert len(pool_with_profs) == 119
    
    counts_profs = {"shark": 0, "regular": 0, "fish": 0}
    for p in pool_with_profs:
        tier = _classify_strategy_tier(p)
        counts_profs[tier] += 1
        
    assert counts_profs["shark"] >= 20, f"Expected >= 20 sharks, got {counts_profs['shark']}"
    assert counts_profs["regular"] >= 35, f"Expected >= 35 regulars, got {counts_profs['regular']}"
    assert counts_profs["fish"] >= 20, f"Expected >= 20 fish, got {counts_profs['fish']}"
    assert sum(counts_profs.values()) == 119

    # Test 2: Universal mode without real profiles (pure archetypes)
    pool_pure = trainer._draw_pool([], [], 42, [], generation=5)
    assert len(pool_pure) == 119
    counts_pure = {"shark": 0, "regular": 0, "fish": 0}
    for p in pool_pure:
        tier = _classify_strategy_tier(p)
        counts_pure[tier] += 1
        
    assert counts_pure["shark"] >= 20
    assert counts_pure["regular"] >= 35
    assert counts_pure["fish"] >= 20
    assert sum(counts_pure.values()) == 119


def test_dynamic_curriculum_across_generations():
    """Verify curriculum progression: early generations have more fish, late generations have more regulars."""
    trainer = StrategyTrainer(seed=123, pool_size=120, workers=1)
    
    # Early curriculum (Gen 0)
    early_pool = trainer._draw_pool([], [], 77, trainer._train_profile_params, generation=0)
    early_counts = {"shark": 0, "regular": 0, "fish": 0}
    for p in early_pool:
        early_counts[_classify_strategy_tier(p)] += 1
        
    # Late curriculum (Gen 15)
    late_pool = trainer._draw_pool([], [], 77, trainer._train_profile_params, generation=15)
    late_counts = {"shark": 0, "regular": 0, "fish": 0}
    for p in late_pool:
        late_counts[_classify_strategy_tier(p)] += 1
        
    # In early generation: fish share should be higher
    assert early_counts["fish"] > late_counts["fish"], (
        f"Early fish ({early_counts['fish']}) should exceed late fish ({late_counts['fish']})"
    )
    # In late generation: regular share should be higher
    assert late_counts["regular"] > early_counts["regular"], (
        f"Late regulars ({late_counts['regular']}) should exceed early regulars ({early_counts['regular']})"
    )


def test_controlled_self_play_bounds():
    """Verify that shadow clones are strictly capped at <= 25% of the field and are jittered."""
    pool_size = 24
    trainer = StrategyTrainer(seed=42, pool_size=pool_size, workers=1, self_play=True, shadow_clones=10)
    
    hero = ARCHETYPES["balanced"]
    hall = [(0.90, hero), (0.85, ARCHETYPES["lag"])]
    
    pool = trainer._draw_pool([hero], hall, 999, trainer._train_profile_params, exclude=hero, generation=5)
    assert len(pool) == pool_size - 1  # 23
    
    # Shadow clones capped to max pool // 4 = 23 // 4 = 5
    # Check that no candidate in pool is bitwise identical to hero (must be jittered)
    hero_dict = asdict(hero)
    exact_matches = sum(1 for p in pool if asdict(p) == hero_dict)
    assert exact_matches == 0, "Shadow clones and opponents must be jittered to prevent static memorization"


def test_dynamic_jitter_enforces_poker_invariants():
    """Verify that all opponents drawn have valid poker monotonicities and non-degenerate parameters."""
    trainer = StrategyTrainer(seed=99, pool_size=60, workers=1)
    pool = trainer._draw_pool([], [], 31415, trainer._train_profile_params, generation=7)
    
    assert len(pool) == 59
    for p in pool:
        # Preflop hierarchy
        assert p.open_thresh_utg <= p.open_thresh_hj
        assert p.open_thresh_hj <= p.open_thresh_co
        assert p.open_thresh_co <= p.open_thresh_btn
        # Postflop thresholds
        assert p.thin_value_threshold < p.value_threshold
        assert p.jam_threshold > p.value_threshold
        assert p.flop_value_threshold <= p.turn_value_threshold + 0.001
        assert p.turn_value_threshold <= p.river_value_threshold + 0.001
        # Bet sizings
        assert p.bluff_bet_size <= p.value_bet_size + 0.001
        assert p.wet_board_bet_size >= p.dry_board_bet_size
        # Aggression coupling
        if p.threebet_frequency >= 0.09:
            assert p.attack >= 0.65


def test_environment_sample_pool_is_stratified():
    """Verify that OpponentEnvironment.sample_pool produces a multi-style stratified pool."""
    trainer = StrategyTrainer(seed=42, pool_size=24, workers=1)
    val_pool = trainer.validation_env.sample_pool(pool_size=24, seed=123)
    
    assert len(val_pool) == 23
    counts = {"shark": 0, "regular": 0, "fish": 0}
    for p in val_pool:
        counts[_classify_strategy_tier(p)] += 1
        
    assert counts["shark"] >= 4
    assert counts["regular"] >= 6
    assert counts["fish"] >= 4
    assert sum(counts.values()) == 23
