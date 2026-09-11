import json
import pytest
from pathlib import Path
from dataclasses import asdict
from agentpoker.strategy import StrategyParams
from agentpoker.training import StrategyTrainer

def _mock_evaluate_worker(payload):
    return {
        "fitness": 0.72,
        "top12_rate": 1.0,
        "final_rate": 0.8,
        "champion_rate": 0.4,
        "avg_rank": 2.5,
        "avg_bb100": 15.0
    }

def test_trainer_resumption_from_checkpoint(tmp_path, monkeypatch):
    monkeypatch.setattr("agentpoker.training._evaluate_worker", _mock_evaluate_worker)
    archive_dir = tmp_path / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)

    # Pre-populate gen_001.json and gen_002.json
    dummy_params = asdict(StrategyParams())
    dummy_metrics = {"fitness": 0.65, "top12_rate": 0.9, "final_rate": 0.5, "champion_rate": 0.2, "avg_rank": 8.0}
    (archive_dir / "gen_001.json").write_text(
        json.dumps({"generation": 1, "champion": dummy_params, "metrics": dummy_metrics}), encoding="utf-8"
    )
    (archive_dir / "gen_002.json").write_text(
        json.dumps({"generation": 2, "champion": dummy_params, "metrics": dummy_metrics}), encoding="utf-8"
    )

    save_path = tmp_path / "champion.json"
    trainer = StrategyTrainer(seed=42, pool_size=12, equity_samples=0, workers=1)

    # Train for 1 generation with resume=True
    champ, report = trainer.fit(
        generations=1,
        population=4,
        runs_per_candidate=2,
        final_race=1,
        save=str(save_path),
        archive=str(archive_dir),
        resume=True
    )

    # Check that gen_003 was generated
    assert (archive_dir / "gen_003.json").exists()
    gen3_data = json.loads((archive_dir / "gen_003.json").read_text(encoding="utf-8"))
    assert gen3_data["generation"] == 3

    # Check that report history preserves gen 1, 2 and adds gen 3
    history = report["training"]
    assert len(history) == 3
    assert [h["generation"] for h in history] == [1, 2, 3]
    assert save_path.exists()

def test_trainer_no_resume(tmp_path, monkeypatch):
    monkeypatch.setattr("agentpoker.training._evaluate_worker", _mock_evaluate_worker)
    archive_dir = tmp_path / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)

    dummy_params = asdict(StrategyParams())
    dummy_metrics = {"fitness": 0.50, "top12_rate": 0.5, "final_rate": 0.2, "champion_rate": 0.1, "avg_rank": 15.0}
    (archive_dir / "gen_001.json").write_text(
        json.dumps({"generation": 1, "champion": dummy_params, "metrics": dummy_metrics}), encoding="utf-8"
    )

    save_path = tmp_path / "champion.json"
    trainer = StrategyTrainer(seed=42, pool_size=12, equity_samples=0, workers=1)

    # Train for 1 generation with resume=False
    champ, report = trainer.fit(
        generations=1,
        population=4,
        runs_per_candidate=2,
        final_race=1,
        save=str(save_path),
        archive=str(archive_dir),
        resume=False
    )

    history = report["training"]
    assert len(history) == 1
    assert history[0]["generation"] == 1

def test_trainer_profiles_injection(tmp_path):
    # Mock profiles dict
    mock_profiles = {
        "fish_player": {
            "hands": 100,
            "calls_count": 80,
            "folds_count": 10,
            "raises_count": 10,
            "vpip_count": 90,
            "pfr_count": 10,
        },
        "nit_player": {
            "hands": 100,
            "calls_count": 10,
            "folds_count": 80,
            "raises_count": 10,
            "vpip_count": 15,
            "pfr_count": 10,
        }
    }
    profiles_path = tmp_path / "test_profiles.json"
    profiles_path.write_text(json.dumps(mock_profiles), encoding="utf-8")

    trainer = StrategyTrainer(seed=123, pool_size=12, profiles=profiles_path)
    assert len(trainer._cached_profile_params) == 2

    # Verify opponents generation draws from profile candidates
    opps = trainer._opponents(StrategyParams(), [], [], seed=999)
    assert len(opps) == 11  # pool_size - 1

def test_trainer_base_model_seeding(tmp_path, monkeypatch):
    monkeypatch.setattr("agentpoker.training._evaluate_worker", _mock_evaluate_worker)
    archive_dir = tmp_path / "archive_empty"
    save_path = tmp_path / "champion_seeded.json"

    base_file = tmp_path / "base_model.json"
    custom_params = asdict(StrategyParams(vpip=0.45, open_size=3.10))
    base_file.write_text(json.dumps({"params": custom_params}), encoding="utf-8")

    trainer = StrategyTrainer(seed=42, pool_size=12, equity_samples=0, workers=1)
    champ, report = trainer.fit(
        generations=1,
        population=4,
        runs_per_candidate=2,
        final_race=1,
        save=str(save_path),
        archive=str(archive_dir),
        resume=True,
        base_model=str(base_file)
    )

    assert save_path.exists()
    assert (archive_dir / "gen_001.json").exists()
    history = report["training"]
    assert len(history) == 1
    assert history[0]["generation"] == 1
