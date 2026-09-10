from agentpoker.engine import NLHEngine
from agentpoker.strategy import StrategyAgent

def test_engine_conserves_chips_simple():
    e=NLHEngine(seed=1)
    agents=['a','b','c','d','e','f']; stacks={x:20000 for x in agents}; policies={x:StrategyAgent(seed=i) for i,x in enumerate(agents)}
    r,_=e.play_hand(agents,stacks,0,policies)
    assert len(r.board)==5
    assert sum(r.final_stacks.values())==sum(stacks.values())

def test_strategy_returns_legal():
    s=StrategyAgent(seed=1)
    obs={'hero':['As','Kd'],'board':[],'pot':300,'stack':19800,'position':0,
         'players':[{'agentId':'a','stack':19800,'folded':False,'allIn':False}],
         'legal':{'fold':None,'call':200,'raise':(600,19800)}}
    d=s.choose_local(obs)
    assert d['type'] in obs['legal']
    if d['type']=='raise': assert 600<=d['amount']<=19800
