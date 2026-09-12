import pytest
from agentpoker.context import TableStrengthModel
from agentpoker.tournament import LeagueSimulator, SimAgent
from agentpoker.strategy import StrategyAgent, StrategyParams
from agentpoker.config import TournamentConfig

def test_hero_invariance():
    """Hero's own win rate, archetype, or stats MUST NEVER affect their own perceived table strength."""
    hero_id = "hero"
    opponents = ["opp1", "opp2", "opp3", "opp4", "opp5"]
    group = [hero_id] + opponents

    profiles = {
        "opp1": {"hands": 50, "bb_100": 15.0, "archetype": "tag", "vpip": 0.22, "pfr": 0.18, "af": 2.5},
        "opp2": {"hands": 50, "bb_100": -20.0, "archetype": "station", "vpip": 0.45, "pfr": 0.08, "af": 0.6},
        "opp3": {"hands": 50, "bb_100": 5.0, "archetype": "nit", "vpip": 0.14, "pfr": 0.12, "af": 1.8},
        "opp4": {"hands": 50, "bb_100": -10.0, "archetype": "fish", "vpip": 0.38, "pfr": 0.10, "af": 0.8},
        "opp5": {"hands": 50, "bb_100": 25.0, "archetype": "lag", "vpip": 0.28, "pfr": 0.24, "af": 3.0},
        hero_id: {"hands": 100, "bb_100": -80.0, "archetype": "fish", "vpip": 0.50, "pfr": 0.05, "af": 0.4},
    }

    ts_hero_1 = TableStrengthModel.compute(group, hero_id=hero_id, profiles=profiles)

    # Modify Hero's profile drastically: make Hero a god-tier LAG crusher
    profiles[hero_id] = {"hands": 500, "bb_100": 80.0, "archetype": "crusher", "vpip": 0.24, "pfr": 0.22, "af": 3.5}
    ts_hero_2 = TableStrengthModel.compute(group, hero_id=hero_id, profiles=profiles)

    # Hero's perceived table strength must be exactly identical
    assert ts_hero_1 == ts_hero_2, f"Hero self-leak detected: {ts_hero_1} != {ts_hero_2}"

    # Also test via compute_table_strength_map
    map_1 = TableStrengthModel.compute_table_strength_map(group, profiles)
    profiles[hero_id] = {"hands": 10, "bb_100": 0.0, "archetype": "unknown", "vpip": 0.25, "pfr": 0.18, "af": 1.5}
    map_2 = TableStrengthModel.compute_table_strength_map(group, profiles)

    assert map_1[hero_id] == map_2[hero_id], "Hero perceived strength changed in table strength map!"
    # But opponents' perceived strength MUST change, because Hero is their opponent!
    assert map_1["opp1"] != map_2["opp1"], "Opponent perceived strength did not update when Hero changed!"


def test_fish_table_strength():
    """A table filled with passive calling stations must output strongly negative table strength <= -0.80."""
    hero_id = "hero"
    group = [hero_id, "fish1", "fish2", "fish3", "fish4", "fish5"]
    profiles = {
        f"fish{i}": {
            "hands": 100,
            "bb_100": -35.0,
            "archetype": "station",
            "vpip": 0.50,
            "pfr": 0.06,
            "af": 0.5,
        }
        for i in range(1, 6)
    }
    ts = TableStrengthModel.compute(group, hero_id=hero_id, profiles=profiles)
    assert ts <= -0.80, f"Expected fish table strength <= -0.80, got {ts}"


def test_shark_table_strength():
    """A table filled with aggressive winning regulars must output strongly positive table strength >= +0.70."""
    hero_id = "hero"
    group = [hero_id, "shark1", "shark2", "shark3", "shark4", "shark5"]
    profiles = {
        f"shark{i}": {
            "hands": 100,
            "bb_100": 35.0,
            "archetype": "tag",
            "vpip": 0.22,
            "pfr": 0.19,
            "af": 2.8,
        }
        for i in range(1, 6)
    }
    ts = TableStrengthModel.compute(group, hero_id=hero_id, profiles=profiles)
    assert ts >= +0.70, f"Expected shark table strength >= +0.70, got {ts}"


def test_empty_zero_sample_bayesian_regression():
    """With 0 hands / unknown opponents, table strength regresses strictly to 0.0."""
    hero_id = "hero"
    group = [hero_id, "u1", "u2", "u3", "u4", "u5"]
    profiles = {
        f"u{i}": {
            "hands": 0,
            "bb_100": 0.0,
            "archetype": "unknown",
        }
        for i in range(1, 6)
    }
    ts = TableStrengthModel.compute(group, hero_id=hero_id, profiles=profiles)
    assert ts == 0.0, f"Expected 0.0 regression for zero-sample opponents, got {ts}"

    # Empty profiles dict also regresses to 0.0
    ts_empty = TableStrengthModel.compute(group, hero_id=hero_id, profiles={})
    assert ts_empty == 0.0, f"Expected 0.0 for empty profiles, got {ts_empty}"


def test_tournament_table_strength_integration():
    """Simulate a mini tournament and check that table_strength is populated and in [-1.0, 1.0]."""
    agents = [
        SimAgent(f"p{i}", StrategyAgent(StrategyParams(), seed=i))
        for i in range(12)
    ]
    cfg = TournamentConfig(
        field_size=12,
        preliminary_rounds=2,
        hands_per_round=5,
        semifinal_qualifiers=12,
        semifinal_tables=2,
        semifinal_hands=5,
        final_hands=5,
    )
    sim = LeagueSimulator(agents, config=cfg, seed=42)
    res = sim.run_event()

    assert len(res["preliminary"]) == 12
    assert len(res["qualified"]) == 12
    assert len(res["final"]) == 6
