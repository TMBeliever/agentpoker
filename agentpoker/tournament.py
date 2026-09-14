from __future__ import annotations
from dataclasses import dataclass
import math
from random import Random
from typing import Any
from .config import TournamentConfig
from .engine import NLHEngine
from .context import build_context, TableStrengthModel
from .pairing import random_groups, swiss_groups
from .scoring import Standing, bb100, rank_standings
from .strategy import StrategyAgent, StrategyParams

@dataclass
class SimAgent:
    agent_id:str
    strategy:StrategyAgent


def snake_seeding(items: list[Any], num_tables: int) -> list[list[Any]]:
    """Partition ranked items across tables using standard snake-seeding order.

    For 2 tables with 12 players:
    Table 0 receives seeds: 1, 4, 5, 8, 9, 12 (0-indexed: 0, 3, 4, 7, 8, 11)
    Table 1 receives seeds: 2, 3, 6, 7, 10, 11 (0-indexed: 1, 2, 5, 6, 9, 10)
    """
    if num_tables <= 1:
        return [list(items)]
    tables: list[list[Any]] = [[] for _ in range(num_tables)]
    forward = True
    idx = 0
    for item in items:
        tables[idx].append(item)
        if forward:
            if idx == num_tables - 1:
                forward = False
            else:
                idx += 1
        else:
            if idx == 0:
                forward = True
            else:
                idx -= 1
    return tables


class LeagueSimulator:
    def __init__(self, agents:list[SimAgent], sb=100, bb=200, rounds=10, hands_per_round=20, seats=6, min_completion=0.80, seed=7, config: TournamentConfig | None = None):
        if config is not None:
            self.config = config
        else:
            self.config = TournamentConfig(
                field_size=max(12, len(agents)),
                small_blind=sb,
                big_blind=bb,
                starting_stack_bb=100,
                seats_per_table=seats,
                preliminary_rounds=rounds,
                hands_per_round=hands_per_round,
                min_completion_rate=min_completion,
            )
        self.agents = agents
        self.rounds = self.config.preliminary_rounds
        self.hpr = self.config.hands_per_round
        self.seats = self.config.seats_per_table
        self.min_completion = self.config.min_completion_rate
        self.engine = NLHEngine(self.config.small_blind, self.config.big_blind, seed)
        self.rng = Random(seed)
        self.big_blind = self.config.big_blind

    def _state(self):
        return {
            a.agent_id: {
                'stack': 100 * self.big_blind,
                'initial_stack': 100 * self.big_blind,
                'rebuy_count': 0,
                'rebuy_cost_bb': 0.0,
                'gross_winnings_bb': 0.0,
                'gross_losses_bb': 0.0,
                'net_bb': 0.0,
                'hands': 0,
                'last_round_bb100': None,
                'from_r4_net_bb': 0.0,
                'from_r4_hands': 0,
            }
            for a in self.agents
        }

    def _standings(self, st):
        tie_round = {aid: float(v.get('from_r4_net_bb', 0.0) or 0.0) for aid, v in st.items()}
        rows = [Standing(aid, v['hands'], v['net_bb'], bb100(v['net_bb'], v['hands'])) for aid, v in st.items()]
        return rank_standings(rows, tie_round=tie_round)

    def _context(self, aid, st, round_no, hands_remaining):
        return self._context_map(st, round_no, hands_remaining).get(aid, {})

    def _context_map(self, st, round_no, hands_remaining, table_strength_map=None, active_ids=None):
        """Tournament context for every agent, computed once per hand."""
        rows = self._standings(st)
        qual_rank = self.config.semifinal_qualifiers
        r_qual = next((x.bb100 for x in rows if x.rank == qual_rank), None)
        r_bubble = next((x.bb100 for x in rows if x.rank == qual_rank + 1), None)
        ts_map = table_strength_map or {}
        target_rows = [x for x in rows if x.agent_id in active_ids] if active_ids is not None else rows
        return {
            x.agent_id: build_context(
                x.rank, x.bb100, r_qual, r_bubble, hands_remaining, round_no,
                table_strength=ts_map.get(x.agent_id, 0.0),
                stage="preliminary",
                target_rank=qual_rank,
                total_stage_hands=self.config.total_preliminary_hands,
            )
            for x in target_rows
        }

    def _play_group(self, group, st, round_no, hands_this_round):
        dealer = 0
        policies = {a.agent_id: a.strategy for a in self.agents}

        # Apply progressive/scheduled blinds for this round
        cur_sb, cur_bb = self.config.get_blinds(round_no, stage="preliminary")
        self.engine.sb = cur_sb
        self.engine.bb = cur_bb

        # Table strength metric for Swiss pairing and random rounds (strictly excluding Hero)
        ts_map = TableStrengthModel.compute_table_strength_map(group, st)

        group_set = set(group)
        for hand_i in range(hands_this_round):
            # Check for any busted players before the hand: auto-rebuy 100 BB
            for aid in group:
                if st[aid]['stack'] <= 0:
                    st[aid]['stack'] = 100 * self.big_blind
                    st[aid]['rebuy_count'] += 1
                    st[aid]['rebuy_cost_bb'] += 100.0

            before = {aid: st[aid]['stack'] for aid in group}
            hands_remaining = self.rounds * self.hpr - (round_no - 1) * self.hpr - hand_i
            provider = self._context_map(st, round_no, hands_remaining, table_strength_map=ts_map, active_ids=group_set).get
            res, dealer = self.engine.play_hand(
                group,
                {aid: st[aid]['stack'] for aid in group},
                dealer,
                policies,
                context_provider=provider,
            )
            for aid in group:
                st[aid]['stack'] = res.final_stacks[aid]
                delta = (st[aid]['stack'] - before[aid]) / self.big_blind
                if delta > 0:
                    st[aid]['gross_winnings_bb'] += delta
                elif delta < 0:
                    st[aid]['gross_losses_bb'] += (-delta)
                st[aid]['hands'] += 1
                if st[aid]['stack'] <= 0:
                    st[aid]['stack'] = 100 * self.big_blind
                    st[aid]['rebuy_count'] += 1
                    st[aid]['rebuy_cost_bb'] += 100.0

                # Unified tournament net calculation:
                st[aid]['net_bb'] = (st[aid]['stack'] - 100 * self.big_blind) / self.big_blind - st[aid]['rebuy_cost_bb']

    def run_preliminary(self):
        st = self._state()
        ids = list(st)
        for rnd in range(1, self.rounds + 1):
            standings = self._standings(st)
            groups = random_groups(ids, self.seats, self.rng) if rnd <= 3 else swiss_groups(ids, seats=self.seats, standings=standings)
            for g in groups:
                g = list(g)
                self.rng.shuffle(g)
                self._play_group(g, st, rnd, self.hpr)
            if rnd == 3:
                for aid, v in st.items():
                    v['_r3_net_bb'] = v['net_bb']
                    v['_r3_hands'] = v['hands']
            if rnd >= 4:
                for aid, v in st.items():
                    v['from_r4_net_bb'] = v['net_bb'] - v.get('_r3_net_bb', 0.0)
                    v['from_r4_hands'] = v['hands'] - v.get('_r3_hands', 0)
        return self._standings(st)

    def run_event(self):
        prelim = self.run_preliminary()
        min_hands = int(self.rounds * self.hpr * self.min_completion)
        qualified = [s for s in prelim if s.hands >= min_hands]
        result = {'preliminary': prelim, 'qualified': [], 'semifinal': [], 'final': []}
        rank_map = {s.agent_id: s.rank for s in prelim}
        byid = {a.agent_id: a for a in self.agents}

        if len(qualified) >= self.config.semifinal_qualifiers:
            # Full 2-table Semifinal -> 1-table Final
            semifinalists = qualified[:self.config.semifinal_qualifiers]
            result['qualified'] = semifinalists
            # Snake seeding: Table 0 = 1, 4, 5, 8, 9, 12; Table 1 = 2, 3, 6, 7, 10, 11
            s_ids = [s.agent_id for s in semifinalists]
            num_sf_tables = max(1, self.config.semifinal_tables)
            groups = snake_seeding(s_ids, num_sf_tables)
            finals = []
            cur_sb, cur_bb = self.config.get_blinds(11, stage="semifinal")
            self.engine.sb = cur_sb
            self.engine.bb = cur_bb

            for grp in groups:
                grp = list(grp)
                self.rng.shuffle(grp)
                local = {
                    aid: {
                        'stack': 100 * self.big_blind,
                        'rebuy_count': 0,
                        'rebuy_cost_bb': 0.0,
                        'gross_winnings_bb': 0.0,
                        'gross_losses_bb': 0.0,
                        'net_bb': 0.0,
                        'hands': 0,
                    }
                    for aid in grp
                }
                dealer = 0
                policies = {a.agent_id: a.strategy for a in self.agents}
                for h in range(self.config.semifinal_hands):
                    for aid in grp:
                        if local[aid]['stack'] <= 0:
                            local[aid]['stack'] = 100 * self.big_blind
                            local[aid]['rebuy_count'] += 1
                            local[aid]['rebuy_cost_bb'] += 100.0
                    before = {aid: local[aid]['stack'] for aid in grp}

                    # Cold-start eliminated: at h=0, rank by preliminary seed (official tiebreak)
                    if h == 0:
                        sf_sorted = sorted(grp, key=lambda aid: rank_map.get(aid, 999))
                    else:
                        sf_sorted = sorted(
                            grp,
                            key=lambda aid: (
                                local[aid]['net_bb'],
                                -rank_map.get(aid, 999)
                            ),
                            reverse=True
                        )

                    r3_aid = sf_sorted[min(2, len(sf_sorted) - 1)]
                    r4_aid = sf_sorted[min(3, len(sf_sorted) - 1)]
                    r3_bb100 = (local[r3_aid]['net_bb'] / max(1, local[r3_aid]['hands']) * 100) if h > 0 else 0.0
                    r4_bb100 = (local[r4_aid]['net_bb'] / max(1, local[r4_aid]['hands']) * 100) if h > 0 else 0.0
                    ts_map = TableStrengthModel.compute_table_strength_map(grp, local)

                    hands_rem = self.config.semifinal_hands - h
                    sf_ctx_map = {}
                    for i, aid in enumerate(sf_sorted, 1):
                        cur_h = local[aid]['hands']
                        cur_b = (local[aid]['net_bb'] / max(1, cur_h) * 100) if h > 0 else 0.0
                        sf_ctx_map[aid] = build_context(
                            rank=i,
                            bb100=cur_b,
                            hands_remaining=hands_rem,
                            round_no=11,
                            stage="semifinal",
                            target_rank=3,
                            total_stage_hands=self.config.semifinal_hands,
                            rank3_bb100=r3_bb100,
                            rank4_bb100=r4_bb100,
                            table_strength=ts_map.get(aid, 0.0),
                        )

                    res, dealer = self.engine.play_hand(
                        grp,
                        {aid: local[aid]['stack'] for aid in grp},
                        dealer,
                        policies,
                        context_provider=sf_ctx_map.get
                    )
                    for aid in grp:
                        local[aid]['stack'] = res.final_stacks[aid]
                        delta = (local[aid]['stack'] - before[aid]) / self.big_blind
                        if delta > 0:
                            local[aid]['gross_winnings_bb'] += delta
                        elif delta < 0:
                            local[aid]['gross_losses_bb'] += (-delta)
                        local[aid]['hands'] += 1
                        if local[aid]['stack'] <= 0:
                            local[aid]['stack'] = 100 * self.big_blind
                            local[aid]['rebuy_count'] += 1
                            local[aid]['rebuy_cost_bb'] += 100.0
                        local[aid]['net_bb'] = (local[aid]['stack'] - 100 * self.big_blind) / self.big_blind - local[aid]['rebuy_cost_bb']

                rows = rank_standings([Standing(aid, v['hands'], v['net_bb'], bb100(v['net_bb'], v['hands'])) for aid, v in local.items()])
                rows.sort(key=lambda x: (-(x.bb100 or float('-inf')), rank_map.get(x.agent_id, 999), x.agent_id))
                for i, x in enumerate(rows, 1):
                    x.rank = i
                result['semifinal'].append(rows)
                finals.extend(rows[:3])
            final_ids = [s.agent_id for s in finals]
        elif len(qualified) >= self.config.final_qualifiers:
            # Scaled tournament: Skip semifinal, top qualifiers advance directly to Final Table
            final_qualifiers = qualified[:self.config.final_qualifiers]
            result['qualified'] = final_qualifiers
            final_ids = [s.agent_id for s in final_qualifiers]
        else:
            # Field too small for final table
            return result

        # Final table match
        cur_sb, cur_bb = self.config.get_blinds(12, stage="final")
        self.engine.sb = cur_sb
        self.engine.bb = cur_bb

        ids = list(final_ids)
        self.rng.shuffle(ids)
        local = {
            aid: {
                'stack': 100 * self.big_blind,
                'rebuy_count': 0,
                'rebuy_cost_bb': 0.0,
                'gross_winnings_bb': 0.0,
                'gross_losses_bb': 0.0,
                'net_bb': 0.0,
                'hands': 0,
            }
            for aid in ids
        }
        dealer = 0
        policies = {a.agent_id: a.strategy for a in self.agents}
        for h in range(self.config.final_hands):
            for aid in ids:
                if local[aid]['stack'] <= 0:
                    local[aid]['stack'] = 100 * self.big_blind
                    local[aid]['rebuy_count'] += 1
                    local[aid]['rebuy_cost_bb'] += 100.0
            before = {aid: local[aid]['stack'] for aid in ids}

            if h == 0:
                f_sorted = sorted(ids, key=lambda aid: rank_map.get(aid, 999))
            else:
                f_sorted = sorted(
                    ids,
                    key=lambda aid: (
                        local[aid]['net_bb'],
                        -rank_map.get(aid, 999)
                    ),
                    reverse=True
                )

            leader_aid = f_sorted[0]
            second_aid = f_sorted[min(1, len(f_sorted) - 1)]
            r1_bb100 = (local[leader_aid]['net_bb'] / max(1, local[leader_aid]['hands']) * 100) if h > 0 else 0.0
            r2_bb100 = (local[second_aid]['net_bb'] / max(1, local[second_aid]['hands']) * 100) if h > 0 else 0.0
            ts_map = TableStrengthModel.compute_table_strength_map(ids, local)

            hands_rem = self.config.final_hands - h
            f_ctx_map = {}
            for i, aid in enumerate(f_sorted, 1):
                cur_h = local[aid]['hands']
                cur_b = (local[aid]['net_bb'] / max(1, cur_h) * 100) if h > 0 else 0.0
                f_ctx_map[aid] = build_context(
                    rank=i,
                    bb100=cur_b,
                    hands_remaining=hands_rem,
                    round_no=12,
                    stage="final",
                    target_rank=1,
                    total_stage_hands=self.config.final_hands,
                    leader_bb100=r1_bb100,
                    second_bb100=r2_bb100,
                    rank1_bb100=r1_bb100,
                    rank2_bb100=r2_bb100,
                    table_strength=ts_map.get(aid, 0.0),
                )

            res, dealer = self.engine.play_hand(
                ids,
                {aid: local[aid]['stack'] for aid in ids},
                dealer,
                policies,
                context_provider=f_ctx_map.get
            )
            for aid in ids:
                local[aid]['stack'] = res.final_stacks[aid]
                delta = (local[aid]['stack'] - before[aid]) / self.big_blind
                if delta > 0:
                    local[aid]['gross_winnings_bb'] += delta
                elif delta < 0:
                    local[aid]['gross_losses_bb'] += (-delta)
                local[aid]['hands'] += 1
                if local[aid]['stack'] <= 0:
                    local[aid]['stack'] = 100 * self.big_blind
                    local[aid]['rebuy_count'] += 1
                    local[aid]['rebuy_cost_bb'] += 100.0
                local[aid]['net_bb'] = (local[aid]['stack'] - 100 * self.big_blind) / self.big_blind - local[aid]['rebuy_cost_bb']

        # Final tie-break by preliminary rank.
        fr = [Standing(aid, v['hands'], v['net_bb'], bb100(v['net_bb'], v['hands'])) for aid, v in local.items()]
        fr = sorted(fr, key=lambda x: (-(x.bb100 if x.bb100 is not None else float('-inf')), rank_map.get(x.agent_id, 999), x.agent_id))
        for i, x in enumerate(fr, 1):
            x.rank = i
        result['final'] = fr
        return result

    def evaluate(self, runs=100):
        if not self.agents: return {'top12_rate':0.0,'final_rate':0.0,'champion_rate':0.0}
        focal=self.agents[0].agent_id; top=final_rate=champ=0
        for i in range(runs):
            sim_agents=[SimAgent(a.agent_id,StrategyAgent(a.strategy.params,seed=1000+i*17+j,name=a.agent_id)) for j,a in enumerate(self.agents)]
            sim=LeagueSimulator(sim_agents,seed=self.engine.rng.randrange(10**9),config=self.config)
            r=sim.run_event()
            if focal in [x.agent_id for x in r['qualified']]: top+=1
            if focal in [x.agent_id for x in r['final']]: final_rate+=1
            if r['final'] and r['final'][0].agent_id==focal: champ+=1
        return {'top12_rate':top/max(1,runs),'final_rate':final_rate/max(1,runs),'champion_rate':champ/max(1,runs)}
