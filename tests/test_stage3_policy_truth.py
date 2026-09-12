import json
import tempfile
from pathlib import Path
import pytest
from agentpoker.battle import certify_champion


def _get_base_mock_report():
    return {
        "field_size": 120,
        "runs": 20,
        "leaderboard": [
            {
                "cid": "candidate_bot",
                "name": "Candidate Bot",
                "standing": 1,
                "score": 1200.0,
                "champ_rate": 0.05,
                "champ_count": 1,
                "final_rate": 0.20,
                "final_count": 4,
                "top12_rate": 0.35,
                "top12_count": 7,
                "avg_bb100": 8.5,
            },
            {
                "cid": "baseline_bot",
                "name": "Baseline Bot",
                "standing": 2,
                "score": 900.0,
                "champ_rate": 0.02,
                "champ_count": 0,
                "final_rate": 0.10,
                "final_count": 2,
                "top12_rate": 0.20,
                "top12_count": 4,
                "avg_bb100": 3.0,
            },
        ],
        "h2h_matrix": {
            "candidate_bot": {
                "baseline_bot": {
                    "wins": 52,
                    "losses": 48,
                    "ties": 0,
                    "win_rate": 52.0,
                }
            }
        },
    }


def test_policy_defaults_have_ev_bypass_false_and_120_field():
    policy_path = Path("configs/certification_policy.json")
    assert policy_path.exists(), "configs/certification_policy.json must exist"
    data = json.loads(policy_path.read_text(encoding="utf-8"))
    invariants = data.get("invariants", {})
    assert invariants.get("required_field_size") == 120
    assert invariants.get("allow_ev_bypass") is False
    assert invariants.get("min_h2h_win_rate") == 50.0
    assert invariants.get("min_champ_multiplier") == 2.0
    assert invariants.get("min_top12_multiplier") == 1.5


def test_policy_dynamic_threshold_h2h():
    report = _get_base_mock_report()

    # 1. Under default policy (min_h2h_win_rate = 50.0%), 52.0% PASSES
    res_default = certify_champion(
        report,
        candidate_cid="candidate_bot",
        baseline_cids=["baseline_bot"],
        policy_path="configs/certification_policy.json",
    )
    assert res_default.certified is True
    c5 = next(c for c in res_default.criteria if "Benchmark Dominance" in c.name)
    assert c5.passed is True

    # 2. Under custom policy where min_h2h_win_rate is raised to 55.0%
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tmp:
        policy_data = {
            "policy_name": "Strict H2H Policy",
            "invariants": {
                "require_rank_1": True,
                "required_field_size": 120,
                "min_champ_multiplier": 2.0,
                "min_top12_multiplier": 1.5,
                "min_bb100": 0.0,
                "min_h2h_win_rate": 55.0,
                "allow_ev_bypass": False,
                "require_all_passed": True,
            },
        }
        json.dump(policy_data, tmp)
        tmp_path = tmp.name

    try:
        res_strict = certify_champion(
            report,
            candidate_cid="candidate_bot",
            baseline_cids=["baseline_bot"],
            policy_path=tmp_path,
        )
        assert res_strict.certified is False
        c5_strict = next(c for c in res_strict.criteria if "Benchmark Dominance" in c.name)
        assert c5_strict.passed is False
        assert "below required 55.0%" in c5_strict.actual
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def test_policy_ev_bypass_toggle():
    report = _get_base_mock_report()
    # Candidate H2H against baseline is only 48.0% (below 50%)
    report["h2h_matrix"]["candidate_bot"]["baseline_bot"]["win_rate"] = 48.0

    # 1. Under allow_ev_bypass = False (policy default)
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tmp:
        policy_no_bypass = {
            "invariants": {
                "require_rank_1": True,
                "required_field_size": 120,
                "min_champ_multiplier": 2.0,
                "min_top12_multiplier": 1.5,
                "min_bb100": 0.0,
                "min_h2h_win_rate": 50.0,
                "allow_ev_bypass": False,
                "require_all_passed": True,
            },
        }
        json.dump(policy_no_bypass, tmp)
        path_no_bypass = tmp.name

    try:
        res_no_bypass = certify_champion(
            report,
            candidate_cid="candidate_bot",
            baseline_cids=["baseline_bot"],
            policy_path=path_no_bypass,
        )
        assert res_no_bypass.certified is False
        c5 = next(c for c in res_no_bypass.criteria if "Benchmark Dominance" in c.name)
        assert c5.passed is False
    finally:
        Path(path_no_bypass).unlink(missing_ok=True)

    # 2. Under allow_ev_bypass = True
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tmp:
        policy_with_bypass = {
            "invariants": {
                "require_rank_1": True,
                "required_field_size": 120,
                "min_champ_multiplier": 2.0,
                "min_top12_multiplier": 1.5,
                "min_bb100": 0.0,
                "min_h2h_win_rate": 50.0,
                "allow_ev_bypass": True,
                "require_all_passed": True,
            },
        }
        json.dump(policy_with_bypass, tmp)
        path_with_bypass = tmp.name

    try:
        res_with_bypass = certify_champion(
            report,
            candidate_cid="candidate_bot",
            baseline_cids=["baseline_bot"],
            policy_path=path_with_bypass,
        )
        assert res_with_bypass.certified is True
        c5 = next(c for c in res_with_bypass.criteria if "Benchmark Dominance" in c.name)
        assert c5.passed is True
        assert "EV Superior" in c5.actual
    finally:
        Path(path_with_bypass).unlink(missing_ok=True)
