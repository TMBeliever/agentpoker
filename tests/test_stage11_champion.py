"""Stage 11: Generation 28 Audit & Next-Gen Champion Evolution Tests

Verifies:
1. Legacy Gen 28 parameter pathology audit and clamping failure
2. Certified Production Champion V2 compliance with all poker invariants
3. Embedded certification metadata and audit trail in models/champion.json
4. Elimination of preflop open-limping in non-blind positions
5. Statistical and tournament EV superiority over Legacy Gen 28
"""

import json
from pathlib import Path
import pytest

from agentpoker.strategy import StrategyParams, StrategyAgent
from agentpoker.training import StrategyTrainer


def test_gen28_parameter_pathology_audit():
    """G11.1: Legacy Gen 28 must exhibit documented nit pathology and fail V2 invariants."""
    gen28_path = Path("models/archive/gen_028.json")
    assert gen28_path.exists(), "Legacy Gen 28 archive missing"
    d = json.loads(gen28_path.read_text(encoding="utf-8"))
    params = d.get("params", d)

    # Documented pathologies
    assert params["vpip"] < 0.05, "Gen 28 must exhibit extreme Nit degeneration (VPIP < 5%)"
    assert params["cbet_size"] < 0.05, "Gen 28 must exhibit micro-bet pathology (cbet_size < 5% pot)"
    assert params["safety"] > 0.85, "Gen 28 must exhibit hyper-defensive aversion (safety > 0.85)"

    # Must be modified when passed through V2 clamping
    trainer = StrategyTrainer()
    clamped_copy = dict(params)
    trainer._clamp_and_validate(clamped_copy)
    assert clamped_copy["vpip"] >= 0.15, "V2 clamp must correct VPIP to at least 15%"
    assert clamped_copy["cbet_size"] >= 0.25, "V2 clamp must correct cbet_size to at least 25% pot"


def test_production_champion_complies_with_all_invariants():
    """G11.2: Promoted models/champion.json must satisfy all V2 tournament poker invariants."""
    champ_path = Path("models/champion.json")
    assert champ_path.exists(), "Production champion.json missing"
    d = json.loads(champ_path.read_text(encoding="utf-8"))
    params = d.get("params", d)

    # V2 Poker Invariants
    assert 0.15 <= params["vpip"] <= 0.40
    assert 0.25 <= params["cbet_size"] <= 1.25
    assert 0.50 <= params["value_bet_size"] <= 1.00
    assert 0.25 <= params["raise_size"] <= 1.20
    assert params["threebet_frequency"] >= 0.04
    assert params["late_aggression"] >= 0.20
    assert "dry_board_bet_size" in params
    assert "wet_board_bet_size" in params
    assert params["dry_board_bet_size"] < params["wet_board_bet_size"]


def test_production_champion_certification_audit_trail():
    """G11.3: Promoted champion.json must retain verifiable certification metadata."""
    champ_path = Path("models/champion.json")
    d = json.loads(champ_path.read_text(encoding="utf-8"))
    assert "certification" in d, "Champion file must include certification metadata"

    cert = d["certification"]
    assert cert["certified"] is True
    assert cert["recommendation"] == "PROMOTE_TO_CHAMPION"
    assert len(cert["criteria"]) == 5
    assert all(c["passed"] for c in cert["criteria"])


def test_preflop_raise_or_fold_initiative():
    """G11.4: Preflop opening in non-blind positions must raise or fold, never open-limp."""
    agent = StrategyAgent.load("models/champion.json")

    # Construct an unopened preflop spot on the Button
    obs_btn_open = {
        "legal": {"fold": True, "call": 200.0, "raise": {"min": 400.0, "max": 20000.0}, "allIn": 20000.0},
        "hero": ["Ah", "9s"],
        "board": [],
        "pot": 300.0,  # SB=100, BB=200
        "big_blind": 200.0,
        "stack": 20000.0,
        "position": 0,
        "dealer_seat": 0,  # Button
        "players": [
            {"agentId": "hero", "stack": 20000.0, "currentBet": 0.0, "folded": False},
            {"agentId": "sb", "stack": 19900.0, "currentBet": 100.0, "folded": False},
            {"agentId": "bb", "stack": 19800.0, "currentBet": 200.0, "folded": False},
        ],
        "context": {"stage": "preliminary", "rank": 5, "hands_remaining": 150, "total_stage_hands": 200},
    }

    # Over 50 decisions with varying seeds, the agent should never choose to open-limp (call)
    actions = set()
    for s in range(50):
        agent.rng.seed(s)
        act = agent.choose_local(obs_btn_open)
        actions.add(act["type"])

    assert "call" not in actions, f"Hero on BTN should raise or fold, not limp. Observed: {actions}"
    assert "raise" in actions or "allIn" in actions or "fold" in actions


def test_stage11_benchmark_tournament_superiority():
    """G11.5: Production Champion must demonstrate superior tournament EV over Legacy Gen 28."""
    report_path = Path("docs/stage11_certification_report.json")
    assert report_path.exists(), "Stage 11 benchmark report missing"
    data = json.loads(report_path.read_text(encoding="utf-8"))

    board = data["report"]["leaderboard"]
    prod_row = next(r for r in board if r["cid"] == "model:prod_v2")
    gen28_row = next(r for r in board if r["cid"] == "model:gen_028")

    # Verified superiority
    assert prod_row["standing"] == 1, "Production Champion must rank #1"
    assert prod_row["avg_bb100"] > gen28_row["avg_bb100"], "Production Champion must generate higher BB/100"
    assert prod_row["final_rate"] > gen28_row["final_rate"], "Production Champion must achieve higher final table rate"
    assert prod_row["score"] > gen28_row["score"], "Production Champion must achieve higher composite score"
