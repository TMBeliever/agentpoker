from __future__ import annotations
from dataclasses import dataclass, asdict, field
from pathlib import Path
import json, math, random
from typing import Any
from .cards import parse_card, full_hand_rank, equity_exact, evaluate_relative_strength

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
    # Bet sizing
    open_size: float = 2.35
    cbet_size: float = 0.47
    value_bet_size: float = 0.69
    bluff_bet_size: float = 0.55
    raise_size: float = 0.68
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
        self._seen_hands: set[str] = set()
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

        # Strong value hands: raise or bet
        value_cut = self.params.value_threshold - 0.06 * pressure
        if villain.get("is_station"):
            # Stations call down with weaker holdings: widen value betting range
            value_cut -= 0.04

        if strength >= value_cut:
            size_boost = 1.15 if villain.get("is_station") else 1.0
            if "raise" in legal and self._should_aggress(self.params.raise_threshold + 0.04 * texture["wetness"], pressure, strength):
                return self._sized_raise(legal, strength=strength, value=True, pressure=pressure, size_mult=size_boost, pot=pot, bb_size=bb_size)
            if "bet" in legal and self._should_aggress(0.55, pressure, strength):
                return self._sized_bet(legal, value=True, pressure=pressure, size_mult=size_boost, pot=pot, bb_size=bb_size)
            if "call" in legal:
                return {"type": "call"}
            if "check" in legal:
                return {"type": "check"}

        # Semi-bluffs / draws
        draw_bias = texture["draws"]
        semi_threshold = max(0.29, pot_odds * 0.80)
        if strength >= semi_threshold and (draw_bias > 0 or strength > self.params.thin_value_threshold):
            semi_cbet = self.params.cbet_frequency * (0.65 + 0.5 * pressure)
            if villain.get("fold", 0.52) > 0.58:
                semi_cbet *= 1.25
            if "raise" in legal and self._noise(semi_cbet):
                return self._sized_raise(legal, strength=strength, value=False, pressure=pressure, pot=pot, bb_size=bb_size)
            if "call" in legal and strength >= pot_odds * 0.88:
                return {"type": "call"}

        # Controlled bluffs (heavily suppressed against stations, boosted against high-folders)
        bluff_rate = self.params.river_bluff_frequency if len(board) >= 5 else self.params.cbet_frequency * 0.18
        bluff_rate *= (1.0 + pressure * 0.65)
        if villain.get("is_station"):
            bluff_rate *= 0.15  # Never bluff a calling station
        elif villain.get("fold", 0.52) > 0.58:
            bluff_rate *= 1.35  # High fold equity

        if "raise" in legal and self._noise(bluff_rate):
            return self._sized_raise(legal, strength=max(strength, 0.25), value=False, pressure=pressure, pot=pot, bb_size=bb_size)
        if "bet" in legal and self._noise(bluff_rate):
            return self._sized_bet(legal, value=False, pressure=pressure, pot=pot, bb_size=bb_size)

        # Standard check/call/fold resolution
        call_cut = max(0.20, pot_odds * (0.95 - 0.08 * pressure))
        if villain.get("is_maniac"):
            call_cut -= 0.04
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
        raise ValueError("no legal action")

    def _preflop(self, legal: dict[str, Any], hero: list[Any], obs: dict[str, Any], pressure: float, villain: dict[str, Any]) -> dict[str, Any]:
        a, b = sorted([c.rank for c in hero], reverse=True)
        suited = hero[0].suit == hero[1].suit
        pair = a == b
        gap = a - b
        score = self._preflop_strength(hero)
        pot = float(obs.get("pot", 0) or 0)
        call = float(legal.get("call", 0) or 0)
        bb_size = float(obs.get("big_blind", 200) or 200)
        is_opening = call <= bb_size * 1.05 and pot <= 3.5 * bb_size

        # Position analysis
        pos_tag, pos_mult, is_steal = self._preflop_position_factor(obs)

        # Short-stack Push/Fold logic (ICM / shallow stack <= 12 BB)
        hero_stack = float(obs.get("stack", 0) or 0)
        effective_bb = hero_stack / max(1.0, bb_size)

        premium = pair and a >= 10 or (a >= 13 and b >= 11) or (a == 14 and b >= 10)

        if effective_bb <= 12.0:
            push_threshold = 0.44 - 0.08 * pressure - (0.06 if is_steal else 0.0)
            if premium or score >= push_threshold:
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

        # Standard preflop ranges
        playable_cut = (0.40 - 0.06 * pressure) / max(0.5, pos_mult)
        playable = score >= playable_cut

        if "raise" in legal:
            freq = (self.params.open_frequency if is_opening else self.params.threebet_frequency) * pos_mult
            if is_steal:
                steal_freq = self.params.steal_frequency
                if villain.get("fold", 0.52) > 0.58:
                    steal_freq = min(0.95, steal_freq * 1.25)
                elif villain.get("is_station"):
                    steal_freq *= 0.80
                freq = max(freq, steal_freq)
            if premium:
                return self._preflop_raise(legal, premium=True, bb_size=bb_size)
            if playable and self._noise(freq * (1.0 + 0.4 * pressure)):
                return self._preflop_raise(legal, premium=False, bb_size=bb_size)

        if "call" in legal:
            threshold = 0.31 - 0.04 * pressure
            if suited: threshold -= 0.015
            if gap <= 1: threshold -= 0.015
            if pos_tag == "btn": threshold -= 0.02
            if score >= threshold and (self._noise(0.92) or premium):
                return {"type": "call"}

        if "check" in legal:
            return {"type": "check"}
        if "fold" in legal:
            return {"type": "fold"}
        if "call" in legal:
            return {"type": "call"}
        if "allIn" in legal:
            return {"type": "allIn"}
        return self._sized_raise(legal, pot=pot, bb_size=bb_size, strength=score, value=premium, pressure=pressure)

    def _preflop_raise(self, legal: dict[str, Any], premium: bool, bb_size: float = 200.0) -> dict[str, Any]:
        spec = legal["raise"]
        lo, hi = int(spec[0]), int(spec[1])
        target = int((self.params.open_size + (0.6 if premium else 0.0)) * bb_size)
        target = max(lo, target)
        return {"type": "raise", "amount": max(lo, min(hi, target))}

    def _equity(self, hero: list[Any], board: list[Any], opponents: int) -> float:
        samples = int(self.params.equity_samples)
        if samples <= 0:
            return evaluate_relative_strength(hero, board)["strength"]
        return equity_exact(hero, board, max(1, opponents), samples, self.rng)

    def _tournament_pressure(self, ctx: dict[str, Any]) -> float:
        rank = ctx.get("rank")
        r12 = ctx.get("rank12_bb100")
        r13 = ctx.get("rank13_bb100")
        bb = ctx.get("bb100")
        rem = ctx.get("hands_remaining")
        if rank is None:
            return 0.0
        pressure = 0.0
        if r12 is not None and bb is not None:
            gap = float(bb) - float(r12)
            if rank <= 12 and gap > 1.5:
                pressure -= self.params.safety
            elif rank >= 13 or gap < 0:
                pressure += self.params.attack
        if r13 is not None and bb is not None and rank <= 12 and float(bb) < float(r13) + 0.5:
            pressure += 0.10
        if rem is not None:
            rem = max(0, int(rem))
            if rem <= 20:
                pressure += self.params.late_aggression if rank >= 13 else -0.05
            if rem <= 10:
                pressure *= 1.20
        return max(-1.0, min(1.0, pressure))

    def _should_aggress(self, base: float, pressure: float, strength: float) -> bool:
        p = base + 0.15 * max(0.0, pressure) + 0.10 * max(0.0, strength - 0.7)
        return self._noise(max(0.05, min(0.98, p)))

    def _sized_raise(self, legal: dict[str, Any], strength: float = 0.5, value: bool = True, pressure: float = 0.0, size_mult: float = 1.0, pot: float = 0.0, bb_size: float = 200.0) -> dict[str, Any]:
        lo, hi = map(int, legal["raise"])
        if strength >= self.params.jam_threshold and (pressure > 0.2 or value):
            return {"type": "raise", "amount": hi}
        base = self.params.value_bet_size if value else self.params.bluff_bet_size
        frac = (base + 0.10 * max(0.0, pressure) + 0.12 * max(0.0, strength - 0.75)) * size_mult
        if pot > 0:
            target = int(lo + pot * frac * 0.5)
        else:
            target = int(lo + (hi - lo) * max(0.05, min(0.90, frac)))
        return {"type": "raise", "amount": max(lo, min(hi, target))}

    def _sized_bet(self, legal: dict[str, Any], value: bool = True, pressure: float = 0.0, size_mult: float = 1.0, pot: float = 0.0, bb_size: float = 200.0) -> dict[str, Any]:
        lo, hi = map(int, legal.get("bet", legal.get("raise")))
        frac = ((self.params.value_bet_size if value else self.params.bluff_bet_size) + 0.08 * max(0.0, pressure)) * size_mult
        if pot > 0:
            target = int(max(pot * frac, bb_size))
        else:
            target = int(lo + (hi - lo) * max(0.05, min(0.88, frac)))
        return {"type": "bet", "amount": max(lo, min(hi, target))}

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
        hero_id = obs.get("agentId")
        hand = obs.get("hand") or {}
        actions = hand.get("actions") or obs.get("recent_actions") or []
        for a in actions:
            aid = a.get("agentId")
            if not aid or aid == hero_id:
                continue
            stats = self.opponents.setdefault(aid, OpponentStats())
            typ = a.get("type")
            if typ in {"smallBlind", "bigBlind"}:
                continue
            if typ in {"raise", "bet"}:
                stats.raises += 1
                stats.bets += 1
            elif typ == "call":
                stats.calls += 1
            elif typ == "fold":
                stats.folds += 1
            elif typ == "check":
                stats.checks += 1
            stats.last_seen += 1

    @staticmethod
    def _preflop_strength(hero: list[Any]) -> float:
        a, b = sorted([c.rank for c in hero], reverse=True)
        score = (a + b) / 28.0
        if a == b: score += 0.30
        if hero[0].suit == hero[1].suit: score += 0.05
        if a - b <= 2: score += 0.045
        if a >= 13 and b >= 10: score += 0.11
        if a == 14: score += 0.04
        return min(1.0, score)

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
                    return {"type": k, "amount": int(spec.get("minAmount", spec.get("amount", 1)))}
                return {"type": k}
        raise ValueError("no legal action")

    def save(self, path: str | Path) -> None:
        p = Path(path); p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"version": 2, "params": asdict(self.params)}, ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path, profiles: dict[str, Any] | str | Path | None = None) -> StrategyAgent:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        agent = cls(StrategyParams(**data.get("params", data)))
        if profiles is not None:
            agent.load_opponent_profiles(profiles)
        return agent
