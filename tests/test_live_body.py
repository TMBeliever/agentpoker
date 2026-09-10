from agentpoker.live import LiveRunner
from agentpoker.protocol import AgentPokerClient, Config
from agentpoker.strategy import StrategyAgent

def test_action_body_uses_current_request_and_legal_amount():
    c=AgentPokerClient(Config(key='sk_test'))
    r=LiveRunner(c,StrategyAgent(seed=1),competition_id='cid')
    obs={'competitionId':'cid','agentId':'a','table':{'id':'tid','players':[{'agentId':'a','stack':1000,'handState':{'holeCards':['As','Kd'],'currentBet':0}}],'hand':{'pot':300,'communityCards':[]}},'actionRequest':{'id':'rid','allowedActions':[{'type':'fold'},{'type':'call','amount':100},{'type':'raise','minAmount':300,'maxAmount':1000}]}}
    body=r._make_action_body(obs)
    assert body['competitionId']=='cid' and body['tableId']=='tid' and body['actionRequestId']=='rid'
    assert body['decision']['type'] in {'fold','call','raise'}
