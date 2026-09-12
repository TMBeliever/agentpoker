import pytest
from dataclasses import asdict

from agentpoker.ecosystem import (
    PyramidRatios,
    classify_profile_dict,
    build_ecosystem_pool,
    build_120_pyramid_field,
    SHARK_ARCHETYPES,
    REGULAR_ARCHETYPES,
    FISH_ARCHETYPES,
)
from agentpoker.battle import ArenaBattle, CompetitorCandidate
from agentpoker.strategy import StrategyParams


def test_pyramid_ratios_calculation():
    """G4.1: Pyramid ratios compute integer counts that strictly sum to target field."""
    ratios = PyramidRatios(0.30, 0.40, 0.30)

    # 120 players (Standard official field)
    s120, r120, f120 = ratios.compute_counts(120)
    assert s120 == 36
    assert r120 == 48
    assert f120 == 36
    assert s120 + r120 + f120 == 120

    # 36 players (Research field)
    s36, r36, f36 = ratios.compute_counts(36)
    assert s36 + r36 + f36 == 36

    # 24 players (Smoke field)
    s24, r24, f24 = ratios.compute_counts(24)
    assert s24 + r24 + f24 == 24

    # Property test over arbitrary field sizes
    for n in range(6, 301, 6):
        s, r, f = ratios.compute_counts(n)
        assert s >= 0 and r >= 0 and f >= 0
        assert s + r + f == n


def test_classify_profile_dict():
    """G4.2: Classification categorizes player profiles accurately into 3 tiers."""
    # Calling station fish (high vpip, low pfr)
    station = {"hands": 100, "vpip_count": 45, "pfr_count": 8, "aggression_factor": 0.6}
    assert classify_profile_dict(station) == "fish"

    # Passive fish (high vpip, low aggression)
    passive = {"hands": 50, "vpip_count": 22, "pfr_count": 5, "aggression_factor": 0.8}
    assert classify_profile_dict(passive) == "fish"

    # Aggressive shark (loose aggressive / maniac)
    shark_lag = {"hands": 100, "vpip_count": 32, "pfr_count": 24, "aggression_factor": 2.8}
    assert classify_profile_dict(shark_lag) == "shark"

    # Tight regular (TAG / Nit)
    tag = {"hands": 100, "vpip_count": 20, "pfr_count": 16, "aggression_factor": 1.8}
    assert classify_profile_dict(tag) == "regular"


def test_build_ecosystem_pool_exact_count():
    """G4.3: build_ecosystem_pool returns exact count of requested agents across modes."""
    for count in (12, 24, 36, 120):
        pool = build_ecosystem_pool(count=count, mode="pyramid", profiles_path=None, seed=42)
        assert len(pool) == count
        assert all(isinstance(p, StrategyParams) for p in pool)

    # Sharks mode
    sharks = build_ecosystem_pool(count=20, mode="sharks", profiles_path=None)
    assert len(sharks) == 20

    # Fish mode
    fish = build_ecosystem_pool(count=20, mode="fish", profiles_path=None)
    assert len(fish) == 20


def test_build_120_pyramid_field():
    """G4.4: build_120_pyramid_field generates 120-agent field with valid parameter bounds."""
    field_120 = build_120_pyramid_field(profiles_path=None, seed=123)
    assert len(field_120) == 120

    for p in field_120:
        d = asdict(p)
        assert 0.0 < d["vpip"] < 1.0
        assert 0.0 < d["open_frequency"] < 1.0
        assert 0.0 < d["cbet_frequency"] < 1.0
        assert 0.0 < d["value_threshold"] < 1.0


def test_arena_battle_pyramid_integration():
    """G4.5: ArenaBattle executes with opponent_mode='pyramid' and 24 agents smoke run."""
    c1 = CompetitorCandidate(cid="c1", name="Bot 1", category="archetype", params=StrategyParams(vpip=0.20))
    c2 = CompetitorCandidate(cid="c2", name="Bot 2", category="archetype", params=StrategyParams(vpip=0.30))

    arena = ArenaBattle(
        competitors=[c1, c2],
        opponent_mode="pyramid",
        field_size=24,
        equity_samples=0,
        workers=1,
        seed=77,
    )
    report = arena.run(runs=1, verbose=False)
    assert "leaderboard" in report
    assert len(report["leaderboard"]) == 2
    assert report["runs"] == 1
    assert report["field_size"] == 24
    assert report["opponent_mode"] == "pyramid"
