from agentpoker.tournament import LeagueSimulator,SimAgent
from agentpoker.strategy import StrategyAgent

def test_full_structure_with_24_agents():
    agents=[SimAgent(str(i),StrategyAgent(seed=i)) for i in range(24)]
    sim=LeagueSimulator(agents,rounds=1,hands_per_round=2,seed=3)
    # Not a full event here because the 1-round smoke test intentionally lacks 12 qualifying hands.
    r=sim.run_event()
    assert 'preliminary' in r and len(r['preliminary'])==24
