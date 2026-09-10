from __future__ import annotations
from dataclasses import dataclass
from random import Random
from .engine import NLHEngine
from .pairing import random_groups, swiss_groups
from .scoring import Standing, bb100, rank_standings
from .strategy import StrategyAgent, StrategyParams

@dataclass
class SimAgent:
    agent_id:str
    strategy:StrategyAgent

class LeagueSimulator:
    def __init__(self, agents:list[SimAgent], sb=100, bb=200, rounds=10, hands_per_round=20, seats=6, min_completion=0.80, seed=7):
        self.agents=agents; self.rounds=rounds; self.hpr=hands_per_round; self.seats=seats; self.min_completion=min_completion
        self.engine=NLHEngine(sb,bb,seed); self.rng=Random(seed); self.big_blind=bb

    def _state(self):
        return {a.agent_id:{'net_bb':0.0,'hands':0,'stack':100*self.big_blind,'last_round_bb100':None,'from_r4_net_bb':0.0,'from_r4_hands':0} for a in self.agents}

    def _standings(self, st):
        tie_round = {}
        for aid, v in st.items():
            h = int(v.get('from_r4_hands', 0) or 0)
            tie_round[aid] = (float(v.get('from_r4_net_bb', 0) or 0) / h * 100.0) if h > 0 else float('-inf')
        rows=[Standing(aid,v['hands'],v['net_bb'],bb100(v['net_bb'],v['hands'])) for aid,v in st.items()]
        return rank_standings(rows, tie_round=tie_round)

    def _context(self, aid, st, round_no, hands_remaining):
        rows=self._standings(st); me=next(x for x in rows if x.agent_id==aid)
        r12=next((x.bb100 for x in rows if x.rank==12),None); r13=next((x.bb100 for x in rows if x.rank==13),None)
        return {'rank':me.rank,'bb100':me.bb100,'rank12_bb100':r12,'rank13_bb100':r13,'hands_remaining':hands_remaining,'round_no':round_no}

    def _play_group(self, group, st, round_no, hands_this_round):
        dealer=0
        for aid in group:
            st[aid]['stack']=100*self.big_blind
        policies={a.agent_id:a.strategy for a in self.agents}
        for hand_i in range(hands_this_round):
            # Each table session uses current stacks; busted seats auto-rebuy one full buy-in.
            for aid in group:
                if st[aid]['stack']<=0: st[aid]['stack']=100*self.big_blind
            before={aid:st[aid]['stack'] for aid in group}
            provider=lambda aid:self._context(aid,st,round_no,self.rounds*self.hpr-(round_no-1)*self.hpr-hand_i)
            res,dealer=self.engine.play_hand(group,{aid:st[aid]['stack'] for aid in group},dealer,policies,context_provider=provider)
            for aid in group:
                st[aid]['stack']=res.final_stacks[aid]
                delta=(st[aid]['stack']-before[aid])/self.big_blind
                st[aid]['net_bb'] += delta
                st[aid]['hands'] += 1
                if st[aid]['stack']<=0: st[aid]['stack']=100*self.big_blind

    def run_preliminary(self):
        st=self._state(); ids=list(st)
        for rnd in range(1,self.rounds+1):
            standings=self._standings(st); score={x.agent_id:(x.bb100 if x.bb100 is not None else float('-inf')) for x in standings}
            groups=random_groups(ids,self.seats,self.rng) if rnd<=3 else swiss_groups(ids,score,self.seats)
            for g in groups:
                g=list(g); self.rng.shuffle(g); self._play_group(g,st,rnd,self.hpr)
            if rnd==3:
                for aid,v in st.items(): v['_r3_net_bb']=v['net_bb']; v['_r3_hands']=v['hands']
            if rnd>=4:
                for aid,v in st.items():
                    v['from_r4_net_bb']=v['net_bb']-v.get('_r3_net_bb',0.0); v['from_r4_hands']=v['hands']-v.get('_r3_hands',0)
        return self._standings(st)

    def run_event(self):
        prelim=self.run_preliminary(); min_hands=int(self.rounds*self.hpr*self.min_completion)
        qualified=[s for s in prelim if s.hands>=min_hands][:12]
        result={'preliminary':prelim,'qualified':qualified,'semifinal':[],'final':[]}
        if len(qualified)<12: return result
        rank_map={s.agent_id:s.rank for s in prelim}; byid={a.agent_id:a for a in self.agents}
        groups=[[qualified[i-1].agent_id for i in (1,4,5,8,9,12)],[qualified[i-1].agent_id for i in (2,3,6,7,10,11)]]
        finals=[]
        for grp in groups:
            grp=list(grp); self.rng.shuffle(grp)
            local={aid:{'net_bb':0.0,'hands':0,'stack':100*self.big_blind} for aid in grp}
            # 20-hand invitation league; rankings inside it use this match only.
            dealer=0; policies={a.agent_id:a.strategy for a in self.agents}
            for h in range(20):
                for aid in grp:
                    if local[aid]['stack']<=0: local[aid]['stack']=100*self.big_blind
                before={aid:local[aid]['stack'] for aid in grp}
                res,dealer=self.engine.play_hand(grp,{aid:local[aid]['stack'] for aid in grp},dealer,policies,context_provider=lambda aid:{'rank':None,'bb100':None,'hands_remaining':20-h,'round_no':11})
                for aid in grp:
                    local[aid]['stack']=res.final_stacks[aid]; local[aid]['hands']+=1; local[aid]['net_bb']+=(local[aid]['stack']-before[aid])/self.big_blind
                    if local[aid]['stack']<=0: local[aid]['stack']=100*self.big_blind
            rows=rank_standings([Standing(aid,v['hands'],v['net_bb'],bb100(v['net_bb'],v['hands'])) for aid,v in local.items()])
            rows.sort(key=lambda x:(-(x.bb100 or float('-inf')), rank_map.get(x.agent_id,999), x.agent_id))
            for i,x in enumerate(rows,1): x.rank=i
            result['semifinal'].append(rows)
            finals.extend(rows[:3])
        # Final uses fresh 30-hand match, no carry-over score.
        ids=[s.agent_id for s in finals]; self.rng.shuffle(ids); local={aid:{'net_bb':0.0,'hands':0,'stack':100*self.big_blind} for aid in ids}; dealer=0; policies={a.agent_id:a.strategy for a in self.agents}
        for h in range(30):
            before={aid:local[aid]['stack'] for aid in ids}
            res,dealer=self.engine.play_hand(ids,{aid:local[aid]['stack'] for aid in ids},dealer,policies,context_provider=lambda aid:{'rank':None,'bb100':None,'hands_remaining':30-h,'round_no':12})
            for aid in ids:
                local[aid]['stack']=res.final_stacks[aid]; local[aid]['hands']+=1; local[aid]['net_bb']+=(local[aid]['stack']-before[aid])/self.big_blind
                if local[aid]['stack']<=0: local[aid]['stack']=100*self.big_blind
        # Final tie-break by preliminary rank.
        fr=[Standing(aid,v['hands'],v['net_bb'],bb100(v['net_bb'],v['hands'])) for aid,v in local.items()]
        fr=sorted(fr,key=lambda x:(-(x.bb100 or float('-inf')),-rank_map.get(x.agent_id,999),x.agent_id))
        for i,x in enumerate(fr,1): x.rank=i
        result['final']=fr
        return result

    def evaluate(self, runs=100):
        if not self.agents: return {'top12_rate':0.0,'final_rate':0.0,'champion_rate':0.0}
        focal=self.agents[0].agent_id; top=final_rate=champ=0
        for i in range(runs):
            sim_agents=[SimAgent(a.agent_id,StrategyAgent(a.strategy.params,seed=1000+i*17+j,name=a.agent_id)) for j,a in enumerate(self.agents)]
            sim=LeagueSimulator(sim_agents,self.engine.sb,self.engine.bb,self.rounds,self.hpr,self.seats,self.min_completion,seed=self.engine.rng.randrange(10**9))
            r=sim.run_event()
            if focal in [x.agent_id for x in r['qualified']]: top+=1
            if focal in [x.agent_id for x in r['final']]: final_rate+=1
            if r['final'] and r['final'][0].agent_id==focal: champ+=1
        return {'top12_rate':top/max(1,runs),'final_rate':final_rate/max(1,runs),'champion_rate':champ/max(1,runs)}
