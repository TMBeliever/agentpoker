from __future__ import annotations
import requests
import pytest
from unittest.mock import MagicMock
from agentpoker.protocol import AgentPokerClient, APIError, Config, retry_same
from agentpoker.live import LiveRunner
from agentpoker.strategy import StrategyAgent, StrategyParams

def test_retry_same_network_exception_recovery():
    """Verify retry_same recovers from transient network exceptions with exponential backoff."""
    calls = 0
    def flaky_network():
        nonlocal calls
        calls += 1
        if calls < 3:
            raise requests.ConnectionError("Connection reset by peer")
        return {"status": "ok", "attempt": calls}

    result = retry_same(flaky_network, max_attempts=4, backoff=0.01)
    assert result["status"] == "ok"
    assert calls == 3

def test_retry_same_502_503_504_gateway_recovery():
    """Verify retry_same handles 502/503/504 Bad Gateway / Service Unavailable."""
    calls = 0
    def flaky_gateway():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise APIError(502, "temporarily_unavailable", "Bad Gateway")
        if calls == 2:
            raise APIError(504, "gateway_timeout", "Gateway Timeout")
        return {"status": "success"}

    result = retry_same(flaky_gateway, max_attempts=4, backoff=0.01)
    assert result["status"] == "success"
    assert calls == 3

def test_live_runner_fallback_action_safety():
    """Verify fallback action hierarchy prioritizes non-committal safety."""
    # Check preferred when free
    legal_check = {
        "fold": None,
        "check": None,
        "call": {"amount": 0},
        "bet": {"minAmount": 200, "maxAmount": 1000},
    }
    assert LiveRunner._fallback_action(legal_check) == {"type": "check"}

    # Fold preferred when facing bet
    legal_facing_bet = {
        "fold": None,
        "call": {"amount": 600},
        "raise": {"minAmount": 1200, "maxAmount": 2000},
    }
    assert LiveRunner._fallback_action(legal_facing_bet) == {"type": "fold"}

    # Call(0) preferred if check not in dict
    legal_zero_call = {
        "fold": None,
        "call": {"amount": 0},
        "bet": {"minAmount": 200, "maxAmount": 1000},
    }
    assert LiveRunner._fallback_action(legal_zero_call) == {"type": "call"}

def test_live_runner_handles_strategy_exception_gracefully():
    """Verify live runner falls back to safe action instead of crashing if strategy fails."""
    client = MagicMock()
    client.cfg = Config(key="test_key", competition_id="comp_1")

    faulty_strat = StrategyAgent(StrategyParams())
    faulty_strat.choose = MagicMock(side_effect=RuntimeError("unexpected strategy crash"))

    runner = LiveRunner(client, faulty_strat, competition_id="comp_1")

    obs = {
        "competitionId": "comp_1",
        "agentId": "hero",
        "table": {
            "id": "t1",
            "bigBlind": 200,
            "players": [{"agentId": "hero", "stack": 20000}],
            "hand": {"id": "h1", "pot": 300, "communityCards": []},
        },
        "actionRequest": {
            "id": "req_123",
            "allowedActions": [{"type": "check"}, {"type": "bet", "minAmount": 200, "maxAmount": 2000}],
        },
    }

    body = runner._make_action_body(obs)
    assert body["actionRequestId"] == "req_123"
    assert body["decision"]["type"] == "check"

def test_action_with_retry_network_and_stale_request():
    """Verify _action_with_retry handles network blips and stale requests by re-observing."""
    client = MagicMock()
    client.cfg = Config(key="test_key", competition_id="comp_1")

    # 1. Action raises network exception then succeeds
    client.action.side_effect = [
        requests.ConnectionError("Temporary blip"),
        {"status": "accepted"},
    ]

    strat = StrategyAgent(StrategyParams())
    runner = LiveRunner(client, strat, competition_id="comp_1")

    body = {"competitionId": "comp_1", "tableId": "t1", "actionRequestId": "r1", "decision": {"type": "check"}}
    obs = {"table": {"id": "t1"}}

    res = runner._action_with_retry(body, obs, max_attempts=3)
    assert res.get("status") == "accepted"

    # 2. Action raises stale_action_request, runner calls _observe_current()
    client.action.side_effect = APIError(400, "stale_action_request", "action timed out")
    runner._observe_current = MagicMock(return_value={"status": "seated", "table": {"id": "t1"}})

    res2 = runner._action_with_retry(body, obs, max_attempts=3)
    assert res2.get("status") == "seated"
    runner._observe_current.assert_called_once()
