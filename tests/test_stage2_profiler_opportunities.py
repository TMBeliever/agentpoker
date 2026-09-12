from __future__ import annotations
import pytest
from pathlib import Path
import json
from agentpoker.profiler import OpponentProfiler, StatMetric
from agentpoker.strategy import OpponentStats, StrategyAgent

def _generate_100_hand_dataset() -> list[dict]:
    """Generates a deterministic 100-hand dataset with 100% analytically hand-calculated metrics.
    
    6 Players:
    - utg: agent_utg
    - mp:  agent_mp
    - co:  agent_co
    - btn: agent_btn
    - sb:  agent_sb
    - bb:  agent_bb

    Structure of the 100 hands:
    - Hands 1-30 (30 hands) [Scenario A]:
      * Preflop: UTG opens 400. MP, CO, BTN, SB fold. BB calls 200.
      * Flop: BB checks. UTG bets 500 (cbet). BB folds.
      * Analytical consequences:
        - UTG: hands=30, preflop_opps=30, vpip=30, pfr_opps=30, pfr=30, saw_flop=30, cbet_opps=30, cbet=30
        - BB: hands=30, preflop_opps=30, vpip=30, pfr_opps=0, threebet_opps=30, threebet=0, saw_flop=30, fold_to_cbet_opps=30, fold_to_cbet=30
        - Others (MP, CO, BTN, SB): hands=30, preflop_opps=30, vpip=0, threebet_opps=30, threebet=0, saw_flop=0

    - Hands 31-50 (20 hands) [Scenario B]:
      * Preflop: UTG, MP, CO fold. BTN opens 400 (open raise). SB 3-bets to 1200. BB folds. BTN folds (fold to 3-bet).
      * Analytical consequences:
        - UTG, MP, CO: preflop_opps=20, pfr_opps=20, pfr=0, vpip=0
        - BTN: preflop_opps=20, pfr_opps=20, pfr=20, vpip=20, fold_to_threebet_opps=20, fold_to_threebet=20
        - SB: preflop_opps=20, threebet_opps=20, threebet=20, vpip=20
        - BB: preflop_opps=20, threebet_opps=20, threebet=0, vpip=0
        - Nobody saw flop.

    - Hands 51-70 (20 hands) [Scenario C]:
      * Preflop: UTG, MP, CO fold. BTN opens 400. SB folds. BB calls 200.
      * Flop: BB checks. BTN checks (c-bet opportunity passed).
      * Turn: BB checks. BTN bets 600 (turn bet). BB calls 600.
      * River: BB checks. BTN bets 1200 (river bet). BB folds.
      * Analytical consequences:
        - BTN: vpip=20, pfr_opps=20, pfr=20. saw_flop=20, cbet_opps=20, cbet=0. saw_turn=20, turn_bet_opps=20, turn_bet=20. saw_river=20, river_bet_opps=20, river_bet=20.
        - BB: vpip=20, threebet_opps=20, threebet=0. saw_flop=20, fold_to_cbet_opps=0. saw_turn=20, saw_river=20, fold_to_river_opps=20, fold_to_river=20.

    - Hands 71-100 (30 hands) [Scenario D]:
      * Preflop: UTG, MP, CO fold. BTN opens 400. SB folds. BB calls 200.
      * Flop: BB checks. BTN bets 500 (cbet). BB calls 500.
      * Turn: BB checks. BTN checks (turn barrel passed).
      * River: BB checks. BTN checks.
      * Showdown: Both reach showdown! BB wins showdown (netChange = +1400, BTN netChange = -1400).
      * Analytical consequences:
        - BTN: vpip=30, pfr_opps=30, pfr=30. saw_flop=30, cbet_opps=30, cbet=30. saw_turn=30, turn_barrel_opps=30, turn_barrel=0. saw_river=30, reached showdown=30, wsd_opps=30, wsd=0.
        - BB: vpip=30, threebet_opps=30, threebet=0. saw_flop=30, fold_to_cbet_opps=30, fold_to_cbet=0. saw_turn=30, saw_river=30, reached showdown=30, wsd_opps=30, wsd=30.
    """
    hands = []
    players = [
        {"agentId": "agent_utg", "name": "UTG_Bot", "seatIndex": 0, "startingStack": 20000, "netChange": 0},
        {"agentId": "agent_mp", "name": "MP_Bot", "seatIndex": 1, "startingStack": 20000, "netChange": 0},
        {"agentId": "agent_co", "name": "CO_Bot", "seatIndex": 2, "startingStack": 20000, "netChange": 0},
        {"agentId": "agent_btn", "name": "BTN_Bot", "seatIndex": 3, "startingStack": 20000, "netChange": 0},
        {"agentId": "agent_sb", "name": "SB_Bot", "seatIndex": 4, "startingStack": 20000, "netChange": 0},
        {"agentId": "agent_bb", "name": "BB_Bot", "seatIndex": 5, "startingStack": 20000, "netChange": 0},
    ]

    # Scenario A: Hands 1-30
    for i in range(1, 31):
        h_players = [dict(p) for p in players]
        h_players[0]["netChange"] = 400  # UTG wins BB + blinds
        h_players[5]["netChange"] = -400 # BB loses call
        actions = [
            {"street": "preflop", "agentId": "agent_sb", "type": "smallBlind", "amount": 100},
            {"street": "preflop", "agentId": "agent_bb", "type": "bigBlind", "amount": 200},
            {"street": "preflop", "agentId": "agent_utg", "type": "raise", "amount": 400},
            {"street": "preflop", "agentId": "agent_mp", "type": "fold"},
            {"street": "preflop", "agentId": "agent_co", "type": "fold"},
            {"street": "preflop", "agentId": "agent_btn", "type": "fold"},
            {"street": "preflop", "agentId": "agent_sb", "type": "fold"},
            {"street": "preflop", "agentId": "agent_bb", "type": "call", "amount": 200},
            {"street": "flop", "agentId": "agent_bb", "type": "check"},
            {"street": "flop", "agentId": "agent_utg", "type": "bet", "amount": 500},
            {"street": "flop", "agentId": "agent_bb", "type": "fold"},
        ]
        hands.append({
            "id": f"hand_{i}",
            "players": h_players,
            "actions": actions,
        })

    # Scenario B: Hands 31-50
    for i in range(31, 51):
        h_players = [dict(p) for p in players]
        h_players[4]["netChange"] = 600  # SB wins 3-bet uncontested
        h_players[3]["netChange"] = -400 # BTN loses open
        actions = [
            {"street": "preflop", "agentId": "agent_sb", "type": "smallBlind", "amount": 100},
            {"street": "preflop", "agentId": "agent_bb", "type": "bigBlind", "amount": 200},
            {"street": "preflop", "agentId": "agent_utg", "type": "fold"},
            {"street": "preflop", "agentId": "agent_mp", "type": "fold"},
            {"street": "preflop", "agentId": "agent_co", "type": "fold"},
            {"street": "preflop", "agentId": "agent_btn", "type": "raise", "amount": 400},
            {"street": "preflop", "agentId": "agent_sb", "type": "raise", "amount": 1200},
            {"street": "preflop", "agentId": "agent_bb", "type": "fold"},
            {"street": "preflop", "agentId": "agent_btn", "type": "fold"},
        ]
        hands.append({
            "id": f"hand_{i}",
            "players": h_players,
            "actions": actions,
        })

    # Scenario C: Hands 51-70
    for i in range(51, 71):
        h_players = [dict(p) for p in players]
        h_players[3]["netChange"] = 1200
        h_players[5]["netChange"] = -1200
        actions = [
            {"street": "preflop", "agentId": "agent_sb", "type": "smallBlind", "amount": 100},
            {"street": "preflop", "agentId": "agent_bb", "type": "bigBlind", "amount": 200},
            {"street": "preflop", "agentId": "agent_utg", "type": "fold"},
            {"street": "preflop", "agentId": "agent_mp", "type": "fold"},
            {"street": "preflop", "agentId": "agent_co", "type": "fold"},
            {"street": "preflop", "agentId": "agent_btn", "type": "raise", "amount": 400},
            {"street": "preflop", "agentId": "agent_sb", "type": "fold"},
            {"street": "preflop", "agentId": "agent_bb", "type": "call", "amount": 200},
            {"street": "flop", "agentId": "agent_bb", "type": "check"},
            {"street": "flop", "agentId": "agent_btn", "type": "check"},
            {"street": "turn", "agentId": "agent_bb", "type": "check"},
            {"street": "turn", "agentId": "agent_btn", "type": "bet", "amount": 600},
            {"street": "turn", "agentId": "agent_bb", "type": "call", "amount": 600},
            {"street": "river", "agentId": "agent_bb", "type": "check"},
            {"street": "river", "agentId": "agent_btn", "type": "bet", "amount": 1200},
            {"street": "river", "agentId": "agent_bb", "type": "fold"},
        ]
        hands.append({
            "id": f"hand_{i}",
            "players": h_players,
            "actions": actions,
        })

    # Scenario D: Hands 71-100
    for i in range(71, 101):
        h_players = [dict(p) for p in players]
        h_players[5]["netChange"] = 1500 # BB wins showdown
        h_players[3]["netChange"] = -1500
        actions = [
            {"street": "preflop", "agentId": "agent_sb", "type": "smallBlind", "amount": 100},
            {"street": "preflop", "agentId": "agent_bb", "type": "bigBlind", "amount": 200},
            {"street": "preflop", "agentId": "agent_utg", "type": "fold"},
            {"street": "preflop", "agentId": "agent_mp", "type": "fold"},
            {"street": "preflop", "agentId": "agent_co", "type": "fold"},
            {"street": "preflop", "agentId": "agent_btn", "type": "raise", "amount": 400},
            {"street": "preflop", "agentId": "agent_sb", "type": "fold"},
            {"street": "preflop", "agentId": "agent_bb", "type": "call", "amount": 200},
            {"street": "flop", "agentId": "agent_bb", "type": "check"},
            {"street": "flop", "agentId": "agent_btn", "type": "bet", "amount": 500},
            {"street": "flop", "agentId": "agent_bb", "type": "call", "amount": 500},
            {"street": "turn", "agentId": "agent_bb", "type": "check"},
            {"street": "turn", "agentId": "agent_btn", "type": "check"},
            {"street": "river", "agentId": "agent_bb", "type": "check"},
            {"street": "river", "agentId": "agent_btn", "type": "check"},
        ]
        hands.append({
            "id": f"hand_{i}",
            "players": h_players,
            "actions": actions,
            "showdown": [
                {"agentId": "agent_bb", "amount": 2900},
                {"agentId": "agent_btn", "amount": 0},
            ],
            "result": {
                "payouts": [{"agentId": "agent_bb", "amount": 2900}]
            }
        })

    return hands

def test_100_hand_fixture_analytic_verification(tmp_path):
    """Gate 2: Rigorously verify that 100-hand fixture opportunity metrics match exact analytical hand-calculated results."""
    hands = _generate_100_hand_dataset()
    assert len(hands) == 100

    dataset_file = tmp_path / "hands_100.jsonl"
    with open(dataset_file, "w", encoding="utf-8") as f:
        for h in hands:
            f.write(json.dumps(h) + "\n")

    profiler = OpponentProfiler()
    ingested = profiler.ingest_file(dataset_file)
    assert ingested == 100

    profiles = profiler.export(min_hands=1)
    assert len(profiles) == 6

    # 1. Verify agent_utg analytical expectations
    utg = profiles["agent_utg"]
    assert utg["hands"] == 100
    assert utg["vpip_count"] == 30
    assert utg["vpip_opps"] == 100
    assert utg["metrics"]["vpip"]["rate"] == 0.30
    assert utg["pfr_count"] == 30
    assert utg["pfr_opps"] == 100
    assert utg["metrics"]["pfr"]["rate"] == 0.30
    assert utg["cbet_count"] == 30
    assert utg["cbet_opps"] == 30 # Exactly 30 opportunities (hands 1-30), NOT 100!
    assert utg["metrics"]["cbet_flop"]["rate"] == 1.00
    assert utg["wtsd_opps"] == 30 # Flops seen = 30
    assert utg["wtsd_count"] == 0

    # 2. Verify agent_btn analytical expectations
    btn = profiles["agent_btn"]
    assert btn["hands"] == 100
    # In hands 1-30: faced UTG open (no pfr opp)
    # In hands 31-100: unraised pot, opened all 70 hands
    assert btn["pfr_opps"] == 70 # Hands with open opportunity
    assert btn["pfr_count"] == 70
    assert btn["metrics"]["pfr"]["rate"] == 1.00
    # 3-bet opportunities: faced open in hands 1-30 (30 times)
    assert btn["threebet_opps"] == 30
    assert btn["threebet_count"] == 0
    assert btn["metrics"]["threebet"]["rate"] == 0.00
    # Fold to 3-bet: opened in hands 31-50 (20 times) and faced SB 3-bet
    assert btn["fold_to_threebet_opps"] == 20
    assert btn["fold_to_threebet_count"] == 20
    assert btn["metrics"]["fold_to_threebet"]["rate"] == 1.00
    # C-Bet on flop: saw flop in 51-70 (20 checked) and 71-100 (30 bet) = 50 opportunities
    assert btn["cbet_opps"] == 50 # NOT 100!
    assert btn["cbet_count"] == 30 # Hands 71-100
    assert btn["metrics"]["cbet_flop"]["rate"] == 0.60
    # Showdown: saw flop in 50 hands, reached showdown in 30 hands (71-100)
    assert btn["wtsd_opps"] == 50 # Flops seen
    assert btn["wtsd_count"] == 30 # Showdowns reached
    assert btn["metrics"]["wtsd"]["rate"] == 0.60
    assert btn["wsd_opps"] == 30
    assert btn["wsd_count"] == 0
    assert btn["metrics"]["wsd"]["rate"] == 0.00

    # 3. Verify agent_bb analytical expectations
    bb = profiles["agent_bb"]
    assert bb["hands"] == 100
    # VPIP: called in hands 1-30 (30) + 51-70 (20) + 71-100 (30) = 80
    assert bb["vpip_count"] == 80
    assert bb["vpip_opps"] == 100
    assert bb["metrics"]["vpip"]["rate"] == 0.80
    # PFR: faced raise in all hands, never had open opportunity
    assert bb["pfr_opps"] == 0
    assert bb["pfr_count"] == 0
    # Fold to Flop C-Bet: faced cbet in hands 1-30 (30 folded) and hands 71-100 (30 called) = 60 opps
    assert bb["fold_to_cbet_opps"] == 60 # NOT 100 hands, NOT 80 flops seen! Exactly 60!
    assert bb["fold_to_cbet_count"] == 30 # Folded in 1-30
    assert bb["metrics"]["fold_to_cbet"]["rate"] == 0.50 # Exactly 30 / 60 = 0.50
    # Fold to River Bet: faced river bet in 51-70 (20 times, folded all 20)
    assert bb["fold_to_river_opps"] == 20
    assert bb["fold_to_river_count"] == 20
    assert bb["metrics"]["fold_to_river"]["rate"] == 1.00
    # Showdown: saw flop 80 times, reached showdown 30 times (71-100)
    assert bb["wtsd_opps"] == 80
    assert bb["wtsd_count"] == 30
    assert bb["metrics"]["wtsd"]["rate"] == 30 / 80 # 0.375
    # Won at Showdown: reached 30 times, won 30 times
    assert bb["wsd_opps"] == 30
    assert bb["wsd_count"] == 30
    assert bb["metrics"]["wsd"]["rate"] == 1.00

def test_bayesian_confidence_and_smoothed_shrinkage_formula():
    """Verify that Bayesian shrinkage formula and confidence score behave with mathematical precision."""
    # Prior weight = 8.0, prior = 0.25
    m = StatMetric(name="vpip", count=10, opportunities=20, population_prior=0.25, prior_weight=8.0)
    assert m.rate == 0.50
    # Confidence: opps / (opps + weight) = 20 / 28 = 0.7143
    assert abs(m.confidence - (20.0 / 28.0)) < 1e-3
    # Smoothed rate: (count + weight * prior) / (opps + weight) = (10 + 8 * 0.25) / 28 = 12 / 28 = 0.4286
    expected_smoothed = (10.0 + 8.0 * 0.25) / 28.0
    assert abs(m.smoothed_rate - expected_smoothed) < 1e-3

def test_small_sample_stability_and_no_nan_or_wild_jumps():
    """Verify small sample behavior at 0, 3, 10, 100 hands: no NaNs, no extreme jumps, strict monotonic confidence."""
    # 0 hands (completely unobserved)
    m0 = StatMetric(name="cbet_flop", count=0, opportunities=0, population_prior=0.55, prior_weight=8.0)
    assert m0.confidence == 0.0
    assert m0.smoothed_rate == 0.55 # Reverts to exact prior
    assert not (m0.smoothed_rate != m0.smoothed_rate) # Not NaN

    # 3 hands (all 3 were c-bets): without shrinkage, 100% c-bet rate would be a wild distortion
    m3 = StatMetric(name="cbet_flop", count=3, opportunities=3, population_prior=0.55, prior_weight=8.0)
    assert m3.rate == 1.0
    assert abs(m3.confidence - (3.0 / 11.0)) < 1e-3
    # Smoothed rate = (3 + 8 * 0.55) / 11 = 7.4 / 11 ≈ 0.6727 (regularized gently towards 0.55)
    assert 0.65 < m3.smoothed_rate < 0.70

    # 10 hands (all 10 were c-bets)
    m10 = StatMetric(name="cbet_flop", count=10, opportunities=10, population_prior=0.55, prior_weight=8.0)
    assert m10.confidence > m3.confidence # Monotonic increase in confidence
    assert abs(m10.confidence - (10.0 / 18.0)) < 1e-3
    # Smoothed rate = (10 + 4.4) / 18 = 14.4 / 18 = 0.80

    # 100 hands (all 100 were c-bets)
    m100 = StatMetric(name="cbet_flop", count=100, opportunities=100, population_prior=0.55, prior_weight=8.0)
    assert m100.confidence > 0.90 # Over 90% confidence
    assert m100.smoothed_rate > 0.95 # Converges near observed empirical rate

def test_opportunity_vs_hands_denominators():
    """Explicitly verify that conditional poker metrics do NOT use hands as their denominator."""
    profiler = OpponentProfiler()
    # 50 hands where player folds preflop every hand
    for _ in range(50):
        profiler.ingest_hand({
            "players": [{"agentId": "tight_player"}],
            "actions": [{"street": "preflop", "agentId": "tight_player", "type": "fold"}]
        })
    profiles = profiler.export()
    tp = profiles["tight_player"]
    assert tp["hands"] == 50
    assert tp["cbet_opps"] == 0 # Has 0 cbet opportunities, NOT 50 hands!
    assert tp["metrics"]["cbet_flop"]["opportunities"] == 0
    assert tp["metrics"]["cbet_flop"]["smoothed_rate"] == 0.55 # Prior, NOT 0.0 or div-by-zero!
    assert tp["metrics"]["fold_to_cbet"]["opportunities"] == 0
    assert tp["wtsd_opps"] == 0 # Saw flop 0 times, NOT 50 hands!

def test_street_actions_tracking():
    """Verify that street_actions breakdown tracks every street and action type accurately."""
    profiler = OpponentProfiler()
    profiler.ingest_hand({
        "players": [{"agentId": "active_agent"}],
        "actions": [
            {"street": "preflop", "agentId": "active_agent", "type": "raise", "amount": 400},
            {"street": "flop", "agentId": "active_agent", "type": "bet", "amount": 500},
            {"street": "turn", "agentId": "active_agent", "type": "check"},
            {"street": "river", "agentId": "active_agent", "type": "bet", "amount": 1000},
        ]
    })
    profiles = profiler.export()
    sa = profiles["active_agent"]["street_actions"]
    assert sa["preflop"]["raises"] == 1
    assert sa["flop"]["bets"] == 1
    assert sa["turn"]["checks"] == 1
    assert sa["river"]["bets"] == 1

def test_opponent_stats_smoothed_profile_integration():
    """Verify that OpponentStats in StrategyAgent seamlessly integrates with exported opportunity profiles."""
    profiles_dict = {
        "fish_station": {
            "hands": 80,
            "preflop_opps": 80,
            "vpip_count": 65,
            "pfr_opps": 40,
            "pfr_count": 5,
            "threebet_opps": 40,
            "threebet_count": 1,
            "cbet_opps": 10,
            "cbet_count": 2,
            "fold_to_cbet_opps": 50,
            "fold_to_cbet_count": 10, # Folds to cbet only 20% of the time (station!)
            "wtsd_opps": 60,
            "wtsd_count": 40, # Reaches showdown 66% of the time
            "calls_count": 70,
            "folds_count": 15,
            "raises_count": 6,
            "bets_count": 4,
            "checks_count": 20,
        }
    }

    agent = StrategyAgent()
    loaded = agent.load_opponent_profiles(profiles_dict)
    assert loaded == 1
    assert "fish_station" in agent.opponents

    stats = agent.opponents["fish_station"]
    assert stats.cbet_opps == 10
    assert stats.fold_to_cbet_opps == 50
    assert stats.fold_to_cbet_count == 10

    prof = stats.smoothed_profile()
    assert prof["fold_to_cbet"] < 0.35 # Clearly detected as calling station
    assert prof["is_station"] is True
