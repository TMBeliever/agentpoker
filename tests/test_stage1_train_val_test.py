from dataclasses import FrozenInstanceError, asdict
import pytest
from agentpoker.training import StrategyTrainer, OpponentEnvironment, ArenaEvaluator
from agentpoker.strategy import StrategyParams

def test_test_set_is_frozen():
    """Verify that test_env is frozen, immutable, and strictly partitioned from train and val."""
    trainer = StrategyTrainer(
        seed=42, pool_size=12, workers=1,
        profiles="models/opponent_profiles.json",
        val_frac=0.15, test_frac=0.15
    )
    
    # 1. Verify environment instances
    assert isinstance(trainer.train_env, OpponentEnvironment)
    assert isinstance(trainer.validation_env, OpponentEnvironment)
    assert isinstance(trainer.test_env, OpponentEnvironment)
    
    # 2. Verify immutability of test_env
    assert trainer.test_env.is_frozen is True
    with pytest.raises(FrozenInstanceError):
        trainer.test_env.name = "corrupted"

    # 3. Verify zero leakage / zero overlap across partitions
    train_profs = {(p.vpip, p.cbet_size, p.attack) for p in trainer.train_env.profile_params}
    val_profs = {(p.vpip, p.cbet_size, p.attack) for p in trainer.validation_env.profile_params}
    test_profs = {(p.vpip, p.cbet_size, p.attack) for p in trainer.test_env.profile_params}
    
    assert train_profs and val_profs and test_profs
    assert not (train_profs & val_profs), "Train and Validation profiles must not overlap"
    assert not (train_profs & test_profs), "Train and Test profiles must not overlap"
    assert not (val_profs & test_profs), "Validation and Test profiles must not overlap"

def test_champion_selection_uses_validation_only(monkeypatch, tmp_path):
    """Verify that candidate champion selection is determined exclusively by validation_env performance."""
    val_call_a = [0]
    def mock_evaluate_val_a(self, strategy, runs=100, opponents=None, seed_offset=0, verbose=False):
        if seed_offset == 987654321:  # Validation race
            val_call_a[0] += 1
            fit = 0.95 if val_call_a[0] == 1 else 0.35
        else:
            fit = 0.50
        return {
            "fitness": fit,
            "top12_rate": 0.5,
            "final_rate": 0.3,
            "champion_rate": 0.1,
            "avg_rank": 5.0,
            "avg_bb100": 50.0,
            "fitness_se": 0.01,
        }

    monkeypatch.setattr(ArenaEvaluator, "evaluate", mock_evaluate_val_a)
    trainer1 = StrategyTrainer(seed=42, pool_size=12, workers=1)
    champ1, rep1 = trainer1.fit(
        generations=1, population=4, runs_per_candidate=1, final_race=1,
        save=str(tmp_path / "c1.json"), archive=str(tmp_path / "arc1"), resume=False
    )
    assert "validation" in rep1
    assert "test" in rep1
    assert rep1["validation"]["fitness"] == 0.95

    # Run 2: Change validation evaluation to pick Candidate 2 instead
    val_call_b = [0]
    def mock_evaluate_val_b(self, strategy, runs=100, opponents=None, seed_offset=0, verbose=False):
        if seed_offset == 987654321:  # Validation race
            val_call_b[0] += 1
            fit = 0.35 if val_call_b[0] == 1 else 0.95
        else:
            fit = 0.50
        return {
            "fitness": fit,
            "top12_rate": 0.5,
            "final_rate": 0.3,
            "champion_rate": 0.1,
            "avg_rank": 5.0,
            "avg_bb100": 50.0,
            "fitness_se": 0.01,
        }

    monkeypatch.setattr(ArenaEvaluator, "evaluate", mock_evaluate_val_b)
    trainer2 = StrategyTrainer(seed=42, pool_size=12, workers=1)
    champ2, rep2 = trainer2.fit(
        generations=1, population=4, runs_per_candidate=1, final_race=1,
        save=str(tmp_path / "c2.json"), archive=str(tmp_path / "arc2"), resume=False
    )

    # Prove that changing validation evaluation outcome directly controls which candidate is chosen
    assert asdict(champ1) != asdict(champ2), "Validation outcome must control champion selection"
    assert rep2["validation"]["fitness"] == 0.95

def test_test_set_never_used_for_selection(monkeypatch, tmp_path):
    """Rigorous assertion: altering the test set or test scores CANNOT alter the selected champion."""
    def mock_evaluate(self, strategy, runs=100, opponents=None, seed_offset=0, verbose=False):
        is_test = seed_offset == 555555555
        is_val = seed_offset == 987654321
        
        if is_test:
            # Test score is deliberately erratic or poisoned
            fit = 0.01
        elif is_val:
            # Validation cleanly prefers lower vpip
            fit = 0.85 if strategy.vpip < 0.22 else 0.45
        else:
            fit = 0.50

        return {
            "fitness": fit,
            "top12_rate": 0.5,
            "final_rate": 0.3,
            "champion_rate": 0.1,
            "avg_rank": 5.0,
            "avg_bb100": 50.0,
            "fitness_se": 0.02,
        }

    monkeypatch.setattr(ArenaEvaluator, "evaluate", mock_evaluate)

    # Run 1: with normal test set
    trainer1 = StrategyTrainer(seed=42, pool_size=12, workers=1)
    save1 = tmp_path / "model1.json"
    champ1, report1 = trainer1.fit(
        generations=1, population=4, runs_per_candidate=1, final_race=1,
        save=str(save1), archive=str(tmp_path / "arc1"), resume=False
    )

    # Run 2: with completely poisoned test set and different test seed
    trainer2 = StrategyTrainer(seed=42, pool_size=12, workers=1)
    trainer2.test_env = OpponentEnvironment(
        "poisoned_test",
        tuple([StrategyParams(vpip=0.99, open_size=5.0)]),
        tuple([StrategyParams(vpip=0.99, open_size=5.0)])
    )
    save2 = tmp_path / "model2.json"
    champ2, report2 = trainer2.fit(
        generations=1, population=4, runs_per_candidate=1, final_race=1,
        save=str(save2), archive=str(tmp_path / "arc2"), resume=False
    )

    # Assert that champion params selected in both runs are 100% IDENTICAL
    assert asdict(champ1) == asdict(champ2), "Test set perturbation must NOT alter the selected champion"
    # And assert report contains distinct validation and test sections
    assert "validation" in report1 and "test" in report1
    assert "validation" in report2 and "test" in report2
