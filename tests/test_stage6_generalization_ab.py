"""Unit and integration tests for Round 2 Stage 6: Final Generalization Acceptance & A/B Statistical Testing.

Verifies:
1. Welch's t-test and degrees of freedom mathematical accuracy in compute_ab_statistical_test.
2. Non-parametric Bootstrap 95% Confidence Interval accuracy and edge case handling.
3. Execution of full 4-Way Generalization A/B Suite (Seen, Unseen, Shift, Stability).
4. Strict safety constraint: models/champion.json is NEVER touched or overwritten during training/evaluation.
5. Candidate model version 5 artifact schema and generalization metrics persistence.
"""
import json
import tempfile
from pathlib import Path
import pytest

from agentpoker.strategy import StrategyParams
from agentpoker.config import TournamentConfig
from agentpoker.training import (
    ARCHETYPES,
    UNSEEN_OOD_ARCHETYPES,
    StrategyTrainer,
    ArenaEvaluator,
    compute_ab_statistical_test,
    conduct_generalization_ab_suite,
    _load_params_safe,
)


def test_compute_ab_statistical_test_superior_candidate():
    """Verify statistical test correctly identifies a significantly superior candidate."""
    scores_baseline = [0.45, 0.48, 0.50, 0.46, 0.49, 0.47, 0.51, 0.46, 0.48, 0.50]
    scores_candidate = [0.65, 0.68, 0.70, 0.66, 0.69, 0.67, 0.71, 0.66, 0.68, 0.72]

    res = compute_ab_statistical_test(scores_baseline, scores_candidate, alpha=0.05, n_bootstrap=1000)

    assert res["delta"] > 0.15
    assert res["t_stat"] > 10.0
    assert res["p_value"] < 0.001
    assert res["statistically_significant"] is True
    assert res["candidate_dominates"] is True
    assert res["ci95"][0] > 0.15 and res["ci95"][1] > 0.15
    assert res["cohens_d"] > 3.0
    assert res["win_rate_candidate"] == 1.0


def test_compute_ab_statistical_test_identical_distributions():
    """Verify statistical test does not report false positives on identical distributions."""
    scores_a = [0.52, 0.49, 0.51, 0.50, 0.48, 0.53, 0.50, 0.49, 0.51, 0.50]
    scores_b = [0.51, 0.50, 0.50, 0.49, 0.52, 0.50, 0.51, 0.50, 0.49, 0.52]

    res = compute_ab_statistical_test(scores_a, scores_b, alpha=0.05, n_bootstrap=1000)

    assert abs(res["delta"]) < 0.02
    assert res["p_value"] > 0.05
    assert res["statistically_significant"] is False
    assert res["candidate_dominates"] is False
    # 95% CI must cross zero
    assert res["ci95"][0] <= 0.0 <= res["ci95"][1]


def test_conduct_generalization_ab_suite_4_tracks():
    """Verify conduct_generalization_ab_suite executes all 4 tracks and populates complete metrics."""
    cfg = TournamentConfig(
        field_size=12,
        preliminary_rounds=2,
        hands_per_round=2,
        semifinal_hands=2,
        final_hands=2,
        progressive_blinds=True,
    )
    baseline = ARCHETYPES["balanced"]
    candidate = ARCHETYPES["tight"]

    res = conduct_generalization_ab_suite(
        candidate=candidate,
        baseline=baseline,
        runs_per_track=5,
        pool_size=12,
        seed_base=123,
        tournament_config=cfg,
        workers=1,
        verbose=False,
    )

    # 1. Track 1: Seen
    assert "seen_track" in res
    assert "baseline_fitness" in res["seen_track"]
    assert "candidate_fitness" in res["seen_track"]
    assert "ab_test" in res["seen_track"]

    # 2. Track 2: Unseen
    assert "unseen_track" in res
    assert "baseline_fitness" in res["unseen_track"]
    assert "candidate_fitness" in res["unseen_track"]
    assert "ab_test" in res["unseen_track"]

    # 3. Track 3: Shift
    assert "shift_track" in res
    assert "ab_test" in res["shift_track"]
    assert "mode_breakdowns" in res["shift_track"]["ab_test"]

    # 4. Track 4: Stability
    assert "stability_track" in res
    assert "baseline_robust_fitness" in res["stability_track"]
    assert "candidate_robust_fitness" in res["stability_track"]
    assert "baseline_between_ecology_variance" in res["stability_track"]
    assert "candidate_between_ecology_variance" in res["stability_track"]

    # Verdict summary
    assert "summary" in res
    assert "generalization_certified" in res["summary"]
    assert res["recommendation"] in ("PROMOTE_CANDIDATE", "RETAIN_BASELINE")


def test_end_to_end_training_and_candidate_save_without_champion_mutation():
    """Verify StrategyTrainer.fit produces candidate.json with version 5 and preserves champion.json."""
    champ_file = Path("models/champion.json")
    original_champ_bytes = champ_file.read_bytes() if champ_file.exists() else None

    with tempfile.TemporaryDirectory() as tmpdir:
        cand_path = Path(tmpdir) / "candidate.json"
        archive_dir = Path(tmpdir) / "archive"

        cfg = TournamentConfig(
            field_size=12,
            preliminary_rounds=2,
            hands_per_round=2,
            semifinal_hands=2,
            final_hands=2,
            progressive_blinds=True,
        )
        trainer = StrategyTrainer(
            seed=42,
            pool_size=12,
            workers=1,
            tournament_config=cfg,
            self_play=True,
        )

        champ, report = trainer.fit(
            generations=2,
            population=3,
            runs_per_candidate=1,
            final_race=1,
            save=str(cand_path),
            archive=str(archive_dir),
        )

        # 1. Verify candidate.json was written
        assert cand_path.exists()
        cand_data = json.loads(cand_path.read_text(encoding="utf-8"))

        assert cand_data["version"] == 5
        assert "params" in cand_data
        assert "training_metrics" in cand_data
        assert "validation_metrics" in cand_data
        assert "test_metrics" in cand_data

        # Verify Round 2 additions in candidate data
        assert "val_distribution_shift" in cand_data
        assert "test_distribution_shift" in cand_data
        assert "robust_fitness" in cand_data["training_metrics"]
        assert "between_ecology_variance" in cand_data["training_metrics"]
        assert "within_ecology_variance" in cand_data["training_metrics"]
        assert "ood_stress_results" in cand_data["test_metrics"]

    # 2. Strict champion safety check
    if original_champ_bytes is not None:
        assert champ_file.exists()
        assert champ_file.read_bytes() == original_champ_bytes, "models/champion.json MUST NOT BE MODIFIED!"
