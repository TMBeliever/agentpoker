from __future__ import annotations
import pytest
import random
from agentpoker.strategy import StrategyAgent, StrategyParams
from agentpoker.cards import RANKS, SUITS

ALL_CARDS = [f"{r}{s}" for r in RANKS for s in SUITS]

def _make_unopened_obs(
    hero: tuple[str, str],
    position: int,
    dealer_seat: int = 0,
    stack: int = 20000,
    bb_size: int = 200,
    context: dict | None = None,
) -> dict:
    players = [
        {"agentId": f"p{i}", "stack": stack, "folded": False, "allIn": False, "currentBet": 0}
        for i in range(6)
    ]
    # Blinds posted: seat 1 = SB (100), seat 2 = BB (200)
    players[1]["currentBet"] = bb_size // 2
    players[2]["currentBet"] = bb_size
    players[position]["agentId"] = "hero"

    return {
        "hero": list(hero),
        "board": [],
        "legal": {"fold": None, "call": bb_size, "raise": (bb_size * 2, stack), "allIn": stack},
        "stack": stack,
        "pot": bb_size + bb_size // 2, # 300
        "current_bet": 0,
        "big_blind": bb_size,
        "position": position,
        "dealer_seat": dealer_seat,
        "players": players,
        "context": context or {"stage": "preliminary", "rank": 5, "hands_remaining": 150},
        "agentId": "hero",
        "hand_id": 1,
    }

def test_1000_seeds_open_or_fold_zero_limp():
    """Gate 3: Verify that across 1000 seeds in UTG, HJ, CO, BTN, call_count is strictly 0."""
    all_cards = ALL_CARDS

    # In 6-max with dealer_seat=0:
    # seat 3 = UTG, seat 4 = HJ/MP, seat 5 = CO, seat 0 = BTN
    positions_to_test = [
        (3, "UTG"),
        (4, "HJ"),
        (5, "CO"),
        (0, "BTN"),
    ]

    total_decisions = 0
    call_count = 0
    raise_counts = {pos_name: 0 for _, pos_name in positions_to_test}
    fold_counts = {pos_name: 0 for _, pos_name in positions_to_test}

    for seat, pos_name in positions_to_test:
        for seed in range(1000):
            rng = random.Random(seed * 31 + seat)
            hero_hand = tuple(rng.sample(all_cards, 2))

            agent = StrategyAgent(StrategyParams(), seed=seed)
            obs = _make_unopened_obs(hero=hero_hand, position=seat, dealer_seat=0)

            action = agent.choose_local(obs)
            act_type = action["type"]
            total_decisions += 1

            assert act_type != "call", (
                f"VIOLATION: Agent open-limped (call) at position {pos_name} "
                f"with hand {hero_hand} at seed {seed}! Action: {action}"
            )
            assert act_type in ("raise", "bet", "allIn", "fold"), (
                f"Unexpected action type {act_type} at position {pos_name}"
            )

            if act_type in ("raise", "bet", "allIn"):
                raise_counts[pos_name] += 1
            else:
                fold_counts[pos_name] += 1

    # Strict Gate 3 Assertions:
    assert call_count == 0, f"Expected strictly 0 calls, got {call_count}"
    assert total_decisions == 4000

    # Ensure both raise and fold happen reasonably across hands
    for _, pos_name in positions_to_test:
        assert raise_counts[pos_name] > 0, f"{pos_name} should have non-zero open raises"
        assert fold_counts[pos_name] > 0, f"{pos_name} should have non-zero folds"

    # Positional monotonicity: BTN opens more than CO, CO opens more than HJ, HJ opens more than UTG
    assert raise_counts["BTN"] > raise_counts["CO"], "BTN open frequency should be higher than CO"
    assert raise_counts["CO"] > raise_counts["HJ"], "CO open frequency should be higher than HJ"
    assert raise_counts["HJ"] > raise_counts["UTG"], "HJ open frequency should be higher than UTG"

def test_extreme_passive_and_high_temperature_invariance():
    """Verify that even under hyper-passive parameters or high temperature, open-limp is never chosen."""
    passive_params = StrategyParams(
        attack=0.05,
        open_frequency=0.05,
        temperature=0.85,
        steal_frequency=0.10,
    )

    all_cards = ALL_CARDS
    test_positions = [3, 4, 5, 0] # UTG, HJ, CO, BTN

    for seat in test_positions:
        for seed in range(250):
            rng = random.Random(seed * 17 + seat)
            hero_hand = tuple(rng.sample(all_cards, 2))

            agent = StrategyAgent(passive_params, seed=seed)
            obs = _make_unopened_obs(hero=hero_hand, position=seat, dealer_seat=0)

            action = agent.choose_local(obs)
            assert action["type"] != "call", f"Passive agent must still never open-limp! Got {action}"
            assert action["type"] in ("raise", "bet", "allIn", "fold")

def test_specific_hand_archetypes_open_or_fold():
    """Verify deterministic open on premiums and deterministic fold on unplayable trash."""
    agent = StrategyAgent(StrategyParams(temperature=0.0), seed=42)

    # 1. Premium AA from UTG -> MUST Raise
    obs_aa = _make_unopened_obs(hero=("Ah", "As"), position=3, dealer_seat=0)
    act_aa = agent.choose_local(obs_aa)
    assert act_aa["type"] in ("raise", "allIn")

    # 2. Complete trash 72o from UTG -> MUST Fold
    obs_72 = _make_unopened_obs(hero=("7d", "2c"), position=3, dealer_seat=0)
    act_72 = agent.choose_local(obs_72)
    assert act_72["type"] == "fold"

    # 3. Steal holding K6s on BTN -> MUST Raise
    obs_k6 = _make_unopened_obs(hero=("Kh", "6h"), position=0, dealer_seat=0)
    act_k6 = agent.choose_local(obs_k6)
    assert act_k6["type"] in ("raise", "allIn")

    # 4. Trash 83o on BTN -> MUST Fold
    obs_83 = _make_unopened_obs(hero=("8c", "3d"), position=0, dealer_seat=0)
    act_83 = agent.choose_local(obs_83)
    assert act_83["type"] == "fold"
