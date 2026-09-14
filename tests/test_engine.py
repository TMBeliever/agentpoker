import random
from collections import Counter

from agentpoker.engine import NLHEngine
from agentpoker.strategy import StrategyAgent
from agentpoker.training import ARCHETYPES
from dataclasses import replace

SEATS = ['a', 'b', 'c', 'd', 'e', 'f']
BUY_IN = 20000


class AlwaysRaise:
    """Raises whenever it can, otherwise calls/checks."""
    def choose(self, obs):
        lg = obs['legal']
        for k in ('raise', 'bet'):
            if k in lg:
                return {'type': k, 'amount': int(lg[k][0])}
        if lg.get('call', 0) > 0:
            return {'type': 'call'}
        return {'type': 'check'}


class AlwaysFoldToBet:
    def choose(self, obs):
        lg = obs['legal']
        if 'check' in lg:
            return {'type': 'check'}
        if 'fold' in lg:
            return {'type': 'fold'}
        return {'type': 'call'}


def _mixed_policies(seed=0):
    base = list(ARCHETYPES.values())
    return {aid: StrategyAgent(replace(base[i % len(base)]), seed=seed + i, name=aid)
            for i, aid in enumerate(SEATS)}


def test_engine_conserves_chips_simple():
    e = NLHEngine(seed=1)
    policies = {x: StrategyAgent(seed=i) for i, x in enumerate(SEATS)}
    stacks = {x: BUY_IN for x in SEATS}
    r, _ = e.play_hand(SEATS, stacks, 0, policies)
    # A hand can legitimately end preflop on folds; only a contested hand runs the
    # board out. (The original assertion here read "len(board) == 5", which held only
    # because the old strategy never folded to a bet.)
    if any(a.type == "fold" for a in r.actions):
        assert len(r.board) in (0, 3, 4, 5)
    else:
        assert len(r.board) == 5
    assert sum(r.final_stacks.values()) == sum(stacks.values())


def test_engine_conserves_chips_over_many_hands():
    """A single hand is not a conservation test -- the minting bug only fired on hands
    that ended with an unmatched bet, so a one-shot assertion passed by luck."""
    eng = NLHEngine(100, 200, seed=3)
    policies = _mixed_policies(seed=3)
    for h in range(4000):
        stacks = {a: BUY_IN for a in SEATS}
        r, _ = eng.play_hand(SEATS, stacks, h % len(SEATS), policies)
        delta = sum(r.final_stacks[a] - stacks[a] for a in SEATS)
        assert delta == 0, f"hand {h} minted {delta} chips"


def test_engine_conserves_chips_with_random_policies():
    """Random policies produce the wild action sequences that trip settlement edge cases."""
    rng = random.Random(11)
    eng = NLHEngine(100, 200, seed=11)

    class Rand:
        def choose(self, obs):
            lg = obs['legal']
            opts = [k for k in lg if k != 'allIn'] or list(lg)
            k = rng.choice(opts)
            if k in ('raise', 'bet'):
                lo, hi = lg[k]
                return {'type': k, 'amount': rng.randint(int(lo), int(hi))}
            return {'type': k}

    for h in range(4000):
        n = rng.randint(2, 6)
        seats = SEATS[:n]
        pol = {a: Rand() for a in seats}
        stacks = {a: BUY_IN for a in seats}
        r, _ = eng.play_hand(seats, stacks, h % n, pol)
        assert sum(r.final_stacks.values()) == sum(stacks.values())


def test_unmatched_bet_is_returned_exactly_once():
    """HU: A raises to 400, B folds. A must net +200 (B's big blind), not +400."""
    e = NLHEngine(100, 200, seed=5)
    r, _ = e.play_hand(['A', 'B'], {'A': BUY_IN, 'B': BUY_IN}, 0,
                       {'A': AlwaysRaise(), 'B': AlwaysFoldToBet()})
    assert r.final_stacks['A'] == BUY_IN + 200
    assert r.final_stacks['B'] == BUY_IN - 200
    assert sum(r.final_stacks.values()) == 2 * BUY_IN


def test_check_never_legal_while_facing_a_bet():
    seen = Counter()

    class Recorder:
        def __init__(self, inner):
            self.inner = inner

        def choose(self, obs):
            lg = obs['legal']
            to_call = lg.get('call', 0)
            if to_call > 0:
                assert 'check' not in lg, "check offered while facing a bet"
                assert 'fold' in lg, "fold missing while facing a bet"
            else:
                assert 'check' in lg, "check missing when there is nothing to call"
                assert 'raise' not in lg and 'bet' in lg, "opening wager must be 'bet'"
            seen[obs['street']] += 1
            d = self.inner.choose(obs)
            assert d['type'] in lg, f"policy returned illegal action {d['type']} for {sorted(lg)}"
            seen['decisions'] += 1
            return d

    eng = NLHEngine(100, 200, seed=17)
    base = _mixed_policies(seed=17)
    policies = {a: Recorder(p) for a, p in base.items()}
    for h in range(400):
        eng.play_hand(SEATS, {a: BUY_IN for a in SEATS}, h % len(SEATS), policies)
    assert seen['decisions'] > 3500


def test_opponent_actions_counted_once_per_action():
    """The observer must consume each action exactly once: counts stay bounded by the
    number of hands, and `hands` advances once per hand."""
    strat = StrategyAgent(seed=1, name='focal')
    others = {a: StrategyAgent(seed=i + 2, name=a) for i, a in enumerate(SEATS[1:])}
    policies = {'a': strat, **others}
    eng = NLHEngine(100, 200, seed=23)
    hands = 200

    # A hand the focal agent never acts in is a hand it never observes, so the expected
    # denominator is "hands the agent saw", not "hands dealt".
    observed = set()
    inner_choose = strat.choose

    def spy(obs):
        observed.add(obs.get('hand_id'))
        return inner_choose(obs)

    strat.choose = spy
    for h in range(hands):
        eng.play_hand(SEATS, {a: BUY_IN for a in SEATS}, h % len(SEATS), policies)

    assert observed, "focal never acted"
    assert strat.opponents, "no opponents observed"
    for aid, st in strat.opponents.items():
        assert st.hands == len(observed), f"{aid} saw {st.hands} hands, expected {len(observed)}"
        # One action of each kind per street at most (4 streets).
        for field in ('raises', 'bets', 'calls', 'folds', 'checks'):
            assert getattr(st, field) <= 4 * hands, f"{aid}.{field} over-counted"
        # VPIP is a per-hand property.
        assert st.vpip <= st.hands, f"{aid} vpip {st.vpip} exceeds hands {st.hands}"
