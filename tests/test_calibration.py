import inspect

import pytest

from agentpoker.cards import card
from agentpoker.calibration import (PREFLOP_PERCENTILE, strength_to_equity,
                                    hand_class, preflop_percentile)
from agentpoker.context import (rank_from_bb100, boundary_bb100, synthetic_context,
                                context_from_standings, QUALIFY_RANK, FIELD_SIZE)


def test_preflop_percentile_ranks_hands_sensibly():
    assert hand_class([card('s', 'A'), card('h', 'A')]) == hand_class([card('d', 'A'), card('c', 'A')])
    aces = preflop_percentile([card('s', 'A'), card('h', 'A')])
    kings = preflop_percentile([card('s', 'K'), card('h', 'K')])
    three_two = preflop_percentile([card('s', '3'), card('h', '2')])
    assert aces is not None and aces == max(PREFLOP_PERCENTILE.values())
    assert aces > kings > three_two
    # 32o, not 72o, is the weakest heads-up holding (0.318 vs 0.324 all-in equity).
    assert three_two == min(PREFLOP_PERCENTILE.values())


def test_preflop_percentile_distinguishes_suitedness():
    suited = preflop_percentile([card('s', 'A'), card('s', 'K')])
    offsuit = preflop_percentile([card('s', 'A'), card('h', 'K')])
    assert suited > offsuit


def test_strength_to_equity_is_monotone_in_strength():
    for street in (3, 4, 5):
        for n in (1, 3, 5):
            prev = -1.0
            for i in range(0, 101):
                eq = strength_to_equity(street, n, i / 100.0)
                assert eq >= prev - 1e-9, f"not monotone at street={street} n={n} s={i/100}"
                prev = eq


def test_more_opponents_means_less_equity_for_the_same_hand():
    """A fixed holding wins less often against more players -- the property the raw
    heuristic score was blind to."""
    for street in (3, 5):
        one = strength_to_equity(street, 1, 0.7)
        five = strength_to_equity(street, 5, 0.7)
        assert five < one


def test_strength_to_equity_is_a_probability():
    for street in (3, 4, 5):
        for n in (1, 2, 3, 4, 5):
            for s in (0.0, 0.25, 0.5, 0.75, 0.99, 1.0):
                assert 0.0 <= strength_to_equity(street, n, s) <= 1.0


def test_rank_ladder_is_monotone():
    prev = None
    for bb10 in range(-500, 501, 5):
        r = rank_from_bb100(bb10 / 10.0)
        assert 1 <= r <= FIELD_SIZE
        if prev is not None:
            assert r <= prev, "a higher win rate must never yield a worse rank"
        prev = r
    assert rank_from_bb100(1e9) == 1
    assert rank_from_bb100(-1e9) == FIELD_SIZE


def test_synthetic_context_matches_simulator_shape():
    ctx = synthetic_context(30.0, 120, 4, 2)
    for key in ("rank", "bb100", "rank12_bb100", "rank13_bb100", "hands_remaining", "round_no"):
        assert key in ctx
    assert ctx["round_no"] == 4 and ctx["hands_remaining"] == 120
    assert ctx["rank"] <= QUALIFY_RANK  # a strong win rate must look safe
    assert ctx["rank13_bb100"] <= ctx["rank12_bb100"]


def test_context_from_standings_rejects_unusable_payloads():
    assert context_from_standings([], "hero", 100, 1) is None
    assert context_from_standings([{"agentId": "a", "bb100": 1.0}], "a", 100, 1) is None
    assert context_from_standings(None, "a", 100, 1) is None


def test_context_from_standings_ranks_correctly():
    rows = [{"agentId": f"p{i}", "bb100": 100.0 - i} for i in range(24)]
    ctx = context_from_standings(rows, "p3", 55, 6)
    assert ctx is not None
    assert ctx["rank"] == 4
    assert ctx["bb100"] == pytest.approx(97.0)
    assert ctx["rank12_bb100"] == pytest.approx(100.0 - 11)
    assert ctx["hands_remaining"] == 55


def test_boundary_lookup_agrees_with_rank_lookup():
    for rank in (1, 6, 12, 13, 24):
        bb = boundary_bb100(rank)
        assert rank_from_bb100(bb) <= rank + 1
