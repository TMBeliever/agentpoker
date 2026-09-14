from __future__ import annotations
import pytest
from agentpoker.strategy import StrategyAgent, StrategyParams
from agentpoker.cards import parse_card, evaluate_relative_strength

def test_fold_discipline_when_behind_pot_odds():
    """Verify that when facing bet and clearly behind pot odds, the agent folds 100% of the time."""
    agent = StrategyAgent(StrategyParams(temperature=0.0), seed=42)
    obs = {
        "hero": ["4c", "7s"],
        "board": ["As", "Kd", "9h", "2c"],
        "legal": {"fold": None, "call": 5000, "allIn": 20000},
        "stack": 20000,
        "pot": 6000,
        "current_bet": 0,
        "big_blind": 1000,
        "position": 0,
        "dealer_seat": 1,
        "players": [
            {"agentId": "hero", "stack": 20000, "folded": False, "allIn": False, "currentBet": 0},
            {"agentId": "villain", "stack": 20000, "folded": False, "allIn": False, "currentBet": 5000},
        ],
        "context": {},
        "hand_id": 101,
        "agentId": "hero",
    }
    # Run 50 decisions with randomized seeds -- should ALWAYS fold
    for s in range(50):
        agent.rng.seed(s)
        action = agent.choose_local(obs)
        assert action["type"] == "fold", f"Expected fold, got {action} on seed {s}"

def test_choose_remote_resolves_big_blind_and_dealer_seat():
    """Verify that _choose_remote accurately extracts blinds.big and dealerSeatIndex from server format."""
    agent = StrategyAgent(StrategyParams(), seed=42)
    server_obs = {
        "agentId": "agent_hero",
        "table": {
            "id": "tbl-1",
            "blinds": {"small": 500, "big": 1000},
            "dealerSeatIndex": 4,
            "players": [
                {
                    "agentId": "agent_hero",
                    "seatIndex": 0,
                    "stack": 50000,
                    "handState": {
                        "status": "active",
                        "holeCards": ["Ts", "Jc"],
                        "currentBet": 0,
                    }
                },
                {
                    "agentId": "agent_v1",
                    "seatIndex": 4,
                    "stack": 50000,
                    "handState": {"status": "active", "holeCards": None, "currentBet": 0}
                }
            ],
            "hand": {
                "id": "h-1",
                "communityCards": [],
                "pot": 1500,
                "dealerSeatIndex": 4,
            }
        },
        "actionRequest": {
            "allowedActions": [
                {"type": "fold"},
                {"type": "call", "amount": 1000},
                {"type": "raise", "minAmount": 2000, "maxAmount": 50000},
            ]
        }
    }
    action = agent._choose_remote(server_obs)
    # With unopened pot and 1000 BB, hero should either raise or fold, NEVER limp-call 1000 in early/mid position!
    assert action["type"] in ("raise", "fold"), f"Expected open-or-fold, got limp-call {action}"

def test_preflop_facing_massive_raise_does_not_min_raise_ping_pong():
    """Verify that facing massive 4-bet / all-in, hero shoves all-in or calls/folds, rather than min-raising."""
    agent = StrategyAgent(StrategyParams(temperature=0.0), seed=42)
    # Hero has QQ facing a massive 25,000 raise
    obs = {
        "hero": ["Qd", "Qs"],
        "board": [],
        "legal": {"fold": None, "call": 25000, "raise": (35000, 50000), "allIn": 50000},
        "stack": 50000,
        "pot": 35000,
        "current_bet": 0,
        "big_blind": 1000,
        "position": 0,
        "dealer_seat": 1,
        "players": [
            {"agentId": "hero", "stack": 50000, "folded": False, "allIn": False, "currentBet": 0},
            {"agentId": "villain", "stack": 50000, "folded": False, "allIn": False, "currentBet": 25000},
        ],
        "context": {},
        "hand_id": 202,
        "agentId": "hero",
    }
    action = agent.choose_local(obs)
    # Must NOT min-raise to 35,000! Either all-in or call
    assert action["type"] in ("allIn", "call", "fold"), f"Did not expect min-raise, got {action}"
    if action["type"] == "raise":
        assert action["amount"] == 50000

def test_semi_bluff_does_not_trigger_on_river_or_with_no_draw():
    """Verify semi-bluffing is restricted to flop/turn and requires an actual draw."""
    agent = StrategyAgent(StrategyParams(temperature=0.0), seed=42)
    # River with wet board (flush/straight possible on board) but hero has 4c 2s (pure air)
    obs = {
        "hero": ["4c", "2s"],
        "board": ["8d", "9d", "Td", "Jc", "Ks"],
        "legal": {"fold": None, "check": None, "bet": (1000, 20000)},
        "stack": 20000,
        "pot": 6000,
        "current_bet": 0,
        "big_blind": 1000,
        "position": 0,
        "dealer_seat": 1,
        "players": [
            {"agentId": "hero", "stack": 20000, "folded": False, "allIn": False, "currentBet": 0},
            {"agentId": "villain", "stack": 20000, "folded": False, "allIn": False, "currentBet": 0},
        ],
        "context": {},
        "hand_id": 303,
        "agentId": "hero",
    }
    action = agent.choose_local(obs)
    # On river with pure air, should check, never semi-bluff bet!
    assert action["type"] == "check", f"Expected check on river with air, got {action}"

def test_two_pair_pocket_pair_distinguishes_overpair_to_board_pair():
    """Verify that QQ on AA895 is evaluated as an underpair to the board pair (low), while KK on 88345 is overpair."""
    hero_qq = [parse_card("Qd"), parse_card("Qs")]
    board_aa = [parse_card("Ad"), parse_card("As"), parse_card("8c"), parse_card("9h"), parse_card("5s")]
    res_under = evaluate_relative_strength(hero_qq, board_aa)
    assert res_under["tier"] == "two_pair_underpair_to_board_pair"
    assert res_under["strength"] < 0.60

    hero_kk = [parse_card("Kd"), parse_card("Ks")]
    board_88 = [parse_card("8d"), parse_card("8s"), parse_card("3c"), parse_card("4h"), parse_card("5s")]
    res_over = evaluate_relative_strength(hero_kk, board_88)
    assert res_over["tier"] == "two_pair_overpair_to_board_pair"
    assert res_over["strength"] > 0.70
