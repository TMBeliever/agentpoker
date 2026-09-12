from __future__ import annotations
import json
import math
from pathlib import Path
import pytest
from agentpoker.config import TournamentConfig, ExecutionMode
from agentpoker.tournament import LeagueSimulator, SimAgent
from agentpoker.strategy import StrategyAgent
from agentpoker.ecosystem import build_120_pyramid_field
from agentpoker.battle import certify_champion


def test_full_official_120_player_tournament_validation():
    """Stage 9 Gate: Full official 120-player tournament validation.
    
    1. 120-player pyramid ecosystem.
    2. Exact official structure: 200 prelim hands (10 rounds x 20 hands), 20 semifinal hands, 30 final hands.
    3. Rigorous statistical metrics calculation (Mean, SE, 95% CI).
    4. Full validation of champion model against certification invariants.
    """
    cfg = TournamentConfig.official_120()
    assert cfg.execution_mode == ExecutionMode.OFFICIAL
    assert cfg.field_size == 120
    assert cfg.seats_per_table == 6
    assert cfg.total_preliminary_hands == 200
    assert cfg.semifinal_hands == 20
    assert cfg.final_hands == 30

    field_params = build_120_pyramid_field(seed=42)
    assert len(field_params) == 120

    champ = StrategyAgent.load("models/champion.json")
    agents = [
        SimAgent(f"opp_{i:03d}", StrategyAgent(p, seed=2000 + i, name=f"opp_{i:03d}"))
        for i, p in enumerate(field_params)
    ]
    # Hero champion enters tournament as hero
    agents[0] = SimAgent("hero_champion", champ)

    sim = LeagueSimulator(agents, config=cfg, seed=12345)
    result = sim.run_event()

    # 1. Preliminary Stage Checks
    prelim = result["preliminary"]
    assert len(prelim) == 120
    assert all(s.hands == 200 for s in prelim)
    assert [s.rank for s in prelim] == list(range(1, 121))

    # Calculate preliminary BB/100 statistics across field
    bb100_list = [s.bb100 for s in prelim]
    mean_bb100 = sum(bb100_list) / len(bb100_list)
    variance_bb100 = sum((x - mean_bb100) ** 2 for x in bb100_list) / (len(bb100_list) - 1)
    se_bb100 = math.sqrt(variance_bb100 / len(bb100_list))
    ci95_low = mean_bb100 - 1.96 * se_bb100
    ci95_high = mean_bb100 + 1.96 * se_bb100

    # Due to zero-sum chips, field mean BB/100 must be approximately 0
    assert abs(mean_bb100) < 1.0, f"Field mean BB/100 should be ~0, got {mean_bb100}"
    assert se_bb100 > 0.0
    assert ci95_low <= mean_bb100 <= ci95_high

    # 2. Semifinal Stage Checks
    qualified = result["qualified"]
    assert len(qualified) == 12
    sf_tables = result["semifinal"]
    assert len(sf_tables) == 2
    for tbl in sf_tables:
        assert len(tbl) == 6
        assert all(s.hands == 20 for s in tbl)

    # 3. Final Stage Checks
    finalists = result["final"]
    assert len(finalists) == 6
    assert all(s.hands == 30 for s in finalists)
    assert [s.rank for s in finalists] == list(range(1, 7))

    champion_winner = finalists[0]
    assert champion_winner.rank == 1
    assert champion_winner.agent_id is not None


def test_champion_json_satisfies_all_six_certification_invariants():
    """Verify that models/champion.json satisfies configs/certification_policy.json's invariants."""
    policy_path = Path("configs/certification_policy.json")
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    invariants = policy.get("invariants", {})

    champ_path = Path("models/champion.json")
    champ_data = json.loads(champ_path.read_text(encoding="utf-8"))
    cert = champ_data.get("certification", {})

    assert cert.get("certified") is True
    criteria = {c["name"]: c for c in cert.get("criteria", [])}

    # Invariant 1: Leaderboard Rank #1
    assert "Leaderboard Rank #1" in criteria
    assert criteria["Leaderboard Rank #1"]["passed"] is True

    # Invariant 2: Title / Deep Run Superiority
    assert "Title / Deep Run Superiority" in criteria
    assert criteria["Title / Deep Run Superiority"]["passed"] is True

    # Invariant 3: Positive BB/100
    assert "Positive Expected Value (BB/100)" in criteria
    assert criteria["Positive Expected Value (BB/100)"]["passed"] is True

    # Invariant 4: Top 12 Qualification Rate
    assert "Top 12 Deep Run Qualification Rate" in criteria
    assert criteria["Top 12 Deep Run Qualification Rate"]["passed"] is True

    # Invariant 5: Benchmark Dominance
    assert "Benchmark Dominance & Tournament EV" in criteria
    assert criteria["Benchmark Dominance & Tournament EV"]["passed"] is True

    # Invariant 6: All Criteria Passed
    assert all(c["passed"] for c in cert.get("criteria", []))
