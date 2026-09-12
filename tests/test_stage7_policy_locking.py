import json
from pathlib import Path
import pytest
from agentpoker.battle import certify_champion

def test_certification_policy_file_invariants():
    """Verify configs/certification_policy.json exists and strictly defines all 6 invariants."""
    policy_path = Path("configs/certification_policy.json")
    assert policy_path.exists(), "configs/certification_policy.json must exist"

    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    assert "invariants" in policy
    inv = policy["invariants"]

    assert inv["require_rank_1"] is True
    assert inv["min_champ_multiplier"] >= 2.0
    assert inv["min_top12_multiplier"] >= 1.5
    assert inv["min_bb100"] >= 0.0
    assert inv["min_h2h_win_rate"] >= 50.0
    assert inv["require_all_passed"] is True
    assert len(policy.get("criteria_definitions", [])) == 5


def test_certify_champion_reads_policy_defaults():
    """Verify certify_champion automatically reads thresholds from configs/certification_policy.json."""
    mock_report = {
        "field_size": 120,
        "runs": 50,
        "leaderboard": [
            {
                "cid": "cand_1",
                "name": "Candidate_1",
                "standing": 1,
                "score": 15.0,
                "champ_rate": 0.04,  # 2 wins / 50 runs = 4% (> 2x baseline)
                "champ_count": 2,
                "final_rate": 0.12,  # 6 / 50 = 12% (> 2x baseline)
                "final_count": 6,
                "avg_bb100": 20.0,   # > 0.0
                "top12_rate": 0.25,  # 25% (> 1.5x baseline)
                "top12_count": 12,
            }
        ],
        "h2h_matrix": {
            "cand_1": {"baseline": {"win_rate": 55.0}}
        }
    }

    res = certify_champion(mock_report, candidate_cid="cand_1", baseline_cids=["baseline"])
    assert res.certified is True
    assert res.recommendation == "PROMOTE_TO_CHAMPION"
    assert len(res.criteria) == 5
    assert all(c.passed for c in res.criteria)


def test_certify_champion_rejects_sub_policy_performance():
    """Verify certify_champion rejects candidate when below policy threshold."""
    mock_report = {
        "field_size": 120,
        "runs": 50,
        "leaderboard": [
            {
                "cid": "weak_cand",
                "name": "Weak_Candidate",
                "standing": 1,
                "score": 10.0,
                "champ_rate": 0.0,
                "champ_count": 0,
                "final_rate": 0.02,  # 2% < required 10% (runs < field requires >= 10%)
                "final_count": 1,
                "avg_bb100": -5.0,   # Negative BB/100
                "top12_rate": 0.08,  # 8% < required 15%
                "top12_count": 4,
            }
        ],
        "h2h_matrix": {
            "weak_cand": {"baseline": {"win_rate": 40.0}}
        }
    }

    res = certify_champion(mock_report, candidate_cid="weak_cand", baseline_cids=["baseline"])
    assert res.certified is False
    assert res.recommendation == "REJECT"
    failed = [c.name for c in res.criteria if not c.passed]
    assert "Title / Deep Run Superiority" in failed
    assert "Positive Expected Value (BB/100)" in failed
    assert "Top 12 Deep Run Qualification Rate" in failed
