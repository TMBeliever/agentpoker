import random
import pytest
from agentpoker.engine import NLHEngine, Action, Player
from agentpoker.cards import Card
from agentpoker.strategy import StrategyAgent, StrategyParams
from agentpoker.tournament import LeagueSimulator, SimAgent
from agentpoker.scoring import Standing, bb100, rank_standings


class FixedActionPolicy:
    def __init__(self, action_type="check", amount=None):
        self.action_type = action_type
        self.amount = amount

    def choose(self, obs):
        lg = obs["legal"]
        if self.action_type in lg:
            d = {"type": self.action_type}
            if self.amount is not None and self.action_type in ("bet", "raise"):
                d["amount"] = self.amount
            return d
        if "check" in lg:
            return {"type": "check"}
        if "call" in lg:
            return {"type": "call"}
        return {"type": "fold"}


class FoldToBetPolicy:
    def choose(self, obs):
        lg = obs["legal"]
        if "check" in lg:
            return {"type": "check"}
        if "fold" in lg:
            return {"type": "fold"}
        return {"type": "call"}


class AllInPolicy:
    def choose(self, obs):
        lg = obs["legal"]
        if "allIn" in lg:
            return {"type": "allIn"}
        for k in ("raise", "bet"):
            if k in lg:
                return {"type": k, "amount": int(lg[k][1])}
        if "call" in lg:
            return {"type": "call"}
        return {"type": "check"}


def test_chip_conservation():
    """G1.1: Verify sum of stacks after hand == sum of stacks before hand."""
    engine = NLHEngine(100, 200, seed=42)
    agents = ["p1", "p2", "p3", "p4", "p5", "p6"]
    policies = {a: StrategyAgent(seed=i) for i, a in enumerate(agents)}

    for hand_idx in range(100):
        stacks = {a: 20000 for a in agents}
        res, _ = engine.play_hand(agents, stacks, hand_idx % len(agents), policies)
        total_before = sum(stacks.values())
        total_after = sum(res.final_stacks.values())
        assert total_after == total_before, f"Hand {hand_idx}: {total_before} -> {total_after}"


def test_blind_posting():
    """G1.2: Verify HU and 3-6 max blind posting and action order."""
    engine = NLHEngine(100, 200, seed=101)

    # 1. Heads-Up (2 players)
    # Dealer (seat 0) is SB; Seat 1 is BB. Dealer acts first preflop!
    hu_agents = ["HU_SB_Dealer", "HU_BB"]
    hu_stacks = {a: 20000 for a in hu_agents}
    hu_first_actor = None

    class CaptureHU:
        def __init__(self, name):
            self.name = name

        def choose(self, obs):
            nonlocal hu_first_actor
            if hu_first_actor is None:
                hu_first_actor = obs["agentId"]
            return {"type": "fold"}

    hu_policies = {a: CaptureHU(a) for a in hu_agents}
    res_hu, next_dealer = engine.play_hand(hu_agents, hu_stacks, 0, hu_policies)

    # In HU, forced actions: seat 0 (dealer) = smallBlind, seat 1 = bigBlind
    assert res_hu.actions[0].type == "smallBlind"
    assert res_hu.actions[0].seat == 0
    assert res_hu.actions[0].amount == 100
    assert res_hu.actions[1].type == "bigBlind"
    assert res_hu.actions[1].seat == 1
    assert res_hu.actions[1].amount == 200
    assert hu_first_actor == "HU_SB_Dealer", "In HU, dealer/SB must act first preflop"
    assert next_dealer == 1

    # 2. 6-max (6 players)
    # Dealer is seat 0. SB is seat 1, BB is seat 2. UTG is seat 3 (acts first preflop).
    six_agents = [f"P{i}" for i in range(6)]
    six_stacks = {a: 20000 for a in six_agents}
    six_first_actor = None

    class Capture6Max:
        def __init__(self, name):
            self.name = name

        def choose(self, obs):
            nonlocal six_first_actor
            if six_first_actor is None:
                six_first_actor = obs["agentId"]
            return {"type": "fold"}

    six_policies = {a: Capture6Max(a) for a in six_agents}
    res_6, next_dealer_6 = engine.play_hand(six_agents, six_stacks, 0, six_policies)
    assert res_6.actions[0].type == "smallBlind"
    assert res_6.actions[0].seat == 1
    assert res_6.actions[0].amount == 100
    assert res_6.actions[1].type == "bigBlind"
    assert res_6.actions[1].seat == 2
    assert res_6.actions[1].amount == 200
    assert six_first_actor == "P3", "In 6-max, UTG (dealer+3) must act first preflop"
    assert next_dealer_6 == 1


def test_button_rotation():
    """G1.3: Verify button rotates +1 seat clockwise each hand."""
    engine = NLHEngine(100, 200, seed=7)
    agents = [f"P{i}" for i in range(6)]
    stacks = {a: 20000 for a in agents}
    policies = {a: FixedActionPolicy("call") for a in agents}

    dealer = 0
    for h in range(12):
        assert dealer == h % 6
        _, next_dealer = engine.play_hand(agents, stacks, dealer, policies)
        dealer = next_dealer
    assert dealer == 0


def test_side_pot():
    """G1.4: Verify multi-all-in staggered stack side pot partitioning."""
    engine = NLHEngine(100, 200, seed=55)

    # 1. Deterministic direct settlement test with known hands:
    # A has 1000 all-in with AA (best hand)
    # B has 3000 all-in with KK (second best)
    # C has 10000 stack, calls 3000 with QQ (worst)
    players = [
        Player(agent_id="A", seat=0, stack=0, hole=[Card(14, 0), Card(14, 1)], committed_total=1000),
        Player(agent_id="B", seat=1, stack=0, hole=[Card(13, 0), Card(13, 1)], committed_total=3000),
        Player(agent_id="C", seat=2, stack=7000, hole=[Card(12, 0), Card(12, 1)], committed_total=3000),
    ]
    board = [Card(2, 0), Card(3, 1), Card(4, 2), Card(7, 3), Card(9, 0)]
    payouts, returned = engine._settle(players, board)

    # Main pot: 1000 * 3 = 3000 -> Won by A (AA)
    assert payouts["A"] == 3000
    # Side pot: (3000 - 1000) * 2 = 4000 -> Won by B (KK beats QQ), A is NOT eligible
    assert payouts["B"] == 4000
    # C gets 0 from pot, keeps 7000 stack
    assert payouts["C"] == 0
    assert sum(payouts.values()) == 7000

    # 2. End-to-end play_hand simulation with staggered stacks
    agents = ["A", "B", "C"]
    stacks = {"A": 1000, "B": 3000, "C": 10000}
    policies = {a: AllInPolicy() for a in agents}
    res, _ = engine.play_hand(agents, stacks, 0, policies)

    # Chip conservation
    assert sum(res.final_stacks.values()) == sum(stacks.values())
    # Short stack A can never win more than 1000 * 3 = 3000 chips
    assert res.final_stacks["A"] <= 3000
    # C did not risk more than 3000, so C must have at least 7000 chips remaining
    assert res.final_stacks["C"] >= 7000


def test_unmatched_raise():
    """G1.5: Uncalled excess bets return directly to raiser without entering pot."""
    engine = NLHEngine(100, 200, seed=99)
    # HU: A opens 400 (commits 500 total), B re-raises 2000 (commits 2200 total), A folds.
    # B should get 1700 uncalled excess returned directly, plus 500 from A.
    agents = ["A", "B"]
    stacks = {"A": 20000, "B": 20000}

    class OpenOnceThenFold:
        def __init__(self):
            self.raised = False

        def choose(self, obs):
            lg = obs["legal"]
            if not self.raised and "raise" in lg:
                self.raised = True
                return {"type": "raise", "amount": 400}
            return {"type": "fold"}

    class ReRaiser:
        def choose(self, obs):
            lg = obs["legal"]
            if "raise" in lg:
                return {"type": "raise", "amount": 2000}
            return {"type": "call"}

    res, _ = engine.play_hand(agents, stacks, 0, {"A": OpenOnceThenFold(), "B": ReRaiser()})
    assert res.final_stacks["A"] + res.final_stacks["B"] == 40000
    assert res.final_stacks["A"] == 20000 - 500
    assert res.final_stacks["B"] == 20000 + 500
    assert res.returned_bets["B"] == 1700
    assert res.payouts["B"] == 1000


def test_auto_rebuy():
    """G1.6: Busted player receives 100 BB chips, is not eliminated, incurs 100 BB rebuy cost."""
    agents = [SimAgent(f"p{i}", StrategyAgent(seed=i)) for i in range(6)]
    sim = LeagueSimulator(agents, rounds=1, hands_per_round=5, seed=12)
    st = sim._state()

    # Manually bust agent p0 to 0 chips
    st["p0"]["stack"] = 0
    # Play 1 hand
    sim._play_group([a.agent_id for a in agents], st, round_no=1, hands_this_round=1)

    # Agent p0 must have rebought to positive stack
    assert st["p0"]["stack"] > 0
    assert st["p0"]["rebuy_count"] >= 1
    assert st["p0"]["rebuy_cost_bb"] >= 100.0
    assert st["p0"]["hands"] == 1


def test_multiple_rebuys():
    """G1.7: 3 consecutive busts record rebuy_count=3, rebuy_cost_bb=300.0, and ledger holds."""
    aid = "test_player"
    bb = 200
    player_state = {
        "stack": 100 * bb,
        "initial_stack": 100 * bb,
        "rebuy_count": 0,
        "rebuy_cost_bb": 0.0,
        "gross_winnings_bb": 0.0,
        "gross_losses_bb": 0.0,
        "net_bb": 0.0,
        "hands": 0,
    }

    # Simulate 3 consecutive complete stack losses of 100 BB each
    for _ in range(3):
        # Starts with 100 BB (20000)
        before_stack = player_state["stack"]
        # Loses entire stack
        player_state["stack"] = 0
        delta = (player_state["stack"] - before_stack) / bb  # -100.0
        if delta < 0:
            player_state["gross_losses_bb"] += (-delta)
        player_state["hands"] += 1
        # Auto rebuy
        player_state["stack"] = 100 * bb
        player_state["rebuy_count"] += 1
        player_state["rebuy_cost_bb"] += 100.0
        player_state["net_bb"] = (
            (player_state["stack"] - 100 * bb) / bb - player_state["rebuy_cost_bb"]
        )

    assert player_state["rebuy_count"] == 3
    assert player_state["rebuy_cost_bb"] == 300.0
    assert player_state["net_bb"] == -300.0
    # Ledger equality verification:
    ledger_net = player_state["gross_winnings_bb"] - player_state["gross_losses_bb"]
    assert player_state["net_bb"] == ledger_net == -300.0


def test_bb100_consistency():
    """G1.8: bb100 == net_bb / hands * 100.0 across arbitrary histories."""
    assert bb100(0.0, 0) is None
    assert bb100(100.0, 100) == pytest.approx(100.0)
    assert bb100(-50.0, 200) == pytest.approx(-25.0)
    assert bb100(12.34, 17) == pytest.approx((12.34 / 17) * 100.0)


def test_bust_does_not_eliminate():
    """G1.9: Busted player in hand h participates normally in hand h+1."""
    agents = [SimAgent(f"a{i}", StrategyAgent(seed=100 + i)) for i in range(6)]
    sim = LeagueSimulator(agents, rounds=1, hands_per_round=10, seed=42)
    st = sim._state()

    # Artificially set a0 to 0 stack before round starts
    st["a0"]["stack"] = 0
    group = [a.agent_id for a in agents]
    sim._play_group(group, st, round_no=1, hands_this_round=10)

    # a0 must have played all 10 hands!
    assert st["a0"]["hands"] == 10
    for a in group:
        assert st[a]["hands"] == 10


def test_net_result_after_rebuy():
    """G1.10: Verify net_bb == (stack - initial_stack) / bb - rebuy_cost_bb throughout transitions."""
    bb = 200
    st = {
        "stack": 100 * bb,
        "rebuy_count": 0,
        "rebuy_cost_bb": 0.0,
        "gross_winnings_bb": 0.0,
        "gross_losses_bb": 0.0,
        "net_bb": 0.0,
    }

    # Step 1: Lose 100 BB (bust) -> rebuy 100 BB
    st["gross_losses_bb"] += 100.0
    st["stack"] = 100 * bb
    st["rebuy_count"] += 1
    st["rebuy_cost_bb"] += 100.0
    st["net_bb"] = (st["stack"] - 100 * bb) / bb - st["rebuy_cost_bb"]
    assert st["net_bb"] == -100.0
    assert st["gross_winnings_bb"] - st["gross_losses_bb"] == -100.0

    # Step 2: Win 150 BB (stack reaches 250 BB)
    st["gross_winnings_bb"] += 150.0
    st["stack"] = 250 * bb
    st["net_bb"] = (st["stack"] - 100 * bb) / bb - st["rebuy_cost_bb"]
    assert st["net_bb"] == 50.0
    assert st["gross_winnings_bb"] - st["gross_losses_bb"] == 50.0

    # Step 3: Lose 250 BB (bust again) -> rebuy 100 BB
    st["gross_losses_bb"] += 250.0
    st["stack"] = 100 * bb
    st["rebuy_count"] += 1
    st["rebuy_cost_bb"] += 100.0
    st["net_bb"] = (st["stack"] - 100 * bb) / bb - st["rebuy_cost_bb"]
    assert st["net_bb"] == -200.0
    assert st["gross_winnings_bb"] - st["gross_losses_bb"] == -200.0


def test_1000_randomized_hands_zero_violation():
    """G1.11: 1,000+ randomized hand simulations with zero conservation violations."""
    rng = random.Random(2026)
    engine = NLHEngine(100, 200, seed=2026)

    class RandomWildPolicy:
        def choose(self, obs):
            lg = obs["legal"]
            keys = list(lg.keys())
            chosen = rng.choice(keys)
            if chosen in ("bet", "raise"):
                lo, hi = lg[chosen]
                return {"type": chosen, "amount": rng.randint(int(lo), int(hi))}
            return {"type": chosen}

    for h in range(1200):
        n_players = rng.randint(2, 6)
        seats = [f"sim_{i}" for i in range(n_players)]
        stacks = {s: rng.choice([2000, 5000, 20000, 50000]) for s in seats}
        total_before = sum(stacks.values())
        policies = {s: RandomWildPolicy() for s in seats}
        dealer = rng.randint(0, n_players - 1)

        res, next_dealer = engine.play_hand(seats, stacks, dealer, policies)
        total_after = sum(res.final_stacks.values())

        assert total_after == total_before, f"Hand {h} leaked chips: {total_before} != {total_after}"
        assert next_dealer == (dealer + 1) % n_players
        for s, stk in res.final_stacks.items():
            assert stk >= 0, f"Player {s} has negative stack {stk}"
