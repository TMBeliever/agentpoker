import json
from pathlib import Path
from dataclasses import asdict
from agentpoker.cards import card, evaluate_relative_strength
from agentpoker.strategy import StrategyAgent, StrategyParams
from agentpoker.training import StrategyTrainer

def test_legacy_champion_backward_compatibility():
    """Verify loading legacy models seamlessly backfills missing fields without errors."""
    champ_path = Path("models/champion.json")
    assert champ_path.exists(), "models/champion.json must exist"
    
    agent = StrategyAgent.load(champ_path)
    assert isinstance(agent.params, StrategyParams)
    assert hasattr(agent.params, "flop_value_threshold")
    assert hasattr(agent.params, "turn_value_threshold")
    assert hasattr(agent.params, "river_value_threshold")
    assert hasattr(agent.params, "dry_board_bet_size")
    assert hasattr(agent.params, "wet_board_bet_size")
    assert agent.params.flop_value_threshold == 0.58
    assert agent.params.turn_value_threshold == 0.65
    assert agent.params.river_value_threshold == 0.74
    assert agent.params.dry_board_bet_size == 0.33
    assert agent.params.wet_board_bet_size == 0.75

    obs = {
        "legal": {"check": None, "bet": (200, 2000)},
        "hero": ["Ah", "Kd"],
        "board": ["As", "7c", "2d"],
        "pot": 600,
        "big_blind": 200,
        "players": [{"agentId": "hero"}, {"agentId": "opp1"}],
        "agentId": "hero"
    }
    decision = agent.choose(obs)
    assert decision["type"] in ("bet", "check")

def test_street_specific_value_thresholds():
    """Verify that flop and turn decisions dynamically observe their respective street thresholds."""
    # When flop threshold is very loose (0.45), hero value bets flop at high rate.
    # When flop threshold is very tight (0.90), hero checks flop.
    loose_flop_agent = StrategyAgent(StrategyParams(flop_value_threshold=0.45, turn_value_threshold=0.90), seed=42)
    tight_flop_agent = StrategyAgent(StrategyParams(flop_value_threshold=0.90, turn_value_threshold=0.45), seed=42)

    hero = ["Kc", "Qd"]
    flop = ["Ks", "8c", "2d"]

    obs_flop = {
        "legal": {"check": None, "bet": (200, 2000)},
        "hero": hero,
        "board": flop,
        "pot": 600,
        "big_blind": 200,
        "players": [{"agentId": "hero"}, {"agentId": "opp1"}],
        "agentId": "hero"
    }

    # Over multiple trials with varied seeds, loose agent must bet significantly more on flop
    loose_bets = sum(
        1 for i in range(40)
        if StrategyAgent(StrategyParams(flop_value_threshold=0.45, turn_value_threshold=0.90), seed=i).choose_local(obs_flop)["type"] == "bet"
    )
    tight_bets = sum(
        1 for i in range(40)
        if StrategyAgent(StrategyParams(flop_value_threshold=0.90, turn_value_threshold=0.45), seed=i).choose_local(obs_flop)["type"] == "bet"
    )
    assert loose_bets > tight_bets * 1.5, f"loose_bets: {loose_bets}, tight_bets: {tight_bets}"

def test_blocker_effects_detection():
    """Verify nut flush blocker accurately detects the unseen highest card of the flush suit."""
    board1 = [card("s", "8"), card("s", "7"), card("s", "2")]
    hero_with_ace = [card("s", "A"), card("d", "K")]
    hero_with_king = [card("s", "K"), card("d", "Q")]

    eval1_ace = evaluate_relative_strength(hero_with_ace, board1)
    eval1_king = evaluate_relative_strength(hero_with_king, board1)
    assert eval1_ace["blocker_effects"]["has_nut_flush_blocker"] is True
    assert eval1_king["blocker_effects"]["has_nut_flush_blocker"] is False

    board2 = [card("s", "A"), card("s", "7"), card("s", "2")]
    eval2_king = evaluate_relative_strength(hero_with_king, board2)
    eval2_queen = evaluate_relative_strength([card("s", "Q"), card("d", "J")], board2)
    assert eval2_king["blocker_effects"]["has_nut_flush_blocker"] is True
    assert eval2_queen["blocker_effects"]["has_nut_flush_blocker"] is False

    board3 = [card("s", "A"), card("h", "7"), card("d", "2")]
    eval3 = evaluate_relative_strength(hero_with_ace, board3)
    assert eval3["blocker_effects"]["has_nut_flush_blocker"] is False

def test_blocker_effects_river_bluff_and_defense():
    """Verify nut flush blocker suppresses bluffs vs station but enables bluffs vs fold-heavy opponents."""
    board = ["8s", "7s", "2s", "4c", "Jh"]
    hero_blocker = ["As", "3d"]
    hero_no_blocker = ["Ad", "3d"]

    station_profile = {"opp_station": {"hands": 50, "calls_count": 35, "folds_count": 5, "raises_count": 5, "vpip_count": 40}}
    nit_profile = {"opp_nit": {"hands": 50, "calls_count": 10, "folds_count": 35, "raises_count": 5, "vpip_count": 12}}

    def bet_rate(hero, prof, opp_id, trials=50):
        bets = 0
        for i in range(trials):
            agent = StrategyAgent(StrategyParams(river_bluff_frequency=0.20, temperature=0.0), seed=i, profiles=prof)
            obs = {
                "legal": {"check": None, "bet": (200, 2000)},
                "hero": hero,
                "board": board,
                "pot": 800,
                "big_blind": 200,
                "players": [{"agentId": "hero"}, {"agentId": opp_id}],
                "agentId": "hero"
            }
            if agent.choose_local(obs)["type"] == "bet":
                bets += 1
        return bets / trials

    rate_station = bet_rate(hero_blocker, station_profile, "opp_station")
    rate_nit_blocker = bet_rate(hero_blocker, nit_profile, "opp_nit")
    rate_nit_no_blocker = bet_rate(hero_no_blocker, nit_profile, "opp_nit")

    # Defense: Never bluff a calling station even with blocker
    assert rate_station == 0.0, f"Rate vs station should be 0.0, got {rate_station}"
    # Exploitation: Blocker significantly boosts river bluff frequency vs nits
    assert rate_nit_blocker > rate_nit_no_blocker + 0.10, f"Blocker: {rate_nit_blocker}, No Blocker: {rate_nit_no_blocker}"

def test_board_texture_bet_sizing():
    """Verify bet size dynamically scales with board texture wetness."""
    agent = StrategyAgent(StrategyParams(
        dry_board_bet_size=0.30,
        wet_board_bet_size=0.80,
        value_bet_size=0.60
    ), seed=1)

    legal = {"bet": (200, 2000)}
    dry_bet = agent._sized_bet(legal, value=True, pot=1000, bb_size=200, street=3, wetness=0.1)
    wet_bet = agent._sized_bet(legal, value=True, pot=1000, bb_size=200, street=3, wetness=0.9)

    assert dry_bet["type"] == "bet"
    assert wet_bet["type"] == "bet"
    assert wet_bet["amount"] > dry_bet["amount"] * 1.35, f"dry: {dry_bet[amount]}, wet: {wet_bet[amount]}"

def test_trainer_monotonicity_invariants():
    """Verify StrategyTrainer enforces street value threshold and texture sizing monotonicity."""
    trainer = StrategyTrainer(seed=42, pool_size=12)
    bad_params = {
        "flop_value_threshold": 0.75,
        "turn_value_threshold": 0.60,
        "river_value_threshold": 0.55,
        "dry_board_bet_size": 0.50,
        "wet_board_bet_size": 0.30,
        "value_threshold": 0.68,
        "thin_value_threshold": 0.67,
        "jam_threshold": 0.70,
        "value_bet_size": 0.70,
        "bluff_bet_size": 0.85,
    }
    for f in StrategyTrainer.FIELDS:
        if f not in bad_params:
            bad_params[f] = 0.5

    trainer._clamp_and_validate(bad_params)
    assert bad_params["turn_value_threshold"] >= bad_params["flop_value_threshold"] + 0.02
    assert bad_params["river_value_threshold"] >= bad_params["turn_value_threshold"] + 0.02
    assert bad_params["wet_board_bet_size"] >= bad_params["dry_board_bet_size"] + 0.10
