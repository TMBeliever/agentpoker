import pytest
from unittest.mock import MagicMock
from agentpoker.config import TournamentConfig, ExecutionMode
from agentpoker.battle import ArenaBattle, CompetitorCandidate, certify_champion
from agentpoker.strategy import StrategyParams
from agentpoker.live import LiveRunner


def test_official_mode_requires_120_players():
    # 1. Reject field_size != 120 under OFFICIAL mode
    with pytest.raises(ValueError, match="OFFICIAL execution mode strictly requires field_size == 120"):
        TournamentConfig(field_size=36, execution_mode=ExecutionMode.OFFICIAL)

    with pytest.raises(ValueError, match="OFFICIAL execution mode strictly requires field_size == 120"):
        TournamentConfig(field_size=24, execution_mode=ExecutionMode.OFFICIAL)

    # 2. Allow field_size == 120 under OFFICIAL mode
    cfg = TournamentConfig.official_120()
    assert cfg.execution_mode == ExecutionMode.OFFICIAL
    assert cfg.field_size == 120
    assert cfg.seats_per_table == 6
    assert cfg.total_preliminary_hands == 200
    assert cfg.semifinal_hands == 20
    assert cfg.final_hands == 30


def test_official_benchmark_cannot_use_36():
    # 1. Cannot instantiate fast_36 with OFFICIAL mode
    with pytest.raises(ValueError, match="cannot be used in OFFICIAL execution mode"):
        TournamentConfig.fast_36(mode=ExecutionMode.OFFICIAL)

    # 2. ArenaBattle rejects official=True with field_size == 36
    c1 = CompetitorCandidate(cid="c1", name="C1", category="model", params=StrategyParams())
    c2 = CompetitorCandidate(cid="c2", name="C2", category="model", params=StrategyParams())
    with pytest.raises(ValueError, match="Official benchmark strictly requires field_size == 120"):
        ArenaBattle([c1, c2], field_size=36, official=True)


def test_official_certification_cannot_use_24():
    # 1. smoke_24 rejects OFFICIAL mode
    with pytest.raises(ValueError, match="cannot be used in OFFICIAL execution mode"):
        TournamentConfig.smoke_24(mode=ExecutionMode.OFFICIAL)

    # 2. certify_champion with official=True strictly rejects field_size == 24
    dummy_report = {
        "field_size": 24,
        "runs": 20,
        "leaderboard": [
            {
                "cid": "cand",
                "name": "Candidate",
                "standing": 1,
                "score": 100.0,
                "champ_rate": 0.20,
                "champ_count": 4,
                "final_rate": 0.50,
                "final_count": 10,
                "top12_rate": 0.80,
                "top12_count": 16,
                "avg_bb100": 5.0,
            }
        ],
        "h2h_matrix": {},
    }
    with pytest.raises(ValueError, match="Official champion certification strictly requires field_size == 120"):
        certify_champion(dummy_report, candidate_cid="cand", official=True)


def test_live_uses_official_config():
    mock_client = MagicMock()
    mock_client.cfg.competition_id = "test_comp"
    runner = LiveRunner(client=mock_client)
    assert runner.config is not None
    assert runner.config.execution_mode == ExecutionMode.OFFICIAL
    assert runner.config.field_size == 120
    assert runner.config.seats_per_table == 6
    assert runner.config.total_preliminary_hands == 200
