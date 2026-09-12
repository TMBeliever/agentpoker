from __future__ import annotations
import pytest
from agentpoker.strategy import StrategyAgent, StrategyParams, OpponentStats
from agentpoker.cards import parse_card

def _make_obs(
    hero=("Ah", "Kd"),
    board=(),
    legal=None,
    stack=20000,
    pot=300,
    current_bet=0,
    big_blind=200,
    position=0,
    dealer_seat=5,
    players=None,
    context=None,
    hand_id=1,
    agent_id="hero",
):
    if legal is None:
        legal = {"fold": None, "check": None, "call": 0, "bet": (200, 20000), "allIn": 20000}
    if players is None:
        players = [
            {"agentId": "hero", "stack": stack, "folded": False, "allIn": False, "currentBet": current_bet},
            {"agentId": "villain1", "stack": 20000, "folded": False, "allIn": False, "currentBet": current_bet},
            {"agentId": "villain2", "stack": 20000, "folded": False, "allIn": False, "currentBet": current_bet},
            {"agentId": "villain3", "stack": 20000, "folded": False, "allIn": False, "currentBet": current_bet},
            {"agentId": "villain4", "stack": 20000, "folded": False, "allIn": False, "currentBet": current_bet},
            {"agentId": "villain5", "stack": 20000, "folded": False, "allIn": False, "currentBet": current_bet},
        ]
    return {
        "hero": list(hero),
        "board": list(board),
        "legal": legal,
        "stack": stack,
        "pot": pot,
        "current_bet": current_bet,
        "big_blind": big_blind,
        "position": position,
        "dealer_seat": dealer_seat,
        "players": players,
        "context": context or {},
        "hand_id": hand_id,
        "agentId": agent_id,
    }

def test_tournament_pressure_sign_and_push_fold():
    """Verify that trailing urgency expands shove range and leading safety tightens it."""
    agent = StrategyAgent(StrategyParams(vpip=0.23, temperature=0.0), seed=42)

    # 1. Check pressure sign
    ctx_safe = {
        "stage": "preliminary",
        "rank": 2,
        "bb100": 35.0,
        "rank12_bb100": 5.0,
        "buffer_bb100": 30.0,
        "hands_remaining": 30,
        "total_stage_hands": 200,
        "stage_progress": 0.85,
    }
    ctx_trailing = {
        "stage": "preliminary",
        "rank": 25,
        "bb100": -15.0,
        "rank12_bb100": 5.0,
        "buffer_bb100": -20.0,
        "hands_remaining": 30,
        "total_stage_hands": 200,
        "stage_progress": 0.85,
    }

    press_safe = agent._tournament_pressure(ctx_safe)
    press_trail = agent._tournament_pressure(ctx_trailing)

    assert press_safe < 0.0, f"Safe lead should have negative pressure, got {press_safe}"
    assert press_trail > 0.0, f"Trailing rank should have positive pressure, got {press_trail}"

    # 2. Short stack push/fold behavior (effective_bb = 8 BB)
    # A marginal hand like 8s, 7s
    obs_trail = _make_obs(
        hero=("8s", "7s"),
        stack=1600, # 8 BB
        legal={"fold": None, "allIn": 1600, "call": 200},
        position=0,
        dealer_seat=0, # BTN
        context=ctx_trailing,
    )
    obs_safe = _make_obs(
        hero=("8s", "7s"),
        stack=1600, # 8 BB
        legal={"fold": None, "allIn": 1600, "call": 200},
        position=0,
        dealer_seat=0, # BTN
        context=ctx_safe,
    )

    action_trail = agent.choose_local(obs_trail)
    action_safe = agent.choose_local(obs_safe)

    # Under trailing urgency, hero shoves with 8s7s on the button; under safe lead, hero protects chips
    assert action_trail["type"] in ("allIn", "raise", "call")
    assert action_safe["type"] == "fold"

def test_preliminary_fish_harvesting():
    """Verify fish harvesting: larger preflop open, larger value bets, no pure bluffs."""
    agent = StrategyAgent(StrategyParams(temperature=0.0), seed=42)

    # Set villain1 as a calling station (high call, low fold)
    agent.opponents["villain1"] = OpponentStats(hands=50, calls=30, folds=5, bets=5, raises=3, checks=7)

    # Preflop open sizing: should use preflop_size_mult = 1.30 against fish
    obs_preflop = _make_obs(
        hero=("Ah", "Kd"),
        board=(),
        legal={"fold": None, "check": None, "call": 0, "raise": (400, 20000), "allIn": 20000},
        context={"stage": "preliminary", "rank": 5, "hands_remaining": 150},
    )
    action_preflop = agent.choose_local(obs_preflop)
    assert action_preflop["type"] == "raise"
    # Base open size is 2.35 * 200 = 470; with premium 0.6: 2.95 * 200 = 590.
    # With fish 1.30x mult: (2.35 * 1.30 + 0.6) * 200 = (3.055 + 0.6) * 200 = 731.
    assert action_preflop["amount"] > 650, f"Expected enlarged open size vs fish, got {action_preflop['amount']}"

    # Postflop value bet sizing: top set on river heads-up against station
    hu_players = [
        {"agentId": "hero", "stack": 20000, "folded": False, "allIn": False, "currentBet": 0},
        {"agentId": "villain1", "stack": 20000, "folded": False, "allIn": False, "currentBet": 0},
        {"agentId": "villain2", "stack": 20000, "folded": True, "allIn": False, "currentBet": 0},
        {"agentId": "villain3", "stack": 20000, "folded": True, "allIn": False, "currentBet": 0},
        {"agentId": "villain4", "stack": 20000, "folded": True, "allIn": False, "currentBet": 0},
        {"agentId": "villain5", "stack": 20000, "folded": True, "allIn": False, "currentBet": 0},
    ]
    obs_river_value = _make_obs(
        hero=("Ah", "Ac"),
        board=("Ad", "8h", "2s", "7c", "3d"),
        legal={"fold": None, "check": None, "bet": (200, 10000), "allIn": 10000},
        pot=1000,
        players=hu_players,
        context={"stage": "preliminary", "rank": 5, "hands_remaining": 150},
    )
    action_value = agent.choose_local(obs_river_value)
    assert action_value["type"] in ("bet", "raise", "allIn")

    # Pure bluff with air on river: should be suppressed vs calling station
    obs_river_bluff = _make_obs(
        hero=("2c", "3s"),
        board=("Kh", "Qd", "9s", "8h", "4c"),
        legal={"fold": None, "check": None, "bet": (200, 10000), "allIn": 10000},
        pot=1000,
        players=hu_players,
        context={"stage": "preliminary", "rank": 5, "hands_remaining": 150},
    )
    action_bluff = agent.choose_local(obs_river_bluff)
    assert action_bluff["type"] in ("check", "fold"), f"Should not bluff calling station, got {action_bluff}"

def test_preliminary_nit_exploitation():
    """Verify exploitation of nits: wider steal and folding to nit bets."""
    agent = StrategyAgent(StrategyParams(temperature=0.0), seed=42)

    # Set villain1 as a nit (low vpip, high fold)
    agent.opponents["villain1"] = OpponentStats(hands=60, vpip=6, folds=45, bets=8, raises=5, calls=2)

    # Steal spot on BTN with marginal holding
    obs_steal = _make_obs(
        hero=("Ks", "6s"),
        board=(),
        legal={"fold": None, "check": None, "raise": (400, 20000), "allIn": 20000},
        position=0,
        dealer_seat=0, # BTN
        context={"stage": "preliminary", "rank": 8, "hands_remaining": 120},
    )
    action_steal = agent.choose_local(obs_steal)
    assert action_steal["type"] in ("raise", "bet"), f"Expected steal open against nit blind, got {action_steal}"

    # Facing a nit bet with a weak bluff-catcher on river (pot sized bet 1200 into 1200)
    obs_facing_nit_bet = _make_obs(
        hero=("2h", "3s"),
        board=("8s", "Qd", "Ac", "Kd", "2c"),
        legal={"fold": None, "call": 1200, "raise": (2400, 20000), "allIn": 20000},
        pot=1200,
        context={"stage": "preliminary", "rank": 8, "hands_remaining": 120},
    )
    action_facing_bet = agent.choose_local(obs_facing_nit_bet)
    assert action_facing_bet["type"] == "fold", f"Should fold weak bluff catcher facing nit bet, got {action_facing_bet}"

def test_semifinal_bubble_factor_rank3_vs_rank4():
    """Verify bubble factor in semifinal: Rank 3 protects qualification; Rank 4 attacks."""
    agent = StrategyAgent(StrategyParams(temperature=0.0), seed=42)

    ctx_rank3 = {
        "stage": "semifinal",
        "rank": 3,
        "round_no": 11,
        "cutoff_bb100": 5.0,
        "buffer_bb100": 2.0,
        "hands_remaining": 6,
        "stage_progress": 0.70,
        "total_stage_hands": 20,
    }
    ctx_rank4 = {
        "stage": "semifinal",
        "rank": 4,
        "round_no": 11,
        "cutoff_bb100": 5.0,
        "buffer_bb100": -4.0,
        "hands_remaining": 6,
        "stage_progress": 0.70,
        "total_stage_hands": 20,
    }

    press3 = agent._tournament_pressure(ctx_rank3)
    press4 = agent._tournament_pressure(ctx_rank4)

    assert press3 < 0.0, f"Rank 3 on bubble should have defensive pressure, got {press3}"
    assert press4 > 0.5, f"Rank 4 facing elimination should have high attack pressure, got {press4}"

    # Compare push/fold on late short stack from UTG (position 3, dealer 0 in 6-max)
    players6 = [{"agentId": f"p{i}", "folded": False, "allIn": False, "stack": 20000} for i in range(6)]
    players6[3]["stack"] = 1800 # Hero stack 9 BB

    obs_rank3 = _make_obs(
        hero=("Ks", "8c"),
        stack=1800, # 9 BB
        legal={"fold": None, "allIn": 1800, "call": 200},
        position=3,
        dealer_seat=0,
        players=players6,
        context=ctx_rank3,
        agent_id="p3",
    )
    obs_rank4 = _make_obs(
        hero=("Ks", "8c"),
        stack=1800, # 9 BB
        legal={"fold": None, "allIn": 1800, "call": 200},
        position=3,
        dealer_seat=0,
        players=players6,
        context=ctx_rank4,
        agent_id="p3",
    )

    action3 = agent.choose_local(obs_rank3)
    action4 = agent.choose_local(obs_rank4)

    assert action3["type"] == "fold", f"Rank 3 should fold marginal shove on bubble, got {action3}"
    assert action4["type"] == "allIn", f"Rank 4 trailing late must shove to survive, got {action4}"

def test_final_table_winner_take_all_aggression():
    """Verify that trailing in the final table ramps up aggression (no ICM preservation for 2nd)."""
    agent = StrategyAgent(StrategyParams(temperature=0.0), seed=42)

    ctx_final_trail = {
        "stage": "final",
        "rank": 2,
        "round_no": 12,
        "cutoff_bb100": 25.0,
        "buffer_bb100": -15.0,
        "hands_remaining": 8,
        "stage_progress": 0.73,
        "total_stage_hands": 30,
    }

    press_final = agent._tournament_pressure(ctx_final_trail)
    assert press_final >= 0.8, f"Trailing late in final table should yield maximum attack pressure, got {press_final}"

    # Trailing rank 2 shoves wide in late hands (e.g. Q9o on BTN)
    obs_final = _make_obs(
        hero=("Qd", "9s"),
        stack=2200, # 11 BB
        legal={"fold": None, "allIn": 2200, "call": 200},
        position=0,
        dealer_seat=0,
        context=ctx_final_trail,
    )
    action_final = agent.choose_local(obs_final)
    assert action_final["type"] == "allIn", f"Expected aggressive shove when trailing final table, got {action_final}"
