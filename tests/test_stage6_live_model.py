import os
import json
import pytest
from unittest.mock import MagicMock
from agentpoker.protocol import AgentPokerClient, Config
from agentpoker.live import LiveRunner
from agentpoker.strategy import StrategyAgent, StrategyParams

def test_live_runner_defaults_to_champion(tmp_path):
    """LiveRunner must strictly default to models/champion.json when strategy is omitted."""
    client = MagicMock()
    client.cfg = Config(key="test_key", competition_id="comp_1")

    # When champion.json exists at models/champion.json
    if os.path.exists("models/champion.json"):
        runner = LiveRunner(client, competition_id="comp_1")
        assert runner.strategy_path == "models/champion.json"
        assert runner.strategy is not None
        assert isinstance(runner.strategy, StrategyAgent)


def test_live_runner_raises_error_when_model_missing(tmp_path):
    """LiveRunner must raise FileNotFoundError if strategy is None and model path does not exist."""
    client = MagicMock()
    client.cfg = Config(key="test_key", competition_id="comp_1")

    non_existent = str(tmp_path / "non_existent_champion.json")
    with pytest.raises(FileNotFoundError, match="Production model not found"):
        LiveRunner(client, strategy=None, strategy_path=non_existent)


def test_live_runner_hot_reload_on_mtime_change(tmp_path):
    """LiveRunner reloads strategy when file mtime changes."""
    client = MagicMock()
    client.cfg = Config(key="test_key", competition_id="comp_1")

    strat_file = tmp_path / "champion.json"
    p1 = StrategyParams(vpip=0.20, steal_frequency=0.50)
    strat_file.write_text(json.dumps({"params": p1.__dict__}), encoding="utf-8")

    runner = LiveRunner(client, strategy_path=str(strat_file))
    assert runner.strategy.params.vpip == pytest.approx(0.20)

    # Now modify model on disk and bump mtime
    p2 = StrategyParams(vpip=0.25, steal_frequency=0.60)
    strat_file.write_text(json.dumps({"params": p2.__dict__}), encoding="utf-8")
    new_mtime = runner._strategy_mtime + 10.0
    os.utime(str(strat_file), (new_mtime, new_mtime))

    runner._check_and_reload_strategy()
    assert runner.strategy.params.vpip == pytest.approx(0.25)
    assert runner._strategy_mtime == pytest.approx(new_mtime)
