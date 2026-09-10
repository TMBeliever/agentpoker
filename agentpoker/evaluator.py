from __future__ import annotations
from itertools import combinations
from .cards import Card, rank5

def eval7(cards):
    best=None
    for five in combinations(cards,5):
        r=rank5(five)
        best=r if best is None or r>best else best
    return best
