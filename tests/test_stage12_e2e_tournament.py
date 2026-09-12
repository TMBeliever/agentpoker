import pytest
from agentpoker.config import TournamentConfig
from agentpoker.tournament import LeagueSimulator, SimAgent
from agentpoker.strategy import StrategyAgent, StrategyParams
from agentpoker.ecosystem import build_120_pyramid_field

def test_official_120_player_tournament_e2e():
    """End-to-end simulation of the official 120-player tournament with 3 stages.
    
    1. Preliminary: 120 players across 20 tables, R1-R3 Random, R4+ Swiss, Top 12 qualify
    2. Semifinal: 12 players across 2 tables of 6, Top 3 per table qualify
    3. Final: 6 players on 1 table of 6, 1st place Champion crowned
    """
    field_params = build_120_pyramid_field(seed=42)
    assert len(field_params) == 120

    agents = [
        SimAgent(f"p_{i:03d}", StrategyAgent(p, seed=1000 + i, name=f"p_{i:03d}"))
        for i, p in enumerate(field_params)
    ]

    cfg = TournamentConfig(
        field_size=120,
        preliminary_rounds=5,  # R1-R3 random + R4-R5 Swiss
        hands_per_round=3,     # Fast E2E verification
        seats_per_table=6,
        semifinal_qualifiers=12,
        semifinal_tables=2,
        semifinal_hands=5,
        final_qualifiers=6,
        final_hands=5,
    )

    sim = LeagueSimulator(agents, config=cfg, seed=777)
    result = sim.run_event()

    # Stage 1 Verification
    prelim = result["preliminary"]
    assert len(prelim) == 120
    assert all(s.hands == 15 for s in prelim)
    # Check strict rank ordering 1..120
    assert [s.rank for s in prelim] == list(range(1, 121))

    # Stage 2 Verification
    qualified = result["qualified"]
    assert len(qualified) == 12
    sf_tables = result["semifinal"]
    assert len(sf_tables) == 2
    for tbl in sf_tables:
        assert len(tbl) == 6
        assert all(s.hands == 5 for s in tbl)

    # Stage 3 Verification
    final = result["final"]
    assert len(final) == 6
    assert all(s.hands == 5 for s in final)
    assert [s.rank for s in final] == list(range(1, 7))

    champion = final[0]
    assert champion.rank == 1
    assert champion.agent_id is not None
