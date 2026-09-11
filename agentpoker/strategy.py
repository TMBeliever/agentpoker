from __future__ import annotations
from dataclasses import dataclass, asdict, field
from pathlib import Path
import json, math, random
from typing import Any
from .cards import parse_card, full_hand_rank, equity_exact, evaluate_relative_strength
from .calibration import preflop_percentile, strength_to_equity

@dataclass
class StrategyParams:
    # Preflop
    vpip: float = 0.23
    open_frequency: float = 0.62
    threebet_frequency: float = 0.085
    squeeze_frequency: float = 0.055
    steal_frequency: float = 0.72
    # Postflop
    cbet_frequency: float = 0.62
    turn_barrel_frequency: float = 0.54
    river_bluff_frequency: float = 0.085
    value_threshold: float = 0.68
    thin_value_threshold: float = 0.57
    raise_threshold: float = 0.61
    jam_threshold: float = 0.91
    # Street-specific value thresholds
    flop_value_threshold: float = 0.58
    turn_value_threshold: float = 0.65
    river_value_threshold: float = 0.74
    # Bet sizing
    open_size: float = 2.35
    cbet_size: float = 0.47
    value_bet_size: float = 0.69
    bluff_bet_size: float = 0.55
    raise_size: float = 0.68
    # Board texture bet sizing
    dry_board_bet_size: float = 0.33
    wet_board_bet_size: float = 0.75
    # Tournament adaptation
    safety: float = 0.45
    attack: float = 0.70
    bubble_aggression: float = 0.80
    late_aggression: float = 0.22
    # Randomization / equity accuracy
    temperature: float = 0.10
    equity_samples: int = 0

@dataclass
class OpponentStats:
    hands: int = 0
    vpip: int = 0
    raises: int = 0
    folds: int = 0
    calls: int = 0
    bets: int = 0
    checks: int = 0
    last_seen: int = 0

    def profile(self) -> dict[str, float]:
        n = max(1, self.hands)
        return {
            "vpip": self.vpip / n,
            "raise": self.raises / n,
            "fold": self.folds / n,
            "call": self.calls / n,
            "bet": self.bets / n,
            "check": self.checks / n,
            "hands": float(self.hands),
        }

    def smoothed_profile(self, prior_weight: float = 8.0) -> dict[str, Any]:
        """Bayesian-smoothed profile metrics to avoid small-sample distortion."""
        prior_vpip = 0.25
        prior_raise = 0.16
        prior_fold = 0.52
        prior_call = 0.32
        w = max(1.0, float(prior_weight))
        denom = float(self.hands) + w
        svpip = (self.vpip + w * prior_vpip) / denom
        sraise = (self.raises + w * prior_raise) / denom
        sfold = (self.folds + w * prior_fold) / denom
        scall = (self.calls + w * prior_call) / denom
        return {
            "vpip": svpip,
            "raise": sraise,
            "fold": sfold,
            "call": scall,
            "is_station": scall >= 0.38 and sfold <= 0.36,
            "is_nit": svpip <= 0.18 and sfold >= 0.58,
            "is_maniac": svpip >= 0.44 and sraise >= 0.26,
            "is_passive": sraise <= 0.11,
            "hands": self.hands,
        }

class StrategyAgent:
    """Competition-specific adaptive poker strategy with exploitative opponent modeling.

    The live agent uses the same decision code as the offline simulator. It incorporates:
    1. Heuristic relative hand strength and draw detection.
    2. Bayesian-smoothed opponent profiles that actively adjust fold/bluff/value thresholds.
    3. Position-aware preflop ranges (UTG vs Button/Cutoff).
    4. Short-stack (<=12 BB) push/fold logic.
    """
    def __init__(self, params: StrategyParams | None = None, seed: int = 7, name: str = "strategy", profiles: dict[str, Any] | str | Path | None = None):
        self.params = params or StrategyParams()
        self.rng = random.Random(seed)
        self.name = name
        self.opponents: dict[str, OpponentStats] = {}
        self._obs_hand_id: Any = None
        self._obs_cursor: int = 0
        self._vpip_seen: set[str] = set()
        # Whether hero raised preflop this hand -- needed to tell a continuation bet
        # (sized by cbet_size) from an ordinary postflop value bet.
        self._hero_is_aggressor: bool = False
        if profiles is not None:
            self.load_opponent_profiles(profiles)

    def load_opponent_profiles(self, source: dict[str, Any] | str | Path) -> int:
        """Load pre-computed opponent profiles from a dict, json string, or file."""
        if isinstance(source, (str, Path)):
            p = Path(source)
            if not p.exists():
                return 0
            data = json.loads(p.read_text(encoding="utf-8"))
        elif isinstance(source, dict):
            data = source
        else:
            return 0
        loaded = 0
        for aid, stats in data.items():
            if not isinstance(stats, dict):
                continue
            if int(stats.get("hands", 0)) < 15:
                continue
            st = self.opponents.setdefault(aid, OpponentStats())
            st.hands = int(stats.get("hands", st.hands))
            st.vpip = int(stats.get("vpip_count", stats.get("vpip", st.vpip)))
            st.raises = int(stats.get("raises_count", stats.get("raises", stats.get("raise", st.raises))))
            st.folds = int(stats.get("folds_count", stats.get("folds", stats.get("fold", st.folds))))
            st.calls = int(stats.get("calls_count", stats.get("calls", stats.get("call", st.calls))))
            st.bets = int(stats.get("bets_count", stats.get("bets", stats.get("bet", st.bets))))
            st.checks = int(stats.get("checks_count", stats.get("checks", stats.get("check", st.checks))))
            loaded += 1
        return loaded

    def choose(self, obs: dict[str, Any]) -> dict[str, Any]:
        if "legal" in obs:
            return self.choose_local(obs)
        return self._choose_remote(obs)

    def _active_villain_profile(self, obs: dict[str, Any]) -> dict[str, Any]:
        """Aggregate smoothed profile of active opponents in the current hand."""
        hero_id = obs.get("agentId")
        players = obs.get("players") or []
        active_opps = [
            p.get("agentId") for p in players
            if p.get("agentId") and p.get("agentId") != hero_id and not p.get("folded")
        ]
        if not active_opps:
            active_opps = [p.get("agentId") for p in players if p.get("agentId") and p.get("agentId") != hero_id]

        if not active_opps:
            return {"fold": 0.52, "call": 0.32, "raise": 0.16, "vpip": 0.25,
                    "is_station": False, "is_nit": False, "is_maniac": False, "is_passive": False}

        folds, calls, raises, vpips = [], [], [], []
        stations, nits, maniacs, passives = 0, 0, 0, 0
        for aid in active_opps:
            st = self.opponents.get(aid)
            prof = st.smoothed_profile() if st else OpponentStats().smoothed_profile()
            folds.append(prof["fold"])
            calls.append(prof["call"])
            raises.append(prof["raise"])
            vpips.append(prof["vpip"])
            if prof["is_station"]: stations += 1
            if prof["is_nit"]: nits += 1
            if prof["is_maniac"]: maniacs += 1
            if prof["is_passive"]: passives += 1

        n = float(len(active_opps))
        return {
            "fold": sum(folds) / n,
            "call": sum(calls) / n,
            "raise": sum(raises) / n,
            "vpip": sum(vpips) / n,
            "is_station": stations > 0,
            "is_nit": nits > 0 and stations == 0,
            "is_maniac": maniacs > 0,
            "is_passive": passives > 0,
        }

    def _preflop_position_factor(self, obs: dict[str, Any]) -> tuple[str, float, bool]:
        """Compute relative position tag, aggression multiplier, and whether hero is in steal seat."""
        players = obs.get("players") or []
        n = max(2, len(players))
        dealer = obs.get("dealer_seat")
        seat = obs.get("position")
        if dealer is not None and seat is not None:
            offset = (int(seat) - int(dealer)) % n
            if offset == 0:  # Button
                return "btn", 1.35, True
            elif offset == 1:  # Small Blind
                return "sb", 0.95, False
            elif offset == 2:  # Big Blind
                return "bb", 1.00, False
            elif offset == n - 1:  # Cutoff
                return "co", 1.15, True
            elif offset == 3 and n >= 5:  # UTG
                return "utg", 0.72, False
            return "mp", 0.88, False
        # Fallback based on raw position index
        pos = int(obs.get("position", 0) or 0)
        is_late = pos >= max(0, n - 2)
        return ("late" if is_late else "early"), (1.20 if is_late else 0.80), is_late

    def choose_local(self, obs: dict[str, Any]) -> dict[str, Any]:
        legal = obs["legal"]
        hero = [parse_card(c) for c in obs["hero"]]
        board = [parse_card(c) for c in obs["board"]]
        ctx = obs.get("context") or {}
        self._observe_opponents(obs)

        active_opp = max(1, len([p for p in obs["players"] if not p.get("folded") and not p.get("allIn")]) - 1)
        pressure = self._tournament_pressure(ctx)
        villain = self._active_villain_profile(obs)

        if not board:
            return self._preflop(legal, hero, obs, pressure, villain)

        equity = self._equity(hero, board, active_opp)
        pot = float(obs.get("pot", 0) or 0)
        bb_size = float(obs.get("big_blind", 200) or 200)
        call = float(legal.get("call", 0) or 0)
        pot_odds = call / (pot + call) if call > 0 and pot + call > 0 else 0.0
        texture = self._board_texture(board)
        facing_bet = call > 0
        strength = equity
        street = len(board)
        # Blocker effect detection: nut flush blocker on 3+ flush boards
        eval_meta = evaluate_relative_strength(hero, board)
        blocker = eval_meta.get("blocker_effects") or {}
        has_nut_flush_blocker = bool(blocker.get("has_nut_flush_blocker", False))

        # Flop bet after hero raised preflop is a continuation bet, priced by cbet_size.
        is_cbet = self._hero_is_aggressor and street == 3
        # Street-specific aggression frequency drives barrelling.
        if street == 4:
            aggression_freq = self.params.turn_barrel_frequency
        elif street >= 5:
            aggression_freq = max(self.params.river_bluff_frequency, 0.10)
        else:
            aggression_freq = self.params.cbet_frequency

        # Multiway pot discount: C-betting into multiple active players requires more caution
        if active_opp > 1 and street == 3:
            aggression_freq *= (0.75 ** (active_opp - 1))

        # Opponent profile adjustments
        fold_edge = pot_odds - 0.045
        if facing_bet:
            if villain.get("is_nit"):
                # Nit bets mean high strength: fold marginal bluff-catchers
                fold_edge += 0.05
            elif villain.get("is_maniac"):
                # Maniac bets frequently with air: widen calling threshold
                fold_edge -= 0.06

        # Fold if facing bet and clearly behind pot odds
        if facing_bet and strength < max(0.16, fold_edge) and self._noise(0.025):
            if "fold" in legal:
                return {"type": "fold"}

        # Strong value hands: raise or bet with street-specific thresholds
        if street == 3:
            street_cut = self.params.flop_value_threshold
        elif street == 4:
            street_cut = self.params.turn_value_threshold
        elif street >= 5:
            street_cut = self.params.river_value_threshold
        else:
            street_cut = self.params.value_threshold

        value_cut = street_cut - 0.06 * pressure
        if self.params.value_threshold != 0.68:
            value_cut += (self.params.value_threshold - 0.68) * 0.4
        if villain.get("is_station"):
            # Stations call down with weaker holdings: widen value betting range
            value_cut -= 0.04

        if strength >= value_cut:
            size_boost = 1.15 if villain.get("is_station") else 1.0
            if "raise" in legal and self._should_aggress(self.params.raise_threshold + 0.04 * texture["wetness"], pressure, strength):
                return self._sized_raise(legal, strength=strength, value=True, pressure=pressure, size_mult=size_boost, pot=pot, bb_size=bb_size, wetness=texture["wetness"])
            if "bet" in legal and self._should_aggress(0.68, pressure, strength):
                return self._sized_bet(legal, value=True, pressure=pressure, size_mult=size_boost, pot=pot, bb_size=bb_size, street=street, is_cbet=is_cbet, wetness=texture["wetness"])
            if "call" in legal:
                return {"type": "call"}
            if "check" in legal:
                return {"type": "check"}

        # Semi-bluffs / draws
        draw_bias = texture["draws"]
        semi_threshold = max(0.29, pot_odds * 0.80)
        thin_cut = max(self.params.thin_value_threshold, value_cut - 0.08)
        if strength >= semi_threshold and (draw_bias > 0 or strength > thin_cut):
            semi_cbet = aggression_freq * (0.65 + 0.5 * pressure)
            if villain.get("fold", 0.52) > 0.58:
                semi_cbet *= 1.25
            if ("raise" in legal or "bet" in legal) and self._noise(semi_cbet):
                # _sized_raise picks the right action type for the spot (bet when first
                # to act, raise when facing one).
                return self._sized_raise(legal, strength=strength, value=False, pressure=pressure, pot=pot, bb_size=bb_size, wetness=texture["wetness"])
            if "call" in legal and strength >= pot_odds * 0.88:
                return {"type": "call"}

        # Controlled bluffs (heavily suppressed against stations, boosted against high-folders)
        # A turn barrel is a real decision the genome makes, not a rescaling of the flop.
        bluff_rate = self.params.river_bluff_frequency if street >= 5 else aggression_freq * 0.18
        bluff_rate *= (1.0 + pressure * 0.65)
        if villain.get("is_station"):
            bluff_rate *= 0.15  # Never bluff a calling station
        elif villain.get("fold", 0.52) > 0.58:
            bluff_rate *= 1.35  # High fold equity

        # River blocker effect: nut flush blocker eliminates opponent's nut hands
        if street >= 5 and has_nut_flush_blocker:
            if villain.get("is_station"):
                # Maintain disciplined defense: never bluff calling stations even with nut blockers
                bluff_rate *= 0.10
            else:
                # River polarized bluff: holding the nut flush blocker makes bluffs much higher equity
                bluff_rate = max(bluff_rate, min(0.42, self.params.river_bluff_frequency * 2.0 + 0.12))

        if "raise" in legal and self._noise(bluff_rate):
            return self._sized_raise(legal, strength=max(strength, 0.25), value=False, pressure=pressure, pot=pot, bb_size=bb_size, wetness=texture["wetness"])
        if "bet" in legal and self._noise(bluff_rate):
            return self._sized_bet(legal, value=False, pressure=pressure, pot=pot, bb_size=bb_size, street=street, wetness=texture["wetness"])

        # Standard check/call/fold resolution
        call_cut = max(0.20, pot_odds * (0.95 - 0.08 * pressure))
        if villain.get("is_maniac"):
            call_cut -= 0.04
        if street >= 5 and has_nut_flush_blocker and not villain.get("is_nit"):
            # Nut flush blocker makes opponent's river bet polarized air -> widen bluff-catching range
            call_cut -= 0.05
        if "call" in legal and strength >= call_cut:
            return {"type": "call"}
        if "check" in legal:
            return {"type": "check"}
        if "fold" in legal:
            return {"type": "fold"}
        if "allIn" in legal:
            return {"type": "allIn"}
        if "call" in legal:
            return {"type": "call"}
        if "raise" in legal:
            return self._sized_raise(legal, strength=strength, value=False, pressure=pressure, pot=pot, bb_size=bb_size)
        if "bet" in legal:
            return self._sized_bet(legal, value=False, pressure=pressure, pot=pot, bb_size=bb_size)
        return self._safe_action(legal)

    def _preflop(self, legal: dict[str, Any], hero: list[Any], obs: dict[str, Any], pressure: float, villain: dict[str, Any]) -> dict[str, Any]:
        a, b = sorted([c.rank for c in hero], reverse=True)
        pair = a == b
        # Percentile among the 169 starting-hand classes: suitedness and connectedness are
        # already priced into it, so they no longer need separate threshold tweaks.
        score = self._preflop_strength(hero)
        pot = float(obs.get("pot", 0) or 0)
        call = float(legal.get("call", 0) or 0)
        bb_size = float(obs.get("big_blind", 200) or 200)
        is_opening = call <= bb_size * 1.05 and pot <= 3.5 * bb_size

        # Position analysis
        _pos_tag, pos_mult, is_steal = self._preflop_position_factor(obs)

        # Short-stack Push/Fold logic (ICM / shallow stack <= 12 BB)
        hero_stack = float(obs.get("stack", 0) or 0)
        effective_bb = hero_stack / max(1.0, bb_size)

        premium = pair and a >= 10 or (a >= 13 and b >= 11) or (a == 14 and b >= 10)

        # Opponents already matching the current bet (hero excluded). One or more callers
        # in front of a raise makes this a squeeze spot, not a cold three-bet.
        callers = sum(
            1 for p in (obs.get("players") or [])
            if p.get("agentId") != obs.get("agentId")
            and not p.get("folded")
            and float(p.get("currentBet", 0) or 0) >= max(call, bb_size)
        )
        is_squeeze = (not is_opening) and callers >= 1

        if effective_bb <= 12.0:
            # Short-stack push/fold: the genome's VPIP sets how wide the shove is.
            push_vpip = (0.18 + self.params.vpip * 0.6) - 0.10 * pressure + (0.10 if is_steal else 0.0)
            push_vpip = max(0.05, min(0.75, push_vpip))
            if premium or score >= 1.0 - push_vpip:
                if "allIn" in legal:
                    return {"type": "allIn"}
                if "raise" in legal:
                    return {"type": "raise", "amount": int(legal["raise"][1])}
                if "call" in legal:
                    return {"type": "call"}
            elif call == 0 and "check" in legal:
                return {"type": "check"}
            elif "fold" in legal:
                return {"type": "fold"}

        # A VPIP target is a percentile bar: play the top `vpip` fraction of hands,
        # loosened by position and tightened by tournament pressure.
        vpip_target = self.params.vpip * (0.75 + 0.45 * pos_mult)
        vpip_target *= (1.0 - 0.25 * max(0.0, pressure)) * (1.0 + 0.20 * max(0.0, -pressure))
        if villain.get("is_station"):
            vpip_target *= 0.90   # stations never fold, so speculative hands lose value
        elif villain.get("is_nit") or villain.get("fold", 0.52) > 0.58:
            vpip_target *= 1.10   # opponents over-fold: entering wider is cheap
        vpip_target = max(0.03, min(0.95, vpip_target))
        in_range = premium or score >= 1.0 - vpip_target

        # "bet" is the opening wager when there is nothing to call (e.g. the big blind's
        # option), so an opening raise must be offered for either key.
        if "raise" in legal or "bet" in legal:
            if is_opening:
                freq = self.params.open_frequency
            elif is_squeeze:
                freq = self.params.squeeze_frequency
            else:
                freq = self.params.threebet_frequency
            freq *= pos_mult
            if is_steal:
                steal_freq = self.params.steal_frequency
                if villain.get("fold", 0.52) > 0.58:
                    steal_freq = min(0.95, steal_freq * 1.25)
                elif villain.get("is_station"):
                    steal_freq *= 0.80
                freq = max(freq, steal_freq)
            if premium:
                self._hero_is_aggressor = True
                return self._preflop_raise(legal, premium=True, bb_size=bb_size)
            if in_range and self._noise(freq * (1.0 + 0.4 * pressure)):
                self._hero_is_aggressor = True
                return self._preflop_raise(legal, premium=False, bb_size=bb_size)

        if "call" in legal:
            if in_range and (self._noise(0.92) or premium):
                return {"type": "call"}

        if "check" in legal:
            return {"type": "check"}
        if "fold" in legal:
            return {"type": "fold"}
        if "call" in legal:
            return {"type": "call"}
        if "allIn" in legal:
            return {"type": "allIn"}
        if "raise" in legal:
            return self._sized_raise(legal, pot=pot, bb_size=bb_size, strength=score, value=premium, pressure=pressure)
        if "bet" in legal:
            return self._sized_bet(legal, pot=pot, bb_size=bb_size, value=premium, pressure=pressure)
        return self._safe_action(legal)

    def _preflop_raise(self, legal: dict[str, Any], premium: bool, bb_size: float = 200.0) -> dict[str, Any]:
        spec = legal.get("raise", legal.get("bet"))
        if not spec:
            return {"type": "allIn"} if "allIn" in legal else {"type": "call"}
        lo, hi = int(spec[0]), int(spec[1])
        action_type = "raise" if "raise" in legal else "bet"
        if lo >= hi:
            if "allIn" in legal:
                return {"type": "allIn"}
            return {"type": action_type, "amount": hi}
        target = int((self.params.open_size + (0.6 if premium else 0.0)) * bb_size)
        return {"type": action_type, "amount": max(lo, min(hi, target))}

    def _equity(self, hero: list[Any], board: list[Any], opponents: int) -> float:
        """Win probability against `opponents` live hands.

        The cheap path runs the heuristic evaluator and then maps its score through the
        offline calibration table, so the returned number is a probability that can be
        compared with pot odds and that accounts for how many players are still in.
        Previously the raw heuristic score was compared against pot odds directly.
        """
        samples = int(self.params.equity_samples)
        if samples > 0:
            return equity_exact(hero, board, max(1, opponents), samples, self.rng)
        raw = evaluate_relative_strength(hero, board)["strength"]
        return strength_to_equity(len(board), opponents, raw)

    def _tournament_pressure(self, ctx: dict[str, Any]) -> float:
        rank = ctx.get("rank")
        r12 = ctx.get("rank12_bb100")
        r13 = ctx.get("rank13_bb100")
        bb = ctx.get("bb100")
        rem = ctx.get("hands_remaining")
        round_no = ctx.get("round_no")
        if rank is None:
            return 0.0

        rem_val = max(0, int(rem)) if rem is not None else 50
        pressure = 0.0

        # Semifinal stage (Round 11: 6-max, Top 3 qualify to final table)
        if round_no == 11:
            if rank <= 3:
                r4 = ctx.get("rank4_bb100")
                if r4 is not None and bb is not None and (float(bb) - float(r4)) > 15.0 and rem_val <= 8:
                    pressure -= self.params.safety * 0.4
                else:
                    pressure += 0.05
            else:
                # Rank 4..6 is currently eliminated! Must attack to qualify
                pressure += self.params.attack + 0.20
                if rem_val <= 10:
                    pressure += (self.params.bubble_aggression - 0.5) * 0.6 + self.params.late_aggression
            return max(-1.0, min(1.0, pressure))

        # Final table stage (Round 12: 6-max, Winner-Take-All for Championship!)
        if round_no == 12:
            if rank == 1:
                # Leading the final table: maintain pressure without reckless punting
                r2 = ctx.get("rank2_bb100") or ctx.get("second_bb100")
                if r2 is not None and bb is not None and (float(bb) - float(r2)) > 20.0 and rem_val <= 8:
                    pressure -= self.params.safety * 0.4
                else:
                    pressure += 0.10
            else:
                # Rank 2..6: Losing the championship! Attack to take 1st place
                pressure += self.params.attack + 0.25
                if rem_val <= 15:
                    pressure += (self.params.bubble_aggression - 0.5) * 0.6 + self.params.late_aggression
                if rem_val <= 8:
                    pressure = min(1.0, pressure + 0.35)
            return max(-1.0, min(1.0, pressure))

        # Preliminary stage (Rounds 1-10: 200 hands, Top 12 qualify)
        if r12 is not None and bb is not None:
            gap = float(bb) - float(r12)
            if rank <= 12 and gap > 1.5:
                pressure -= self.params.safety
            elif rank >= 13 or gap < 0:
                pressure += self.params.attack
        if r13 is not None and bb is not None and rank <= 12 and float(bb) < float(r13) + 0.5:
            pressure += 0.10
        if rem_val <= 20:
            # On the bubble (straddling the qualification line) how hard to press is
            # a trait the genome chooses via bubble_aggression, not a constant.
            if 10 <= rank <= 15:
                pressure += (self.params.bubble_aggression - 0.5) * 0.6
            pressure += self.params.late_aggression if rank >= 13 else -0.05
        if rem_val <= 10:
            pressure *= 1.20
        return max(-1.0, min(1.0, pressure))

    def _should_aggress(self, base: float, pressure: float, strength: float) -> bool:
        p = base + 0.15 * max(0.0, pressure) + 0.10 * max(0.0, strength - 0.7)
        return self._noise(max(0.05, min(0.98, p)))

    def _sized_raise(self, legal: dict[str, Any], strength: float = 0.5, value: bool = True, pressure: float = 0.0, size_mult: float = 1.0, pot: float = 0.0, bb_size: float = 200.0, wetness: float | None = None) -> dict[str, Any]:
        spec = legal.get("raise", legal.get("bet"))
        if not spec:
            return {"type": "allIn"} if "allIn" in legal else {"type": "call"}
        lo, hi = map(int, spec)
        action_type = "raise" if "raise" in legal else "bet"
        if lo >= hi:
            if "allIn" in legal:
                return {"type": "allIn"}
            return {"type": action_type, "amount": hi}
        if strength >= self.params.jam_threshold and (pressure > 0.2 or value):
            return {"type": "allIn"} if "allIn" in legal else {"type": action_type, "amount": hi}
        # raise_size is the genome's dedicated raise-sizing knob
        base = self.params.raise_size if value else self.params.bluff_bet_size
        if wetness is not None:
            w = max(0.0, min(1.0, float(wetness)))
            # Wet board raises slightly larger to charge draws; dry board raises smaller
            texture_raise_bias = (self.params.wet_board_bet_size - self.params.dry_board_bet_size) * (w - 0.5) * 0.25
            base = max(0.25, base + texture_raise_bias)
        frac = (base + 0.10 * max(0.0, pressure) + 0.12 * max(0.0, strength - 0.75)) * size_mult
        if pot > 0:
            target = int(lo + pot * frac * 0.5)
        else:
            target = int(lo + (hi - lo) * max(0.05, min(0.90, frac)))
        return {"type": action_type, "amount": max(lo, min(hi, target))}

    def _sized_bet(self, legal: dict[str, Any], value: bool = True, pressure: float = 0.0, size_mult: float = 1.0, pot: float = 0.0, bb_size: float = 200.0, street: int | None = None, is_cbet: bool = False, wetness: float | None = None) -> dict[str, Any]:
        spec = legal.get("bet", legal.get("raise"))
        if not spec:
            return {"type": "allIn"} if "allIn" in legal else ({"type": "check"} if "check" in legal else {"type": "call"})
        lo, hi = map(int, spec)
        action_type = "bet" if "bet" in legal else "raise"
        if lo >= hi:
            if "allIn" in legal:
                return {"type": "allIn"}
            return {"type": action_type, "amount": hi}

        # Dynamic board texture sizing: smoothly interpolate between dry and wet board bet sizes
        w = 0.5 if wetness is None else max(0.0, min(1.0, float(wetness)))
        texture_size = self.params.dry_board_bet_size + (self.params.wet_board_bet_size - self.params.dry_board_bet_size) * w

        if is_cbet and street == 3:
            # Continuation bet: blend cbet_size with board texture sizing
            base = 0.45 * self.params.cbet_size + 0.55 * texture_size
        else:
            bet_genome = self.params.value_bet_size if value else self.params.bluff_bet_size
            base = 0.40 * bet_genome + 0.60 * texture_size

        frac = (base + 0.08 * max(0.0, pressure)) * size_mult
        if pot > 0:
            target = int(max(pot * frac, bb_size))
        else:
            target = int(lo + (hi - lo) * max(0.05, min(0.88, frac)))
        return {"type": action_type, "amount": max(lo, min(hi, target))}

    def _noise(self, probability: float) -> bool:
        t = max(0.0, min(1.0, self.params.temperature))
        probability = probability * (1 - t) + 0.5 * t
        return self.rng.random() < probability

    def _board_texture(self, board: list[Any]) -> dict[str, float]:
        ranks = [c.rank for c in board]
        suits = [c.suit for c in board]
        paired = len(set(ranks)) < len(ranks)
        flushish = max(suits.count(s) for s in set(suits)) >= 3
        uniq = sorted(set(ranks))
        connected = any(all(x in uniq for x in range(h - 4, h + 1)) for h in range(6, 15))
        return {"wetness": 1.0 if flushish or connected else (0.5 if paired else 0.2), "draws": float(flushish) + float(connected)}

    def _observe_opponents(self, obs: dict[str, Any]) -> None:
        """Fold newly observed actions into the opponent model.

        Only actions appended since the previous decision are consumed (a per-hand
        cursor), so each action is counted exactly once. Rescanning the full history on
        every decision used to re-count every prior action -- one opponent accumulated
        tens of thousands of phantom raises per tournament -- and made the simulator
        quadratic in hand length.
        """
        hero_id = obs.get("agentId")
        hand = obs.get("hand") or {}
        actions = obs.get("recent_actions")
        if not actions:
            actions = hand.get("actions") or []

        hid = obs.get("hand_id")
        new_hand = hid != self._obs_hand_id
        # A shorter list than the cursor means a fresh hand with no usable hand_id.
        if new_hand or len(actions) < self._obs_cursor:
            self._obs_hand_id = hid
            self._obs_cursor = 0
            self._vpip_seen = set()
            if new_hand:
                self._hero_is_aggressor = False
                for p in obs.get("players") or []:
                    aid = p.get("agentId")
                    if aid and aid != hero_id:
                        self.opponents.setdefault(aid, OpponentStats()).hands += 1

        cursor = min(self._obs_cursor, len(actions))
        new_actions = actions[cursor:]
        self._obs_cursor = len(actions)

        for a in new_actions:
            aid = a.get("agentId")
            if not aid or aid == hero_id:
                continue
            typ = a.get("type")
            if typ in {"smallBlind", "bigBlind"}:
                continue
            stats = self.opponents.setdefault(aid, OpponentStats())
            if typ in {"raise", "bet", "allIn"}:
                stats.raises += 1
                stats.bets += 1
            elif typ == "call":
                stats.calls += 1
            elif typ == "fold":
                stats.folds += 1
            elif typ == "check":
                stats.checks += 1
            else:
                continue
            # VPIP is a per-hand property: count the first voluntary money-in only.
            if typ in {"raise", "bet", "allIn", "call"} and aid not in self._vpip_seen:
                stats.vpip += 1
                self._vpip_seen.add(aid)
            stats.last_seen += 1

    @staticmethod
    def _preflop_strength(hero: list[Any]) -> float:
        """Starting-hand strength in [0, 1], 1 = strongest.

        Prefers the calibrated percentile among the 169 starting-hand classes, which is
        what lets a VPIP target mean "play the top X% of hands". Falls back to a rescaled
        version of the old raw score if the calibration table is unavailable -- the old
        score compressed almost every hand above 0.31, which is why every archetype
        ended up playing roughly the same (very wide) range.
        """
        pct = preflop_percentile(hero)
        if pct is not None:
            return pct
        a, b = sorted([c.rank for c in hero], reverse=True)
        score = (a + b) / 28.0
        if a == b: score += 0.30
        if hero[0].suit == hero[1].suit: score += 0.05
        if a - b <= 2: score += 0.045
        if a >= 13 and b >= 10: score += 0.11
        if a == 14: score += 0.04
        return max(0.0, min(1.0, (score - 0.30) / 0.70))

    def _choose_remote(self, obs: dict[str, Any]) -> dict[str, Any]:
        req = obs.get("actionRequest") or {}
        allowed = req.get("allowedActions") or []
        amap = {a["type"]: a for a in allowed if isinstance(a, dict) and a.get("type")}
        table = obs.get("table") or {}
        hand = table.get("hand") or {}
        me = next((p for p in table.get("players") or [] if p.get("agentId") == obs.get("agentId")), None)
        if not me or not isinstance(me.get("handState"), dict) or len(me["handState"].get("holeCards") or []) != 2:
            return self._safe_action(amap)
        legal = self._legal_map(amap)
        players = []
        for p in table.get("players") or []:
            hs = p.get("handState") if isinstance(p.get("handState"), dict) else None
            players.append({
                "agentId": p.get("agentId"),
                "stack": p.get("stack", 0),
                "folded": bool(hs and hs.get("status") == "folded"),
                "allIn": bool(hs and hs.get("status") == "allIn"),
                "currentBet": hs.get("currentBet", 0) if hs else 0,
            })
        dealer_seat = table.get("dealerSeat") or table.get("buttonSeat") or hand.get("buttonSeat")
        local = {
            "hero": me["handState"]["holeCards"],
            "board": hand.get("communityCards") or [],
            "pot": hand.get("pot", 0),
            "current_bet": me["handState"].get("currentBet", 0),
            "stack": me.get("stack", 0),
            "players": players,
            "legal": legal,
            "context": obs.get("tournamentContext") or {},
            "hand": hand,
            "hand_id": hand.get("id"),
            "agentId": obs.get("agentId"),
            "dealer_seat": dealer_seat,
            "position": me.get("seat"),
            "big_blind": table.get("bigBlind") or 200,
        }
        return self.choose_local(local)

    @staticmethod
    def _legal_map(amap: dict[str, Any]) -> dict[str, Any]:
        out = {}
        for k, v in amap.items():
            if k in ("fold", "check"): out[k] = None
            elif k in ("call", "allIn"): out[k] = int(v.get("amount", 0))
            elif k in ("raise", "bet"): out[k] = (int(v.get("minAmount", 0)), int(v.get("maxAmount", 0)))
        return out

    @staticmethod
    def _safe_action(amap: dict[str, Any]) -> dict[str, Any]:
        for k in ("check", "call", "fold", "allIn", "raise", "bet"):
            if k in amap:
                if k in ("raise", "bet"):
                    spec = amap[k]
                    if isinstance(spec, (tuple, list)):
                        lo, hi = int(spec[0]), int(spec[1])
                        return {"type": k, "amount": min(lo, hi)}
                    elif isinstance(spec, dict):
                        lo = int(spec.get("minAmount", 1))
                        hi = int(spec.get("maxAmount", lo))
                        return {"type": k, "amount": min(lo, hi)}
                    return {"type": k, "amount": int(spec.get("minAmount", spec.get("amount", 1)))}
                return {"type": k}
        raise ValueError("no legal action")

    def save(self, path: str | Path) -> None:
        p = Path(path); p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"version": 2, "params": asdict(self.params)}, ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path, profiles: dict[str, Any] | str | Path | None = None) -> StrategyAgent:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        raw = data.get("champion") or data.get("params") or data
        valid_keys = set(asdict(StrategyParams()).keys())
        params_dict = {k: v for k, v in raw.items() if k in valid_keys} if isinstance(raw, dict) else raw
        agent = cls(StrategyParams(**params_dict))
        if profiles is not None:
            agent.load_opponent_profiles(profiles)
        return agent
