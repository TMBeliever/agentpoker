"""The fitness number must travel with its own uncertainty.

With a handful of tournament runs per candidate, generation-over-generation fitness
differences of ~0.05 were being read as progress when the sampling noise alone is
several times larger. `_summarise` reports the standard error so that comparison is
possible; these tests pin its behaviour.
"""
import math

from agentpoker.training import _summarise, StrategyTrainer


def test_summarise_reports_uncertainty():
    metrics = _summarise(6, 3, 1, [1, 2, 3, 4, 5, 6], [10.0] * 6, 6, 24)
    assert metrics["runs"] == 6
    assert metrics["top12_rate"] == 1.0
    assert metrics["fitness_se"] > 0
    lo, hi = metrics["fitness_ci95"]
    assert lo < metrics["fitness"] < hi
    assert math.isclose(hi - lo, 2 * 1.96 * metrics["fitness_se"], rel_tol=1e-6)


def test_identical_runs_carry_no_sampling_variance():
    metrics = _summarise(2, 2, 2, [1, 1], [5.0, 5.0], 2, 24)
    assert metrics["fitness_se"] == 0.0


def test_more_runs_shrinks_the_standard_error():
    noisy = _summarise(3, 2, 1, [1, 5, 9, 13, 17, 21], [0.0] * 6, 6, 24)
    calmer = _summarise(24, 16, 8, [1, 5, 9, 13, 17, 21] * 4, [0.0] * 24, 24, 24)
    assert calmer["fitness_se"] < noisy["fitness_se"]


def test_fitness_matches_the_declared_weighting():
    m = _summarise(12, 6, 3, [4.0] * 24, [0.0] * 24, 24, 24)
    expected = .20 * 0.5 + .25 * 0.25 + .45 * 0.125 + .05 * (1 - 3 / 23) + .05 * 0.5
    assert math.isclose(m["fitness"], expected, rel_tol=1e-9)


def test_holdout_and_training_pools_do_not_overlap():
    trainer = StrategyTrainer(seed=7, pool_size=12, workers=1,
                              profiles="models/opponent_profiles.json", holdout_frac=0.25)
    train = {(p.vpip, p.cbet_size, p.attack) for p in trainer._train_profile_params}
    hold = {(p.vpip, p.cbet_size, p.attack) for p in trainer._holdout_profile_params}
    assert train and hold
    assert not (train & hold)


def test_common_random_numbers_give_identical_pools():
    trainer = StrategyTrainer(seed=7, pool_size=12, workers=1)
    a = trainer._draw_pool([], [], 999, trainer._train_profile_params)
    b = trainer._draw_pool([], [], 999, trainer._train_profile_params)
    key = lambda pool: [(p.vpip, p.cbet_frequency, p.temperature) for p in pool]
    assert key(a) == key(b)
    c = trainer._draw_pool([], [], 1000, trainer._train_profile_params)
    assert key(c) != key(a)


def test_holdout_pool_is_never_drawn_from_training_profiles():
    trainer = StrategyTrainer(seed=7, pool_size=12, workers=1,
                              profiles="models/opponent_profiles.json", holdout_frac=0.25)
    hold = {(p.vpip, p.cbet_size) for p in trainer._holdout_pool()}
    train = {(p.vpip, p.cbet_size) for p in trainer._train_profile_params}
    assert not (hold & train)
