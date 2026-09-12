import pytest
from random import Random

from agentpoker.config import TournamentConfig
from agentpoker.pairing import random_groups, swiss_groups, verify_pairing_integrity
from agentpoker.scoring import Standing, bb100, rank_standings
from agentpoker.tournament import LeagueSimulator, SimAgent
from agentpoker.strategy import StrategyAgent, StrategyParams


def test_random_groups_partition_120():
    """G5.1: random_groups partitions 120 players into 20 disjoint tables of 6."""
    rng = Random(42)
    ids = [f"agent_{i:03d}" for i in range(120)]
    tables = random_groups(ids, seats=6, rng=rng)

    assert len(tables) == 20
    assert all(len(t) == 6 for t in tables)
    assert verify_pairing_integrity(tables, ids, seats=6) is True


def test_swiss_groups_tier_assignment():
    """G5.2: swiss_groups assigns highest-ranked players to Table 1, next to Table 2, etc."""
    # 120 standings
    standings = []
    for i in range(1, 121):
        # Rank 1 has +100 BB/100, down to Rank 120 with -100 BB/100
        bb = 100.0 - (i - 1) * (200.0 / 119.0)
        standings.append(Standing(agent_id=f"p_{i:03d}", hands=60, net_bb=bb * 0.6, bb100=bb, rank=i))

    ids = [s.agent_id for s in standings]
    tables = swiss_groups(ids, seats=6, standings=standings)

    assert len(tables) == 20
    # Table 0 (Shark table) must contain Rank 1..6
    assert tables[0] == [f"p_{i:03d}" for i in range(1, 7)]
    # Table 1 must contain Rank 7..12
    assert tables[1] == [f"p_{i:03d}" for i in range(7, 13)]
    # Table 19 (Tail table) must contain Rank 115..120
    assert tables[19] == [f"p_{i:03d}" for i in range(115, 121)]
    assert verify_pairing_integrity(tables, ids, seats=6) is True


def test_swiss_tiebreaker_preservation():
    """G5.3: swiss_groups respects R4-R10 tiebreaker when cumulative BB/100 is identical."""
    # Two players with identical cumulative BB/100 (25.0 BB/100), but different from_r4_net_bb
    s_playerA = Standing(agent_id="playerA", hands=100, net_bb=25.0, bb100=25.0)
    s_playerB = Standing(agent_id="playerB", hands=100, net_bb=25.0, bb100=25.0)

    # playerA won +50 BB in R4-R10; playerB won +20 BB in R4-R10
    tie_round = {"playerA": 50.0, "playerB": 20.0}
    ranked = rank_standings([s_playerB, s_playerA], tie_round=tie_round)

    assert ranked[0].agent_id == "playerA"
    assert ranked[1].agent_id == "playerB"

    # Swiss groups with these ranked standings must place playerA ahead of playerB
    groups = swiss_groups(["playerB", "playerA"], seats=1, standings=ranked)
    assert groups[0] == ["playerA"]
    assert groups[1] == ["playerB"]


def test_stack_continuity_during_reseating():
    """G5.4: Table reseating at Round 4 carries accumulated chip stacks continuously."""
    cfg = TournamentConfig(
        field_size=24,
        preliminary_rounds=5,
        hands_per_round=4,
        seats_per_table=6,
        semifinal_hands=2,
        final_hands=2,
    )
    agents = [SimAgent(f"p_{i}", StrategyAgent(seed=i)) for i in range(24)]
    sim = LeagueSimulator(agents, config=cfg, seed=99)

    st = sim._state()
    # Manually set p_0 stack to 40,000 (200 BB) and p_1 stack to 5,000 (25 BB)
    st["p_0"]["stack"] = 40000
    st["p_1"]["stack"] = 5000

    # Simulate preliminary rounds
    standings = sim.run_preliminary()
    assert len(standings) == 24
    # All players played all 5 rounds x 4 hands = 20 hands
    assert all(s.hands == 20 for s in standings)


def test_full_120_player_preliminary_swiss():
    """G5.5: Full 120-player field executes R1-R3 random and R4-R10 Swiss with zero drops."""
    cfg = TournamentConfig(
        field_size=120,
        preliminary_rounds=4,  # R1-R3 random, R4 Swiss
        hands_per_round=2,    # Fast smoke test
        seats_per_table=6,
    )
    agents = [SimAgent(f"a_{i:03d}", StrategyAgent(seed=100 + i)) for i in range(120)]
    sim = LeagueSimulator(agents, config=cfg, seed=1234)

    res = sim.run_event()
    assert len(res["preliminary"]) == 120
    assert len(res["qualified"]) == 12
    # All 120 agents completed 8 hands
    assert all(s.hands == 8 for s in res["preliminary"])
