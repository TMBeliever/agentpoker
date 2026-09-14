import json
import tempfile
from pathlib import Path
import pytest
from agentpoker.battle import certify_champion
from agentpoker.config import TournamentConfig
from agentpoker.strategy import StrategyAgent, StrategyParams
from agentpoker.training import ARCHETYPES, StrategyTrainer


def test_universal_track_convergence_and_metrics_integrity():
    """Verify Universal Track evolution produces structurally sound metrics and artifacts."""
    with tempfile.TemporaryDirectory() as tmpdir:
        save_path = Path(tmpdir) / "candidate.json"
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
        )

        champ, report = trainer.fit(
            generations=2,
            population=3,
            runs_per_candidate=1,
            final_race=1,
            save=str(save_path),
            archive=str(archive_dir),
        )

        assert isinstance(champ, StrategyParams)
        assert save_path.exists()

        data = json.loads(save_path.read_text(encoding="utf-8"))
        assert data["version"] == 5
        assert "params" in data
        assert "training_metrics" in data
        assert "validation_metrics" in data
        assert "test_metrics" in data
        assert "history" in data
        assert len(data["history"]) == 2

        # Check metrics details
        for key in ("fitness", "prelim_bb100", "overall_bb100", "avg_finish_rank"):
            assert key in data["validation_metrics"]
            assert key in data["test_metrics"]

        # Check diversity in history
        for entry in data["history"]:
            assert "population_diversity" in entry
            assert 0.0 <= entry["population_diversity"] <= 1.0


def test_targeted_track_train_val_test_isolation():
    """Verify Targeted Track with opponent profiles strictly isolates train, val, and test partitions."""
    profiles_path = "models/opponent_profiles.json"
    if not Path(profiles_path).exists():
        pytest.skip(f"{profiles_path} does not exist.")

    cfg = TournamentConfig(
        field_size=12,
        preliminary_rounds=2,
        hands_per_round=2,
        semifinal_hands=2,
        final_hands=2,
        progressive_blinds=True,
    )
    trainer = StrategyTrainer(
        seed=101,
        pool_size=12,
        workers=1,
        profiles=profiles_path,
        profile_min_hands=15,
        profile_share=0.5,
        holdout_frac=0.30,
        tournament_config=cfg,
    )

    assert trainer.n_profiles_loaded > 0
    # Strict 3-way partition check (disjoint sets)
    val_set = set(id(p) for p in trainer.validation_env.profile_params)
    test_set = set(id(p) for p in trainer.test_env.profile_params)
    train_set = set(id(p) for p in trainer.train_env.profile_params)
    assert len(val_set.intersection(test_set)) == 0
    assert len(val_set.intersection(train_set)) == 0
    assert len(test_set.intersection(train_set)) == 0

    with tempfile.TemporaryDirectory() as tmpdir:
        champ, report = trainer.fit(
            generations=1,
            population=2,
            runs_per_candidate=1,
            final_race=1,
            save=f"{tmpdir}/candidate.json",
            archive=f"{tmpdir}/archive",
        )
        assert "validation" in report
        assert "test" in report
        assert report["test"]["fitness"] >= 0.0


def test_champion_certification_gate_decision_logic():
    """Verify certify_champion evaluates leaderboard rankings and rejects sub-par candidates."""
    # Synthetic battle report where candidate passed all criteria
    mock_passing_report = {
        "field_size": 120,
        "runs": 20,
        "leaderboard": [
            {
                "cid": "candidate_1",
                "name": "Candidate One",
                "standing": 1,
                "score": 85.0,
                "champ_count": 4,
                "champ_rate": 0.20,
                "final_count": 8,
                "final_rate": 0.40,
                "top12_count": 10,
                "top12_rate": 0.50,
                "avg_rank": 4.5,
                "avg_bb100": 35.0,
            },
            {
                "cid": "baseline_1",
                "name": "Baseline Champion",
                "standing": 2,
                "score": 60.0,
                "champ_count": 1,
                "champ_rate": 0.05,
                "final_count": 4,
                "final_rate": 0.20,
                "top12_count": 6,
                "top12_rate": 0.30,
                "avg_rank": 8.0,
                "avg_bb100": 5.0,
            },
        ],
        "h2h_matrix": {
            "candidate_1": {"baseline_1": {"wins": 14, "losses": 6, "draws": 0, "win_rate": 70.0}},
            "baseline_1": {"candidate_1": {"wins": 6, "losses": 14, "draws": 0, "win_rate": 30.0}},
        },
    }

    result = certify_champion(mock_passing_report, candidate_cid="candidate_1", official=True)
    assert result.certified is True
    assert result.recommendation == "PROMOTE_TO_CHAMPION"

    # Synthetic battle report where candidate is Rank 2 (failed standing criteria)
    mock_failing_report = {
        "field_size": 120,
        "runs": 20,
        "leaderboard": [
            {
                "cid": "baseline_1",
                "name": "Baseline Champion",
                "standing": 1,
                "score": 90.0,
                "champ_count": 5,
                "champ_rate": 0.25,
                "final_count": 10,
                "final_rate": 0.50,
                "top12_count": 12,
                "top12_rate": 0.60,
                "avg_rank": 3.5,
                "avg_bb100": 45.0,
            },
            {
                "cid": "candidate_2",
                "name": "Candidate Two",
                "standing": 2,
                "score": 50.0,
                "champ_count": 0,
                "champ_rate": 0.0,
                "final_count": 2,
                "final_rate": 0.10,
                "top12_count": 4,
                "top12_rate": 0.20,
                "avg_rank": 15.0,
                "avg_bb100": -15.0,
            },
        ],
        "h2h_matrix": {
            "candidate_2": {"baseline_1": {"wins": 3, "losses": 17, "draws": 0, "win_rate": 15.0}},
            "baseline_1": {"candidate_2": {"wins": 17, "losses": 3, "draws": 0, "win_rate": 85.0}},
        },
    }

    fail_result = certify_champion(mock_failing_report, candidate_cid="candidate_2", official=True)
    assert fail_result.certified is False
    assert fail_result.recommendation == "REJECT"


def test_model_export_json_schema_compliance():
    """Verify that exported candidate models are cleanly loadable by StrategyAgent."""
    with tempfile.TemporaryDirectory() as tmpdir:
        model_file = Path(tmpdir) / "test_model.json"
        cfg = TournamentConfig(
            field_size=12,
            preliminary_rounds=1,
            hands_per_round=1,
            semifinal_hands=1,
            final_hands=1,
        )
        trainer = StrategyTrainer(seed=777, pool_size=12, workers=1, tournament_config=cfg)
        champ, report = trainer.fit(
            generations=1,
            population=2,
            runs_per_candidate=1,
            final_race=1,
            save=str(model_file),
        )

        agent = StrategyAgent.load(str(model_file))
        assert isinstance(agent, StrategyAgent)
        assert agent.params.vpip == champ.vpip
        assert agent.params.value_threshold == champ.value_threshold
