import pytest, json
from pathlib import Path
from agentpoker.battle import (
    discover_candidates,
    build_opponent_pool,
    ArenaBattle,
    CompetitorCandidate,
    print_battle_report,
)
from agentpoker.strategy import StrategyParams
from agentpoker.training import ARCHETYPES


def test_discover_candidates():
    cands = discover_candidates()
    assert len(cands) >= 6  # At least the 6 builtin archetypes
    categories = {c.category for c in cands}
    assert "archetype" in categories
    assert any(c.name == "bot_tight" for c in cands)


def test_build_opponent_pool():
    pool_arch = build_opponent_pool(mode="archetypes", count=18)
    assert len(pool_arch) == 18
    assert all(isinstance(p, StrategyParams) for p in pool_arch)

    pool_mix = build_opponent_pool(mode="mix", count=18)
    assert len(pool_mix) == 18

    pool_prof = build_opponent_pool(mode="profiles", count=18)
    assert len(pool_prof) == 18


def test_arena_battle_validation():
    with pytest.raises(ValueError, match="at least 2 competitor agents"):
        cands = discover_candidates()
        ArenaBattle(competitors=[cands[0]])


def test_arena_battle_execution():
    cands = discover_candidates()
    # Pick 3 competitors
    comp_a = CompetitorCandidate(
        cid="test_a",
        name="Agent_Tight",
        category="archetype",
        params=ARCHETYPES["tight"],
    )
    comp_b = CompetitorCandidate(
        cid="test_b",
        name="Agent_Lag",
        category="archetype",
        params=ARCHETYPES["lag"],
    )
    comp_c = CompetitorCandidate(
        cid="test_c",
        name="Agent_Station",
        category="archetype",
        params=ARCHETYPES["station"],
    )

    arena = ArenaBattle(
        competitors=[comp_a, comp_b, comp_c],
        opponent_mode="archetypes",
        field_size=12,
        workers=1,
        seed=123,
    )
    assert arena.field_size == 12

    report = arena.run(runs=2, verbose=False)
    assert report["runs"] == 2
    assert len(report["leaderboard"]) == 3

    # Check H2H reciprocity
    h2h = report["h2h_matrix"]
    assert h2h["test_a"]["test_b"]["wins"] == h2h["test_b"]["test_a"]["losses"]
    assert h2h["test_a"]["test_c"]["wins"] == h2h["test_c"]["test_a"]["losses"]

    # Verify report formatting doesn't raise
    print_battle_report(report)
