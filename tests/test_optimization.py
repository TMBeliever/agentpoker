import json
from pathlib import Path
from agentpoker.cards import card, evaluate_relative_strength
from agentpoker.strategy import StrategyAgent, StrategyParams, OpponentStats
from agentpoker.profiler import OpponentProfiler

def test_relative_hand_strength_differentiation():
    # Board: Ah 7s 2c
    board = [card("h", "A"), card("s", "7"), card("c", "2")]
    
    # 1. AK: Top pair top kicker
    ak = [card("c", "A"), card("d", "K")]
    res_ak = evaluate_relative_strength(ak, board)
    assert res_ak["tier"] == "top_pair_good"
    assert res_ak["strength"] >= 0.68

    # 2. 23: Bottom pair weak kicker
    w23 = [card("h", "2"), card("d", "3")]
    res_23 = evaluate_relative_strength(w23, board)
    assert res_23["tier"] == "bottom_pair"
    assert res_23["strength"] < 0.42

    # Verify AK strength is substantially higher than 23 (unlike old 0.47 for both)
    assert res_ak["strength"] > res_23["strength"] + 0.25

    # 3. KK: Second pocket pair (under the Ace)
    kk = [card("c", "K"), card("d", "K")]
    res_kk = evaluate_relative_strength(kk, board)
    assert res_kk["tier"] == "second_pocket_pair"
    assert 0.50 <= res_kk["strength"] <= 0.60

    # 4. Nut flush draw (board has 2 hearts + hero has 2 hearts = 4 hearts)
    board_fd = [card("h", "A"), card("h", "7"), card("c", "2")]
    hero_fd = [card("h", "K"), card("h", "Q")]
    res_fd = evaluate_relative_strength(hero_fd, board_fd)
    assert res_fd["is_draw"]
    assert res_fd["draw_equity"] > 0.10
    assert "flush_draw" in res_fd["tier"]

def test_opponent_bayesian_smoothing():
    # Only 2 hands observed, 2 calls
    st = OpponentStats(hands=2, calls=2, folds=0, raises=0)
    raw = st.profile()
    assert raw["call"] == 1.0  # Raw is extreme 100%

    smoothed = st.smoothed_profile(prior_weight=8.0)
    # Bayesian smoothed pulls back towards prior (0.32)
    assert 0.40 <= smoothed["call"] <= 0.55
    assert smoothed["hands"] == 2

def test_opponent_profiler_ingestion(tmp_path):
    p = tmp_path / "hands_test.jsonl"
    mock_hand = {
        "table": {
            "id": "t1",
            "players": [
                {"agentId": "agent_station", "stack": 20000},
                {"agentId": "hero", "stack": 20000},
            ],
            "hand": {
                "id": "h1",
                "actions": [
                    {"agentId": "agent_station", "type": "call", "street": "preflop", "amount": 200},
                    {"agentId": "hero", "type": "raise", "street": "preflop", "amount": 600},
                    {"agentId": "agent_station", "type": "call", "street": "preflop", "amount": 400},
                    {"agentId": "hero", "type": "bet", "street": "flop", "amount": 600},
                    {"agentId": "agent_station", "type": "call", "street": "flop", "amount": 600},
                ]
            }
        }
    }
    p.write_text(json.dumps(mock_hand) + "\n", encoding="utf-8")

    profiler = OpponentProfiler()
    count = profiler.ingest_file(p)
    assert count == 1
    profiles = profiler.export(tmp_path / "profiles.json")

    assert "agent_station" in profiles
    assert profiles["agent_station"]["calls_count"] == 3
    assert profiles["agent_station"]["hands"] == 1

def test_exploitative_decision_vs_station():
    # Load profile where opponent is a marked calling station
    station_profile = {
        "villain_station": {
            "hands": 50,
            "calls_count": 35,
            "folds_count": 5,
            "raises_count": 5,
            "vpip_count": 40,
        }
    }
    agent_vs_station = StrategyAgent(seed=42, profiles=station_profile)
    agent_normal = StrategyAgent(seed=42)

    # On river with pure air (hero has low high card, pot has money)
    # Against a station, agent should check much more and suppress bluffs
    obs = {
        "agentId": "hero",
        "hero": ["2c", "3d"],
        "board": ["As", "Kd", "9h", "8c", "Jh"],
        "pot": 2000,
        "stack": 18000,
        "players": [
            {"agentId": "hero", "stack": 18000, "folded": False},
            {"agentId": "villain_station", "stack": 18000, "folded": False},
        ],
        "legal": {"check": None, "bet": (200, 18000)},
    }
    decisions_vs_station = [agent_vs_station.choose_local(obs)["type"] for _ in range(50)]
    
    obs_unknown = dict(obs, players=[
        {"agentId": "hero", "stack": 18000, "folded": False},
        {"agentId": "villain_unknown", "stack": 18000, "folded": False},
    ])
    decisions_vs_unknown = [agent_normal.choose_local(obs_unknown)["type"] for _ in range(50)]

    # Station bluffs should be substantially reduced
    assert decisions_vs_station.count("check") >= 42
    assert decisions_vs_station.count("bet") <= decisions_vs_unknown.count("bet")

def test_push_fold_short_stack():
    agent = StrategyAgent(seed=1)
    # Hero has only 8 BB (1600 chips at BB=200) and holds AK preflop
    obs = {
        "agentId": "hero",
        "hero": ["As", "Kd"],
        "board": [],
        "pot": 300,
        "stack": 1600,
        "big_blind": 200,
        "position": 0,
        "dealer_seat": 0,  # Button
        "players": [
            {"agentId": "hero", "stack": 1600, "folded": False},
            {"agentId": "opp1", "stack": 20000, "folded": False},
        ],
        "legal": {"fold": None, "call": 200, "raise": (400, 1600), "allIn": 1600},
    }
    decision = agent.choose_local(obs)
    # With short stack and AK, hero should push all-in directly rather than min-raising
    assert decision["type"] in ("allIn", "raise")
    if decision["type"] == "raise":
        assert decision["amount"] == 1600

def test_opponent_profiler_quality_filters():
    profiler = OpponentProfiler()
    # 1. Normal active player with 40 hands
    for _ in range(40):
        profiler.ingest_hand({
            "players": [{"agentId": "good_player", "name": "SolidPro"}],
            "actions": [{"agentId": "good_player", "type": "raise", "street": "preflop"}]
        })
    # 2. Low-sample player with only 5 hands
    for _ in range(5):
        profiler.ingest_hand({
            "players": [{"agentId": "noisy_newbie", "name": "Newbie"}],
            "actions": [{"agentId": "noisy_newbie", "type": "call", "street": "preflop"}]
        })
    # 3. AFK/Zombie bot with 25 hands of 100% fold
    for _ in range(25):
        profiler.ingest_hand({
            "players": [{"agentId": "zombie_bot", "name": "Zombie"}],
            "actions": [{"agentId": "zombie_bot", "type": "fold", "street": "preflop"}]
        })

    # Raw export without filter keeps all 3
    raw = profiler.export(min_hands=1, filter_afk=False)
    assert len(raw) == 3

    # Filtered export: keeps only good_player
    cleaned = profiler.export(min_hands=30, filter_afk=True)
    assert len(cleaned) == 1
    assert "good_player" in cleaned
    assert "noisy_newbie" not in cleaned
    assert "zombie_bot" not in cleaned

def test_live_profile_hot_reload_accumulates_onto_stored_counts(tmp_path):
    """A live session must add to stored history, not replace it with its own sample.

    The profiler seeds from the profile file at startup, so 5 hands on top of a
    2000-hand profile yields 2005. Without seeding the session snapshot (5 hands)
    would be written over the file -- losing the history, and dropping the opponent
    from the model entirely since load_opponent_profiles ignores anything under 15 hands.
    """
    from agentpoker.live import LiveRunner
    from agentpoker.protocol import AgentPokerClient, Config

    profiles_file = tmp_path / "opponent_profiles.json"
    profiles_file.write_text(json.dumps({
        "veteran": {
            "name": "Vet", "hands": 2000, "vpip_count": 600, "raises_count": 400,
            "calls_count": 200, "folds_count": 1200, "net_pnl": 5000, "bb_sum": 10000.0,
            "bb_100": 50.0, "vpip": 0.3,
        },
    }), encoding="utf-8")

    client = AgentPokerClient(Config(key="fake", competition_id="comp1"))
    runner = LiveRunner(client, StrategyAgent(name="hero"), competition_id="comp1",
                        profiles_path=str(profiles_file))
    for _ in range(5):
        runner.profiler.ingest_hand({
            "players": [{"agentId": "veteran", "name": "Vet"}],
            "actions": [{"agentId": "veteran", "type": "raise", "street": "preflop"}],
        })
    runner._update_and_reload_profiles()

    stored = json.loads(profiles_file.read_text(encoding="utf-8"))
    assert stored["veteran"]["hands"] == 2005, "session hands must accumulate onto stored counts"
    assert stored["veteran"]["vpip_count"] == 605, "action counts must accumulate too"
    assert stored["veteran"]["name"] == "Vet", "the stored name must survive the rewrite"


def test_short_stack_min_raise_boundary():
    agent = StrategyAgent(seed=42)
    # Scenario: hero is short-stacked (500 chips remaining), table has min bet = 1000
    obs = {
        "agentId": "hero",
        "hero": ["Ah", "Kd"],
        "board": [],
        "pot": 2000,
        "stack": 500,
        "big_blind": 1000,
        "position": 1,
        "dealer_seat": 0,
        "players": [
            {"agentId": "hero", "stack": 500, "folded": False},
            {"agentId": "villain", "stack": 20000, "folded": False}
        ],
        # lo > hi boundary condition
        "legal": {"check": None, "bet": (1000, 500), "allIn": 500}
    }
    decision = agent.choose_local(obs)
    # Must never emit bet > 500
    if decision["type"] in ("bet", "raise"):
        assert decision["amount"] <= 500
    else:
        assert decision["type"] in ("allIn", "check", "fold")


def test_trainer_param_bounds_clamping():
    from agentpoker.training import StrategyTrainer
    trainer = StrategyTrainer(seed=42)
    # Start with an extreme nit
    nit_params = StrategyParams(vpip=0.01, cbet_size=0.01, value_threshold=0.60, thin_value_threshold=0.75, jam_threshold=0.50)
    # Mutate with zero sigma -> must clamp and fix monotonicity
    clamped = trainer.mutate(nit_params, 0.0)
    assert clamped.vpip >= 0.18, "VPIP must never drop below healthy 6-max floor (0.18)"
    assert clamped.cbet_size >= 0.28, "C-bet size must never drop below 28% pot"
    assert clamped.thin_value_threshold < clamped.value_threshold, "thin value must be strictly less than full value"
    assert clamped.jam_threshold > clamped.value_threshold, "jam threshold must be strictly greater than value threshold"


def test_championship_tournament_pressure():
    agent = StrategyAgent()
    # 1. Semifinal: Rank 4 is eliminated -> pressure must be high attack
    sf_losing_ctx = {"rank": 4, "round_no": 11, "hands_remaining": 6, "bb100": -10.0, "rank3_bb100": 15.0}
    p_sf_losing = agent._tournament_pressure(sf_losing_ctx)
    assert p_sf_losing > 0.5, "Losing in semifinal must trigger high attack pressure"

    # 2. Final: Rank 2 is losing the championship -> pressure must be aggressive attack
    final_second_ctx = {"rank": 2, "round_no": 12, "hands_remaining": 6, "bb100": 20.0, "leader_bb100": 50.0}
    p_final_second = agent._tournament_pressure(final_second_ctx)
    assert p_final_second > 0.5, "2nd place in final must trigger aggressive attack to overtake leader"

    # 3. Final: Rank 1 is leading -> pressure is controlled
    final_first_ctx = {"rank": 1, "round_no": 12, "hands_remaining": 6, "bb100": 50.0, "second_bb100": 20.0}
    p_final_first = agent._tournament_pressure(final_first_ctx)
    assert p_final_first < p_final_second, "Leader in final should not be more desperate than 2nd place"

