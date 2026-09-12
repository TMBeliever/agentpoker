from __future__ import annotations
import math
import pytest
from agentpoker.engine import NLHEngine
from agentpoker.training import ARCHETYPES
from agentpoker.strategy import StrategyAgent
from agentpoker.profiler import OpponentProfiler


def test_opponent_profiler_engine_replay_10000_hands():
    """Stage 2 Gate: Rigorous 10,000-hand NLHEngine replay across 6 archetypes.
    
    Verifies that real engine action histories streamed into OpponentProfiler
    satisfy all mathematical invariants across all tracked metrics:
      - 0 <= rate <= 1.0
      - 0 <= smoothed_rate <= 1.0
      - 0 <= confidence <= 1.0
      - count <= opportunities
      - opportunities >= 0
      - if count > 0 then opportunities > 0
      - No NaN, Inf, or ZeroDivisionError in any state.
    """
    agents = {k: StrategyAgent(params) for k, params in ARCHETYPES.items()}
    names = list(ARCHETYPES.keys())
    assert len(names) == 6, f"Expected 6 archetypes, got {len(names)}"

    stacks = {name: 20000 for name in names}
    engine = NLHEngine(100, 200, seed=2026)
    profiler = OpponentProfiler()
    seat_map = {i: name for i, name in enumerate(names)}

    total_hands = 10000
    for i in range(total_hands):
        res, dealer = engine.play_hand(names, stacks, i % len(names), agents)

        actions_list = [
            {"agentId": seat_map[a.seat], "type": a.type, "amount": a.amount, "street": a.street}
            for a in res.actions
        ]
        players_list = [
            {
                "agentId": name,
                "name": name,
                "seatIndex": idx,
                "startingStack": stacks[name],
                "netChange": res.final_stacks[name] - stacks[name],
            }
            for idx, name in enumerate(names)
        ]
        folded = {seat_map[a.seat] for a in res.actions if a.type == "fold"}
        active_at_end = [n for n in names if n not in folded]
        showdown_list = active_at_end if len(active_at_end) > 1 else []

        hand_payload = {
            "actions": actions_list,
            "players": players_list,
            "showdown": [{"agentId": aid, "amount": res.payouts.get(aid, 0)} for aid in showdown_list],
            "payouts": res.payouts,
            "board": [str(c) for c in res.board],
        }
        profiler.ingest_hand(hand_payload)

    profiles = profiler.export()
    assert len(profiles) == 6, f"Expected 6 profiled agents, got {len(profiles)}"

    for aid, prof in profiles.items():
        assert prof["hands"] == total_hands, f"Expected {total_hands} hands for {aid}, got {prof['hands']}"
        metrics = prof["metrics"]

        # Ensure all core metrics are tracked
        core_metric_keys = [
            "vpip",
            "pfr",
            "threebet",
            "fold_to_threebet",
            "cbet_flop",
            "fold_to_cbet",
            "turn_barrel",
            "fold_to_turn",
            "river_bet",
            "fold_to_river",
            "wtsd",
            "wsd",
        ]
        for key in core_metric_keys:
            assert key in metrics, f"Metric '{key}' missing from profile of {aid}"
            m = metrics[key]

            count = m["count"]
            opps = m["opportunities"]
            rate = m["rate"]
            smoothed = m["smoothed_rate"]
            conf = m["confidence"]

            # Mathematical Invariant 1: 0 <= rate <= 1.0
            assert 0.0 <= rate <= 1.0, f"{aid} {key} rate {rate} not in [0, 1]"
            assert 0.0 <= smoothed <= 1.0, f"{aid} {key} smoothed_rate {smoothed} not in [0, 1]"
            assert 0.0 <= conf <= 1.0, f"{aid} {key} confidence {conf} not in [0, 1]"

            # Mathematical Invariant 2: count <= opportunities
            assert count <= opps, f"{aid} {key} count {count} > opps {opps}"

            # Mathematical Invariant 3: opportunities >= 0
            assert opps >= 0, f"{aid} {key} opps {opps} < 0"

            # Mathematical Invariant 4: count > 0 => opportunities > 0
            if count > 0:
                assert opps > 0, f"{aid} {key} count {count} > 0 but opps {opps} <= 0"

            # Mathematical Invariant 5: No NaN or Inf in any state
            assert not math.isnan(rate), f"{aid} {key} rate is NaN"
            assert not math.isnan(smoothed), f"{aid} {key} smoothed_rate is NaN"
            assert not math.isnan(conf), f"{aid} {key} confidence is NaN"
            assert not math.isinf(rate), f"{aid} {key} rate is Inf"
            assert not math.isinf(smoothed), f"{aid} {key} smoothed_rate is Inf"
            assert not math.isinf(conf), f"{aid} {key} confidence is Inf"
