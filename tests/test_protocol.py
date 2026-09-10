from agentpoker.collector import redact

def test_redact_secret():
    x=redact({'Authorization':'Bearer sk_abc123','nested':['sk_zzz']})
    assert 'sk_' not in str(x)
