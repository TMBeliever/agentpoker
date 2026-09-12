import pytest
from dataclasses import asdict
from agentpoker.strategy import StrategyAgent, StrategyParams
from agentpoker.training import StrategyTrainer, ARCHETYPES, _load_params_safe
from agentpoker.engine import NLHEngine


def test_position_threshold_monotonicity_enforcement():
    """Verify _clamp_and_validate enforces UTG <= HJ <= CO <= BTN."""
    trainer = StrategyTrainer(pool_size=12, seed=42)
    inverted = {
        "open_thresh_utg": 0.35,
        "open_thresh_hj": 0.20,
        "open_thresh_co": 0.15,
        "open_thresh_btn": 0.10,
        "open_thresh_sb": 0.05,
        "defend_thresh_bb": 0.50,
        "multiway_decay": 0.50,
        "table_strength_weight": 0.30,
    }
    for k in StrategyTrainer.FIELDS:
        if k not in inverted:
            inverted[k] = 0.5

    trainer._clamp_and_validate(inverted)
    assert inverted["open_thresh_utg"] <= inverted["open_thresh_hj"]
    assert inverted["open_thresh_hj"] <= inverted["open_thresh_co"]
    assert inverted["open_thresh_co"] <= inverted["open_thresh_btn"]


def test_positional_open_rates_in_play():
    """Verify that in simulated hands, hero opens significantly wider on BTN than UTG."""
    p = StrategyParams(
        open_thresh_utg=0.12,
        open_thresh_hj=0.18,
        open_thresh_co=0.26,
        open_thresh_btn=0.52,
    )
    agent = StrategyAgent(p, seed=123)

    utg_opens = 0
    btn_opens = 0
    trials = 200

    for i in range(trials):
        obs_utg = {
            "hero": ["Ah", "7c"],
            "board": [],
            "pot": 300,
            "stack": 20000,
            "big_blind": 200,
            "dealer_seat": 0,
            "position": 3,
            "players": [{"agentId": f"p{j}", "currentBet": 0, "folded": False, "allIn": False} for j in range(6)],
            "legal": {"call": 200, "raise": [400, 20000], "fold": None},
        }
        dec_utg = agent.choose_local(obs_utg)
        if dec_utg["type"] in ("raise", "bet"):
            utg_opens += 1

        obs_btn = {
            "hero": ["Ah", "7c"],
            "board": [],
            "pot": 300,
            "stack": 20000,
            "big_blind": 200,
            "dealer_seat": 0,
            "position": 0,
            "players": [{"agentId": f"p{j}", "currentBet": 0, "folded": False, "allIn": False} for j in range(6)],
            "legal": {"call": 200, "raise": [400, 20000], "fold": None},
        }
        dec_btn = agent.choose_local(obs_btn)
        if dec_btn["type"] in ("raise", "bet"):
            btn_opens += 1

    assert btn_opens > utg_opens


def test_multiway_safety_bluff_shutdown():
    """Verify that pure air bluffs into 3+ opponents are strictly shut down."""
    p = StrategyParams(
        river_bluff_frequency=0.20,
        multiway_decay=0.45,
    )
    agent = StrategyAgent(p, seed=99)

    obs_4way = {
        "hero": ["7c", "3d"],
        "board": ["Ks", "9d", "4c", "2h", "2s"],
        "pot": 1200,
        "stack": 18000,
        "big_blind": 200,
        "players": [
            {"agentId": "hero", "folded": False, "allIn": False},
            {"agentId": "opp1", "folded": False, "allIn": False},
            {"agentId": "opp2", "folded": False, "allIn": False},
            {"agentId": "opp3", "folded": False, "allIn": False},
        ],
        "legal": {"check": None, "bet": [200, 18000]},
    }

    for _ in range(50):
        dec = agent.choose_local(obs_4way)
        assert dec["type"] != "bet", "Pure air bluff should be shut down in 4-way pot!"


def test_bellman_continuous_qualification_pressure():
    """Verify Bellman qualification gradient smoothly shifts pressure based on margin & remaining hands."""
    agent = StrategyAgent(StrategyParams(safety=0.60, attack=0.80), seed=42)

    ctx_safe = {
        "rank": 2,
        "bb100": 35.0,
        "rank12_bb100": -5.0,
        "hands_remaining": 10,
        "round_no": 9,
    }
    p_safe = agent._tournament_pressure(ctx_safe)
    assert p_safe < -0.20

    ctx_behind = {
        "rank": 18,
        "bb100": -15.0,
        "rank12_bb100": 10.0,
        "hands_remaining": 15,
        "round_no": 9,
    }
    p_behind = agent._tournament_pressure(ctx_behind)
    assert p_behind > 0.40


def test_table_strength_modulation():
    """Verify table strength tightens preflop ranges on tough tables and widens on soft tables."""
    agent = StrategyAgent(StrategyParams(table_strength_weight=0.40), seed=77)

    ctx_tough = {"table_strength": 0.8}
    ctx_soft = {"table_strength": -0.8}

    obs_base = {
        "hero": ["Kd", "9d"],
        "board": [],
        "pot": 300,
        "stack": 20000,
        "big_blind": 200,
        "dealer_seat": 0,
        "position": 3,
        "players": [{"agentId": f"p{j}", "currentBet": 0, "folded": False, "allIn": False} for j in range(6)],
        "legal": {"call": 200, "raise": [400, 20000], "fold": None},
    }

    obs_tough = dict(obs_base, context=ctx_tough)
    obs_soft = dict(obs_base, context=ctx_soft)

    tough_raises = sum(1 for _ in range(100) if agent.choose_local(obs_tough)["type"] == "raise")
    soft_raises = sum(1 for _ in range(100) if agent.choose_local(obs_soft)["type"] == "raise")

    assert soft_raises >= tough_raises


def test_backwards_compatibility_load_and_save(tmp_path):
    """Verify older 23-parameter JSONs cleanly load with default v2 parameters."""
    old_23_param_dict = {
        "vpip": 0.22,
        "open_frequency": 0.60,
        "threebet_frequency": 0.08,
        "squeeze_frequency": 0.05,
        "steal_frequency": 0.70,
        "cbet_frequency": 0.60,
        "turn_barrel_frequency": 0.50,
        "river_bluff_frequency": 0.08,
        "value_threshold": 0.65,
        "thin_value_threshold": 0.55,
        "raise_threshold": 0.60,
        "jam_threshold": 0.90,
        "flop_value_threshold": 0.55,
        "turn_value_threshold": 0.62,
        "river_value_threshold": 0.72,
        "open_size": 2.30,
        "cbet_size": 0.45,
        "value_bet_size": 0.68,
        "bluff_bet_size": 0.52,
        "raise_size": 0.65,
        "dry_board_bet_size": 0.30,
        "wet_board_bet_size": 0.72,
        "safety": 0.45,
        "attack": 0.65,
        "bubble_aggression": 0.75,
        "late_aggression": 0.20,
        "temperature": 0.08,
    }

    loaded = _load_params_safe(old_23_param_dict)
    assert loaded.open_thresh_utg == 0.15
    assert loaded.multiway_decay == 0.50

    save_file = tmp_path / "test_v2_model.json"
    agent = StrategyAgent(loaded)
    agent.save(save_file)

    reloaded = StrategyAgent.load(save_file)
    assert reloaded.params.open_thresh_utg == 0.15
    assert reloaded.params.multiway_decay == 0.50
