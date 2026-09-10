from __future__ import annotations
from pathlib import Path
import json, re
from typing import Any

class OpponentProfiler:
    """Extracts, aggregates, and Bayesian-smooths opponent profiles from hand history data."""

    def __init__(self):
        self.stats: dict[str, dict[str, Any]] = {}
        self.names: dict[str, str] = {}

    def ingest_hand(self, data: dict[str, Any]) -> None:
        """Ingest a single hand observation, raw event, or API hand dictionary."""
        if isinstance(data, dict) and "actions" in data and "players" in data:
            hand = data
            table = data
        else:
            table = data.get("table") if isinstance(data.get("table"), dict) else data
            hand = table.get("hand") if isinstance(table.get("hand"), dict) else data.get("hand", data)

        if not isinstance(hand, dict) or not hand.get("actions"):
            return

        players = table.get("players") or hand.get("players") or []
        participating_agents = set()
        for p in players:
            if isinstance(p, dict):
                aid = p.get("agentId")
                name = p.get("name")
                if aid:
                    participating_agents.add(aid)
                    if name:
                        self.names[aid] = name
            elif isinstance(p, str):
                participating_agents.add(p)

        for aid in participating_agents:
            st = self.stats.setdefault(aid, {
                "hands": 0,
                "vpip": 0,
                "pfr": 0,
                "raises": 0,
                "bets": 0,
                "calls": 0,
                "folds": 0,
                "checks": 0,
                "allins": 0,
                "wtsd": 0,
                "net_pnl": 0,
            })
            st["hands"] += 1

        for p in players:
            if isinstance(p, dict):
                aid = p.get("agentId")
                if aid and aid in self.stats:
                    self.stats[aid]["net_pnl"] += int(p.get("netChange", 0))

        actions = hand.get("actions") or []
        has_vpip = set()
        has_pfr = set()

        for a in actions:
            if not isinstance(a, dict):
                continue
            aid = a.get("agentId")
            if not aid:
                continue
            st = self.stats.setdefault(aid, {
                "hands": 0,
                "vpip": 0,
                "pfr": 0,
                "raises": 0,
                "bets": 0,
                "calls": 0,
                "folds": 0,
                "checks": 0,
                "allins": 0,
                "wtsd": 0,
                "net_pnl": 0,
            })
            typ = a.get("type")
            street = a.get("street", "preflop")

            if typ in {"smallBlind", "bigBlind"}:
                continue

            if typ in {"raise", "bet"}:
                st["raises"] += 1
                st["bets"] += 1
                if street == "preflop" and aid not in has_pfr:
                    st["pfr"] += 1
                    has_pfr.add(aid)
                if street == "preflop" and aid not in has_vpip:
                    st["vpip"] += 1
                    has_vpip.add(aid)
            elif typ == "allIn":
                st["allins"] += 1
                st["raises"] += 1
                st["bets"] += 1
                if street == "preflop" and aid not in has_pfr:
                    st["pfr"] += 1
                    has_pfr.add(aid)
                if street == "preflop" and aid not in has_vpip:
                    st["vpip"] += 1
                    has_vpip.add(aid)
            elif typ == "call":
                st["calls"] += 1
                if street == "preflop" and aid not in has_vpip:
                    st["vpip"] += 1
                    has_vpip.add(aid)
            elif typ == "fold":
                st["folds"] += 1
            elif typ == "check":
                st["checks"] += 1

        # Check showdown participation
        showdowns = hand.get("showdown") or hand.get("payouts") or []
        if isinstance(showdowns, list):
            for s in showdowns:
                if isinstance(s, dict) and s.get("agentId") in self.stats:
                    self.stats[s["agentId"]]["wtsd"] += 1
        elif isinstance(showdowns, dict):
            for aid in showdowns:
                if aid in self.stats:
                    self.stats[aid]["wtsd"] += 1

    def ingest_file(self, path: str | Path) -> int:
        """Parse a JSONL file containing raw events or exported hands."""
        p = Path(path)
        if not p.exists():
            return 0
        count = 0
        text = p.read_text(encoding="utf-8")
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except Exception:
                continue
            # Support both raw event {'data': {...}} and direct hand dict
            payload = item.get("data", item) if isinstance(item, dict) else item
            self.ingest_hand(payload)
            count += 1
        return count

    def pull_competition_hands(self, client: Any, cid: str, max_hands: int | None = None, save_hands_path: str | Path | None = "data/processed/hands.jsonl") -> int:
        """Fetch completed hands from GET /api/competitions/:cid/hands and ingest them."""
        cursor = None
        total_fetched = 0
        save_file = Path(save_hands_path) if save_hands_path else None
        if save_file:
            save_file.parent.mkdir(parents=True, exist_ok=True)
            f_out = save_file.open("w", encoding="utf-8")
        else:
            f_out = None

        try:
            while True:
                limit = 50
                if max_hands:
                    remaining = max_hands - total_fetched
                    if remaining <= 0:
                        break
                    limit = min(50, remaining)

                resp = client.hands(cid, limit=limit, cursor=cursor)
                hands = resp.get("hands") or []
                if not hands:
                    break

                for h in hands:
                    self.ingest_hand(h)
                    if f_out:
                        f_out.write(json.dumps(h, ensure_ascii=False) + "\n")
                    total_fetched += 1

                if total_fetched % 500 == 0:
                    print(f"[Profiler] Pulled {total_fetched} hands from competition {cid}...")

                cursor = resp.get("nextCursor")
                if not cursor:
                    break
        finally:
            if f_out:
                f_out.close()

        return total_fetched

    def export(
        self,
        out_path: str | Path | None = None,
        prior_weight: float = 8.0,
        min_hands: int = 1,
        filter_afk: bool = False,
    ) -> dict[str, Any]:
        """Export computed smoothed profiles, optionally filtering low-quality agents, saving to JSON."""
        profiles = {}
        filtered = {}
        for aid, st in self.stats.items():
            name = self.names.get(aid, "Unknown")
            hands = st["hands"]

            # Quality Filter 1: Minimum sample size
            if min_hands > 1 and hands < min_hands:
                filtered[aid] = {"name": name, "hands": hands, "reason": f"Sample size too small ({hands} < {min_hands} hands)"}
                continue

            # Quality Filter 2: AFK / Zombie bot filter (disconnected bot auto-folding every hand)
            if filter_afk and hands >= 15:
                raw_fold_rate = st["folds"] / max(1, hands)
                if st["vpip"] == 0 and raw_fold_rate >= 0.95:
                    filtered[aid] = {"name": name, "hands": hands, "reason": f"AFK/Zombie bot (hands={hands}, vpip=0, folds={st['folds']})"}
                    continue

            n = max(1, st["hands"])
            w = max(1.0, float(prior_weight))
            denom = float(st["hands"]) + w
            svpip = (st["vpip"] + w * 0.25) / denom
            spfr = (st["pfr"] + w * 0.16) / denom
            sraise = (st["raises"] + w * 0.16) / denom
            sfold = (st["folds"] + w * 0.52) / denom
            scall = (st["calls"] + w * 0.32) / denom

            af = round((st["raises"] + st["bets"]) / max(1, st["calls"]), 2)
            net_pnl = st.get("net_pnl", 0)
            bb_100 = round((net_pnl / 1000.0) / max(1, st["hands"]) * 100, 1)

            is_station = scall >= 0.38 and sfold <= 0.36
            is_nit = svpip <= 0.18 and sfold >= 0.58
            is_maniac = svpip >= 0.42 and (sraise >= 0.22 or af >= 2.5)
            is_passive = sraise <= 0.10 and af < 0.8
            is_pushfold = (st.get("allins", 0) / max(1, st["hands"])) >= 0.12

            if is_maniac:
                archetype = "Maniac (狂徒/高频乱搞)"
                advice = "绝不河牌纯诈唬；顶对/中对放宽抓诈(Bluff-catch)；手握强牌翻前翻后多做Check-raise引诱其推注。"
            elif is_nit:
                archetype = "Nit (极紧/岩石)"
                advice = "后位无脑偷盲捡底池；对其实施高频C-Bet；一旦其在转牌/河牌反常下注或加注，坚决盖掉中强牌。"
            elif is_station:
                archetype = "Calling Station (跟注站)"
                advice = "绝不进行三条街纯诈唬；顶对好踢脚做大价值下注(75%-100%底池)，他们会用弱对/听牌跟到底。"
            elif is_passive:
                archetype = "Passive (被动鱼)"
                advice = "一旦对方Check直接开枪抢池；对方主动下注或加注代表极强成牌，立即弃牌止损。"
            elif is_pushfold:
                archetype = "Push/Fold (短码梭哈客)"
                advice = "收紧跟注All-In范围至TT+、AQs+；在无弃牌率的情况下不要对其施加轻量诈唬。"
            elif svpip > 0.28 and sraise > 0.18:
                archetype = "LAG (松凶强手)"
                advice = "位置劣势避免玩投机牌；后位利用位置优势做3-bet施压，警惕其转牌河牌连开两枪。"
            elif 0.18 <= svpip <= 0.28 and sraise >= 0.12:
                archetype = "TAG (紧凶稳健)"
                advice = "尊重其早位Open和3-Bet范围；多在底池较小或有位置时针对其翻牌Miss的牌面浮动跟注偷底。"
            else:
                archetype = "Balanced (均衡常规)"
                advice = "按照标准GTO价值/诈唬比例对抗，重点观察其入池位置与下注尺度偏好。"

            profiles[aid] = {
                "name": self.names.get(aid, "Unknown"),
                "hands": st["hands"],
                "vpip_count": st["vpip"],
                "pfr_count": st["pfr"],
                "raises_count": st["raises"],
                "calls_count": st["calls"],
                "folds_count": st["folds"],
                "bets_count": st["bets"],
                "checks_count": st["checks"],
                "allins_count": st.get("allins", 0),
                "wtsd_count": st["wtsd"],
                "net_pnl": net_pnl,
                "bb_100": bb_100,
                "vpip": round(svpip, 3),
                "pfr": round(spfr, 3),
                "raise": round(sraise, 3),
                "fold": round(sfold, 3),
                "call": round(scall, 3),
                "af": af,
                "archetype": archetype,
                "is_station": is_station,
                "is_nit": is_nit,
                "is_maniac": is_maniac,
                "is_passive": is_passive,
                "is_pushfold": is_pushfold,
                "exploit_advice": advice,
            }

        self.last_filtered = filtered
        if filtered:
            print(f"[Profiler] Quality Filter: Filtered out {len(filtered)} low-quality agents ({len(profiles)} retained).")
            for aid, info in filtered.items():
                print(f"  [Filtered] {info['name']:<16} ({info['reason']})")

        if out_path:
            p = Path(out_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(profiles, ensure_ascii=False, indent=2), encoding="utf-8")

        return profiles
