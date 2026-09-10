import pytest
from agentpoker.live import LiveRunner
from agentpoker.protocol import AgentPokerClient, Config
from agentpoker.strategy import StrategyAgent, StrategyParams

class DummyClient:
    cfg = Config(key="dummy_key", competition_id="comp_123")

def test_hand_tracking_and_round_boundary(tmp_path):
    client = DummyClient()
    strat = StrategyAgent(StrategyParams())
    prof_path = str(tmp_path / "test_profiles.json")
    runner = LiveRunner(
        client=client,
        strategy=strat,
        competition_id="comp_123",
        round_hands=2,
        cycle_hands=4,
        auto_profile=True,
        profiles_path=prof_path,
    )

    # Hand 1 initial state
    obs1 = {
        "agentId": "hero_1",
        "competitionId": "comp_123",
        "table": {
            "id": "t1",
            "bigBlind": 200,
            "players": [
                {"agentId": "hero_1", "stack": 20000, "name": "Hero"},
                {"agentId": "opp_1", "stack": 20000, "name": "Opp1"},
            ],
            "hand": {
                "id": "hand_1",
                "actions": [{"agentId": "hero_1", "type": "bet", "amount": 400}],
            },
        },
    }
    runner._track_hand_progress(obs1)
    assert runner.total_hands_played == 0

    # Hand 2 starts (Hand 1 completed with +600 netChange for hero)
    obs2 = {
        "agentId": "hero_1",
        "competitionId": "comp_123",
        "table": {
            "id": "t1",
            "bigBlind": 200,
            "players": [
                {"agentId": "hero_1", "stack": 20600, "netChange": 600, "name": "Hero"},
                {"agentId": "opp_1", "stack": 19400, "netChange": -600, "name": "Opp1"},
            ],
            "hand": {
                "id": "hand_2",
                "actions": [
                    {"agentId": "hero_1", "type": "call", "amount": 200},
                    {"agentId": "opp_1", "type": "fold"},
                ],
            },
        },
    }
    runner._track_hand_progress(obs2)
    assert runner.total_hands_played == 1
    assert runner.round_net_bb == 3.0  # +600 / 200

    # Hand 3 starts (Hand 2 completed with -200 netChange for hero)
    # Hand 2 is the 2nd hand, triggering round completion (round_hands = 2)
    obs3 = {
        "agentId": "hero_1",
        "competitionId": "comp_123",
        "table": {
            "id": "t1",
            "bigBlind": 200,
            "players": [
                {"agentId": "hero_1", "stack": 20400, "netChange": -200, "name": "Hero"},
                {"agentId": "opp_1", "stack": 19600, "netChange": 200, "name": "Opp1"},
            ],
            "hand": {
                "id": "hand_3",
                "actions": [{"agentId": "hero_1", "type": "raise", "amount": 600}],
            },
        },
    }
    runner._track_hand_progress(obs3)
    assert runner.total_hands_played == 2
    # Round 1 finished, advanced to Round 2!
    assert runner.current_round == 2
    assert runner.round_net_bb == 0.0  # Reset for round 2
    assert runner.cycle_net_bb == 2.0  # (600 - 200) / 200 = 2.0 BB

def test_tournament_context_injection():
    client = DummyClient()
    strat = StrategyAgent(StrategyParams())
    runner = LiveRunner(
        client=client,
        strategy=strat,
        competition_id="comp_123",
        round_hands=20,
        cycle_hands=200,
    )
    runner.total_hands_played = 40
    runner.current_round = 3
    runner.cycle_net_bb = 20.0  # 20 BB in 40 hands = +50 BB/100

    obs = {
        "agentId": "hero_1",
        "competitionId": "comp_123",
        "table": {
            "id": "t1",
            "bigBlind": 200,
            "players": [
                {"agentId": "hero_1", "stack": 20000, "handState": {"holeCards": ["Ah", "Kd"]}},
            ],
            "hand": {
                "id": "hand_41",
                "communityCards": [],
                "pot": 300,
            },
        },
        "actionRequest": {
            "id": "req_1",
            "allowedActions": [
                {"type": "fold"},
                {"type": "call", "amount": 200},
                {"type": "raise", "minAmount": 400, "maxAmount": 2000},
            ],
        },
    }

    body = runner._make_action_body(obs)
    ctx = obs.get("tournamentContext")
    assert ctx is not None
    assert ctx["round_no"] == 3
    assert ctx["hands_remaining"] == 160  # 200 - 40
    assert ctx["bb100"] == 50.0
    assert ctx["rank"] <= 12  # High BB/100 maps to safe qualification rank
    assert body["actionRequestId"] == "req_1"
    assert "decision" in body
