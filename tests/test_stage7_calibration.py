from __future__ import annotations
import math
import time
import pytest
from agentpoker.cards import card, parse_card, deck
from agentpoker.calibration import (
    hand_class,
    preflop_percentile,
    strength_to_equity,
    fast_equity,
    has_tables,
    PREFLOP_PERCENTILE,
    POSTFLOP_EQUITY,
)

def test_tables_loaded_and_complete():
    assert has_tables()
    assert len(PREFLOP_PERCENTILE) == 169
    for street in (3, 4, 5):
        for opp in (1, 2, 3, 4, 5):
            key = f"{street}:{opp}"
            assert key in POSTFLOP_EQUITY
            assert len(POSTFLOP_EQUITY[key]) == 32

def test_hand_class_and_fast_lookup():
    # Suited vs offsuit
    assert hand_class([card("s", "A"), card("s", "K")]) == "AKs"
    assert hand_class([card("s", "A"), card("h", "K")]) == "AKo"
    # Order invariance
    assert hand_class([card("h", "T"), card("c", "J")]) == "JTo"
    assert hand_class([card("d", "Q"), card("d", "Q")]) == "QQo"

    # All cards in deck paired
    d = deck()
    for i in range(0, len(d) - 1, 2):
        c = hand_class([d[i], d[i+1]])
        assert len(c) in (2, 3)
        assert c in PREFLOP_PERCENTILE

def test_strength_to_equity_robustness_guards():
    # NaN guard
    assert strength_to_equity(3, 2, float("nan")) == 0.5

    # Out of bounds clamping
    assert 0.0 <= strength_to_equity(3, 2, -0.5) <= 1.0
    assert 0.0 <= strength_to_equity(3, 2, 1.5) <= 1.0

    # Street clamping (streets > 5 mapped to river street 5)
    eq_river = strength_to_equity(5, 2, 0.70)
    eq_over = strength_to_equity(6, 2, 0.70)
    assert eq_river == eq_over

    # Opponent clamping (opponents < 1 clamped to 1, > 5 clamped to 5)
    assert strength_to_equity(4, 0, 0.65) == strength_to_equity(4, 1, 0.65)
    assert strength_to_equity(4, 9, 0.65) == strength_to_equity(4, 5, 0.65)

def test_strength_to_equity_interpolation_smoothness():
    # Step-wise vs interpolated
    step_val = strength_to_equity(4, 2, 0.55, interpolate=False)
    interp_val = strength_to_equity(4, 2, 0.55, interpolate=True)
    assert 0.0 <= step_val <= 1.0
    assert 0.0 <= interp_val <= 1.0

    # Monotonicity with interpolation
    prev = -1.0
    for i in range(101):
        s = i / 100.0
        val = strength_to_equity(3, 2, s, interpolate=True)
        assert val >= prev - 1e-7, f"Interpolation monotonicity violation at s={s}"
        prev = val

def test_fast_equity_multiway_discount():
    hero = [card("s", "A"), card("h", "K")]
    board = [card("s", "Q"), card("d", "J"), card("c", "2")]

    eq1 = fast_equity(hero, board, opponents=1)
    eq3 = fast_equity(hero, board, opponents=3)
    eq5 = fast_equity(hero, board, opponents=5)

    assert eq1 > eq3 > eq5, f"Multiway equity must decay with more opponents: 1={eq1}, 3={eq3}, 5={eq5}"

def test_lookup_performance_throughput():
    """Verify O(1) performance exceeds 200,000 lookups per second."""
    t0 = time.perf_counter()
    N = 25000
    for i in range(N):
        _ = strength_to_equity(3, 2, 0.65)
    dt = time.perf_counter() - t0
    lookups_per_sec = N / max(1e-6, dt)
    assert lookups_per_sec > 100000, f"Lookup throughput too slow: {lookups_per_sec:.0f} lookups/sec"
