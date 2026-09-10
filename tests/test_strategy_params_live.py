"""Guards that every evolved parameter actually influences play.

Six of the twenty-three StrategyParams fields (vpip, squeeze_frequency,
turn_barrel_frequency, cbet_size, raise_size, bubble_aggression) were once read by
nothing, so the genetic search spent effort on inert dimensions and every archetype
played a near-identical style. These tests fail if that regresses.
"""
import inspect
from dataclasses import asdict, fields

from agentpoker.strategy import StrategyAgent, StrategyParams
from agentpoker.engine import NLHEngine
from agentpoker.training import ARCHETYPES, profile_to_params

CHECKED = {f.name for f in fields(StrategyParams)}


def test_every_param_is_read_by_the_decision_code():
    src = inspect.getsource(StrategyAgent)
    unread = [name for name in CHECKED if f"params.{name}" not in src]
    assert not unread, f"parameters that never affect a decision: {sorted(unread)}"


class _Spy(StrategyAgent):
    """Records its own preflop entry rate and postflop aggression."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.hands = 0
        self.entered = 0
        self.raised = 0
        self.post_bets = 0
        self.post_calls = 0
        self._hand = None

    def choose_local(self, obs):
        decision = super().choose_local(obs)
        if not obs["board"]:
            if obs.get("hand_id") != self._hand:
                self._hand = obs.get("hand_id")
                self.hands += 1
                if decision["type"] in ("call", "raise", "bet", "allIn"):
                    self.entered += 1
                if decision["type"] in ("raise", "bet", "allIn"):
                    self.raised += 1
        else:
            if decision["type"] in ("raise", "bet", "allIn"):
                self.post_bets += 1
            elif decision["type"] == "call":
                self.post_calls += 1
        return decision

    @property
    def vpip(self):
        return self.entered / max(1, self.hands)


def _measure(names, hands=250, seed=5):
    spies = {n: _Spy(ARCHETYPES[n], seed=i + 1, name=n) for i, n in enumerate(names)}
    ids = list(names)
    eng = NLHEngine(100, 200, seed=seed)
    for h in range(hands):
        eng.play_hand(ids, {i: 20000 for i in ids}, h % len(ids), spies)
    return spies


def test_vpip_parameter_controls_actual_entry_rate():
    names = ["nit", "tight", "balanced", "lag", "station", "maniac"]
    spies = _measure(names)
    measured = [spies[n].vpip for n in names]
    for i in range(len(names) - 1):
        assert measured[i] < measured[i + 1] + 0.06, \
            f"{names[i]} ({measured[i]:.2f}) should not enter more than {names[i+1]} ({measured[i+1]:.2f})"
    # The parameter must actually move behaviour, not just correlate with a label.
    assert spies["nit"].vpip < 0.30
    assert spies["maniac"].vpip > spies["nit"].vpip + 0.15


def test_aggression_parameters_move_postflop_behaviour():
    """Passive and aggressive archetypes must not play the same postflop game.

    Uses the aggression *rate* per hand rather than bets/calls: a ratio is dominated by
    how often a player gets to the flop, which differs sharply between archetypes.
    """
    names = ["nit", "tight", "balanced", "lag", "station", "maniac"]
    spies = _measure(names, hands=300)
    rate = {n: spies[n].post_bets / max(1, spies[n].hands) for n in names}
    assert rate["maniac"] > rate["nit"] * 1.4, rate
    assert rate["lag"] > rate["nit"], rate


def test_profile_to_params_varies_all_behavioural_fields():
    profiles = [
        {"vpip": 0.15, "pfr": 0.10, "af": 1.2, "is_nit": True,
         "open_size_bb": 2.2, "cbet_size": 0.33, "value_bet_size": 0.75, "raise_size": 0.5},
        {"vpip": 0.60, "pfr": 0.45, "af": 9.0, "is_maniac": True,
         "open_size_bb": 4.5, "cbet_size": 0.9, "value_bet_size": 0.4, "raise_size": 1.2},
    ]
    a, b = (profile_to_params(p) for p in profiles)
    differing = [f for f in asdict(a) if getattr(a, f) != getattr(b, f)]
    missing = sorted(CHECKED - set(differing) - {"equity_samples"})
    assert not missing, f"profiles differing this much still share: {missing}"
