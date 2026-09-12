from dataclasses import FrozenInstanceError
import tempfile
from pathlib import Path
import pytest

from agentpoker.config import TournamentConfig
from agentpoker.tournament import LeagueSimulator, SimAgent
from agentpoker.strategy import StrategyAgent, StrategyParams


def test_default_config_is_official_120():
    """G2.1: Default config strictly matches the official 120-player specification."""
    cfg = TournamentConfig()
    assert cfg.field_size == 120
    assert cfg.small_blind == 100
    assert cfg.big_blind == 200
    assert cfg.starting_stack_bb == 100
    assert cfg.seats_per_table == 6
    assert cfg.preliminary_rounds == 10
    assert cfg.hands_per_round == 20
    assert cfg.min_completion_rate == 0.80
    assert cfg.semifinal_qualifiers == 12
    assert cfg.semifinal_tables == 2
    assert cfg.semifinal_hands == 20
    assert cfg.final_qualifiers == 6
    assert cfg.final_hands == 30


def test_config_immutability():
    """G2.2: Config is immutable (frozen dataclass)."""
    cfg = TournamentConfig()
    with pytest.raises(FrozenInstanceError):
        cfg.field_size = 96  # type: ignore


def test_config_validation():
    """G2.3: Validation catches invalid tournament structures."""
    # Field size not divisible by seats
    with pytest.raises(ValueError, match="divisible by seats_per_table"):
        TournamentConfig(field_size=25, seats_per_table=6)

    # Field size smaller than semifinal qualifiers
    with pytest.raises(ValueError, match="must be >= semifinal_qualifiers"):
        TournamentConfig(field_size=6, semifinal_qualifiers=12)

    # Semifinal qualifiers != semifinal_tables * seats_per_table
    with pytest.raises(ValueError, match="semifinal_tables \\* seats_per_table"):
        TournamentConfig(semifinal_qualifiers=10, semifinal_tables=2, seats_per_table=6)

    # Final qualifiers != seats_per_table
    with pytest.raises(ValueError, match="equal seats_per_table"):
        TournamentConfig(final_qualifiers=5, seats_per_table=6)

    # Invalid min_completion_rate
    with pytest.raises(ValueError, match="min_completion_rate"):
        TournamentConfig(min_completion_rate=0.0)
    with pytest.raises(ValueError, match="min_completion_rate"):
        TournamentConfig(min_completion_rate=1.5)

    # Invalid blinds
    with pytest.raises(ValueError, match="Invalid blinds"):
        TournamentConfig(small_blind=200, big_blind=100)
    with pytest.raises(ValueError, match="Invalid blinds"):
        TournamentConfig(small_blind=0, big_blind=200)


def test_derived_properties():
    """G2.4: Derived properties accurately reflect tournament math."""
    cfg = TournamentConfig.official_120()
    assert cfg.starting_chips == 20000
    assert cfg.total_preliminary_hands == 200
    assert cfg.min_hands_required == 160
    assert cfg.num_tables == 20
    assert cfg.top12_rate_baseline == pytest.approx(12 / 120)  # 10.0%
    assert cfg.final_rate_baseline == pytest.approx(6 / 120)   # 5.0%
    assert cfg.champion_rate_baseline == pytest.approx(1 / 120) # 0.833%
    # Baseline fitness under zero-sum equilibrium:
    expected_fit = (
        0.20 * (12 / 120)
        + 0.20 * (6 / 120)
        + 0.25 * (1 / 120)
        + 0.05 * 0.50
        + 0.30 * 0.50
    )
    assert cfg.baseline_fitness == pytest.approx(expected_fit)


def test_named_profiles():
    """G2.5: Official named profiles instantiate correctly."""
    c120 = TournamentConfig.official_120()
    assert c120.field_size == 120
    assert c120.num_tables == 20

    c36 = TournamentConfig.fast_36()
    assert c36.field_size == 36
    assert c36.num_tables == 6

    c24 = TournamentConfig.smoke_24()
    assert c24.field_size == 24
    assert c24.num_tables == 4


def test_yaml_round_trip():
    """G2.6: YAML serialization and deserialization work cleanly."""
    cfg = TournamentConfig.official_120()
    with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        cfg.to_yaml(tmp_path)
        loaded = TournamentConfig.from_yaml(tmp_path)
        assert loaded == cfg
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def test_configs_tournament_yaml_loads():
    """G2.7: configs/tournament.yaml in the repo loads into a valid TournamentConfig."""
    repo_cfg_path = Path(__file__).resolve().parent.parent / "configs" / "tournament.yaml"
    assert repo_cfg_path.exists()
    cfg = TournamentConfig.from_yaml(repo_cfg_path)
    assert cfg.field_size == 120
    assert cfg.total_preliminary_hands == 200
    assert cfg.semifinal_hands == 20
    assert cfg.final_hands == 30


def test_league_simulator_uses_config():
    """G2.8: LeagueSimulator accepts and respects custom TournamentConfig."""
    # Test with smoke_24 profile, 1 round x 2 hands, 2 semifinal hands, 2 final hands
    custom_cfg = TournamentConfig(
        field_size=24,
        preliminary_rounds=1,
        hands_per_round=2,
        semifinal_hands=2,
        final_hands=2,
        min_completion_rate=0.50,
    )
    agents = [SimAgent(f"a_{i}", StrategyAgent(seed=i)) for i in range(24)]
    sim = LeagueSimulator(agents, config=custom_cfg, seed=123)

    assert sim.config == custom_cfg
    assert sim.rounds == 1
    assert sim.hpr == 2
    assert sim.seats == 6

    res = sim.run_event()
    assert len(res["preliminary"]) == 24
    assert len(res["qualified"]) == 12
    assert len(res["semifinal"]) == 2  # 2 semifinal tables
    assert len(res["final"]) == 6       # 6 final players
