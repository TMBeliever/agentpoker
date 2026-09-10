from __future__ import annotations
from random import Random

def random_groups(ids,seats,rng:Random):
    ids=list(ids); rng.shuffle(ids); return [ids[i:i+seats] for i in range(0,len(ids),seats)]

def swiss_groups(ids, scores, seats):
    ordered=sorted(ids,key=lambda x:(-float(scores.get(x,float('-inf'))),x))
    return [ordered[i:i+seats] for i in range(0,len(ordered),seats)]
