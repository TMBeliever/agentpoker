"""Stage 10: Arena Battle & Champion Certification Gate Tests

Verifies:
1. Multi-model tournament matrix evaluation and H2H reciprocity invariants
2. Statistical metrics and standard errors (champ_se, top12_se, bb_se)
3. Formal Champion Certification Gate (mathematical criteria evaluation)
4. Failure modes under defective metrics (negative BB/100, rank != 1, etc.)
5. Model promotion and backup creation
"""

import json
from pathlib import Path
import pytest

from agentpoker.battle import (
    ArenaBattle,
    CompetitorCandidate,
    CertificationCriterion,
    ChampionCertificationResult,
    certify_champion,
    print_certification_card,
    promote_champion,
)
from agentpoker.training import ARCHETYPES


def test_h2h_matrix_mathematical_reciprocity():
    """G10.1: H2H matrix must satisfy strict pairwise reciprocity invariants."""
    comp_a = CompetitorCandidate(cid="bot_a", name="Bot A", category="archetype", params=ARCHETYPES["tight"])
    comp_b = CompetitorCandidate(cid="bot_b", name="Bot B", category="archetype", params=ARCHETYPES["lag"])
    comp_c = CompetitorCandidate(cid="bot_c", name="Bot C", category="archetype", params=ARCHETYPES["station"])

    arena = ArenaBattle(
        competitors=[comp_a, comp_b, comp_c],
        opponent_mode="archetypes",
        field_size=12,
        workers=1,
        seed=42,
    )
    report = arena.run(runs=3, verbose=False)
    h2h = report["h2h_matrix"]

    # Pairwise reciprocity
    for ca in ["bot_a", "bot_b", "bot_c"]:
        for cb in ["bot_a", "bot_b", "bot_c"]:
            if ca == cb:
                continue
            pair_ab = h2h[ca][cb]
            pair_ba = h2h[cb][ca]
            assert pair_ab["wins"] == pair_ba["losses"]
            assert pair_ab["losses"] == pair_ba["wins"]
            assert pair_ab["ties"] == pair_ba["ties"]
            assert pytest.approx(pair_ab["win_rate"] + pair_ba["win_rate"], rel=1e-3) == 100.0


def test_leaderboard_statistical_standard_errors():
    """G10.2: Leaderboard must compute non-negative standard errors for champ, final, top12, and bb100."""
    comp_a = CompetitorCandidate(cid="bot_a", name="Bot A", category="archetype", params=ARCHETYPES["tight"])
    comp_b = CompetitorCandidate(cid="bot_b", name="Bot B", category="archetype", params=ARCHETYPES["lag"])

    arena = ArenaBattle(
        competitors=[comp_a, comp_b],
        opponent_mode="archetypes",
        field_size=12,
        workers=1,
        seed=100,
    )
    report = arena.run(runs=4, verbose=False)
    leaderboard = report["leaderboard"]
    assert len(leaderboard) == 2

    for row in leaderboard:
        assert row["champ_se"] >= 0.0
        assert row["final_se"] >= 0.0
        assert row["top12_se"] >= 0.0
        assert row["bb_se"] >= 0.0
        assert 1 <= row["standing"] <= 2


def test_champion_certification_gate_passes_qualified_candidate():
    """G10.3: Candidate meeting all 5 formal criteria must be certified for production promotion."""
    synthetic_report = {
        "runs": 50,
        "field_size": 120,
        "opponent_mode": "pyramid",
        "leaderboard": [
            {
                "cid": "model:next_gen_champ",
                "name": "NextGen Champion v2",
                "standing": 1,
                "score": 48.5,
                "champ_count": 6,
                "champ_rate": 0.12,     # 12% vs baseline 0.83% (14.4x baseline)
                "final_count": 18,
                "final_rate": 0.36,
                "top12_count": 28,
                "top12_rate": 0.56,     # 56% vs baseline 10%
                "avg_bb100": 42.5,      # +42.5 BB/100 > 0.0
                "avg_rank": 14.2,
                "total_hands": 10500,
            },
            {
                "cid": "model:old_incumbent",
                "name": "Old Incumbent",
                "standing": 2,
                "score": 32.0,
                "champ_count": 2,
                "champ_rate": 0.04,
                "final_count": 8,
                "final_rate": 0.16,
                "top12_count": 15,
                "top12_rate": 0.30,
                "avg_bb100": 11.2,
                "avg_rank": 26.5,
                "total_hands": 10000,
            },
        ],
        "h2h_matrix": {
            "model:next_gen_champ": {
                "model:old_incumbent": {
                    "wins": 34,
                    "losses": 14,
                    "ties": 2,
                    "win_rate": 70.0,
                }
            },
            "model:old_incumbent": {
                "model:next_gen_champ": {
                    "wins": 14,
                    "losses": 34,
                    "ties": 2,
                    "win_rate": 30.0,
                }
            },
        },
    }

    result = certify_champion(
        report=synthetic_report,
        candidate_cid="model:next_gen_champ",
        baseline_cids=["model:old_incumbent"],
    )

    assert result.certified is True
    assert result.recommendation == "PROMOTE_TO_CHAMPION"
    assert len(result.criteria) == 5
    assert all(c.passed for c in result.criteria)

    # Output executive card should not error
    print_certification_card(result)


def test_champion_certification_gate_fails_underperforming_candidate():
    """G10.4: Candidate failing expected value or qualification rate must be rejected."""
    failing_report = {
        "runs": 40,
        "field_size": 120,
        "leaderboard": [
            {
                "cid": "model:luck_donkey",
                "name": "Luck Donkey",
                "standing": 1,
                "score": 25.0,
                "champ_count": 1,
                "champ_rate": 0.025,
                "final_count": 3,
                "final_rate": 0.075,
                "top12_count": 4,
                "top12_rate": 0.10,     # 10% (fails 1.5x baseline threshold 15%)
                "avg_bb100": -18.4,     # Negative BB/100 (bleeding chips)
                "avg_rank": 45.2,
                "total_hands": 8000,
            },
            {
                "cid": "archetype:tight",
                "name": "TAG Baseline",
                "standing": 2,
                "score": 22.0,
                "champ_count": 0,
                "champ_rate": 0.0,
                "final_count": 4,
                "final_rate": 0.10,
                "top12_count": 8,
                "top12_rate": 0.20,
                "avg_bb100": 8.5,
                "avg_rank": 32.1,
                "total_hands": 8000,
            }
        ],
        "h2h_matrix": {
            "model:luck_donkey": {
                "archetype:tight": {"wins": 18, "losses": 22, "ties": 0, "win_rate": 45.0}
            },
            "archetype:tight": {
                "model:luck_donkey": {"wins": 22, "losses": 18, "ties": 0, "win_rate": 55.0}
            }
        },
    }

    result = certify_champion(
        report=failing_report,
        candidate_cid="model:luck_donkey",
        baseline_cids=["archetype:tight"],
    )

    assert result.certified is False
    assert result.recommendation == "REJECT"
    failed_criteria = [c.name for c in result.criteria if not c.passed]
    assert "Positive Expected Value (BB/100)" in failed_criteria
    assert "Top 12 Deep Run Qualification Rate" in failed_criteria
    assert "Benchmark Dominance & Tournament EV" in failed_criteria


def test_champion_promotion_and_backup(tmp_path: Path):
    """G10.5: Safe model promotion creates timestamped backup and writes certification metadata."""
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    target_champion = model_dir / "champion.json"

    # Incumbent champion
    target_champion.write_text(json.dumps({"version": 1, "name": "Old Champ"}), encoding="utf-8")

    # New candidate
    candidate_file = tmp_path / "gen_next.json"
    candidate_file.write_text(json.dumps({"version": 2, "name": "New NextGen Champ"}), encoding="utf-8")

    cert_res = ChampionCertificationResult(
        certified=True,
        candidate_id="model:gen_next",
        candidate_name="New NextGen Champ",
        criteria=[CertificationCriterion(name="Test Criterion", required="Req", actual="Act", passed=True)],
        summary="Candidate passed test certification.",
        recommendation="PROMOTE_TO_CHAMPION",
    )

    promoted_path = promote_champion(
        candidate_source=candidate_file,
        target_path=target_champion,
        backup=True,
        certification_result=cert_res,
    )

    assert promoted_path == target_champion
    promoted_data = json.loads(target_champion.read_text(encoding="utf-8"))
    assert promoted_data["version"] == 2
    assert "certification" in promoted_data
    assert promoted_data["certification"]["certified"] is True

    # Check that backup file was created
    backups = list(model_dir.glob("champion_backup_*.json"))
    assert len(backups) == 1
    backup_data = json.loads(backups[0].read_text(encoding="utf-8"))
    assert backup_data["version"] == 1
