from __future__ import annotations
import json
import pytest
from dataclasses import asdict
from agentpoker.training import (
    StrategyTrainer,
    StrategyParams,
    _summarise,
    _load_params_safe,
    ARCHETYPES,
)

def test_summarise_with_120_player_equilibrium():
    """Verify 120-player baseline expectation rates and calibrated advantage factors."""
    # Simulation of a strong candidate in a 120-player field over 50 runs:
    # 15 top12 qualifications (30%), 6 finals (12%), 2 wins (4%), average BB/100 = +25.0
    runs = 50
    pool = 120
    top = 15
    final = 6
    champ = 2
    ranks = [15.0] * 50
    bbs = [25.0] * 50

    m = _summarise(top, final, champ, ranks, bbs, runs, pool)

    assert m["expected_top_rate"] == pytest.approx(12.0 / 120.0)  # 10%
    assert m["expected_final_rate"] == pytest.approx(6.0 / 120.0)  # 5%
    assert m["expected_champion_rate"] == pytest.approx(1.0 / 120.0)  # 0.833%

    assert m["top12_rate"] == 0.30
    assert m["final_rate"] == 0.12
    assert m["champion_rate"] == 0.04

    # Advantage multipliers over random baseline
    assert m["adv_top"] == pytest.approx(3.0)      # 3.0x baseline
    assert m["adv_final"] == pytest.approx(2.4)    # 2.4x baseline
    assert m["adv_champ"] == pytest.approx(4.8)    # 4.8x baseline

    assert 0.0 < m["fitness"] <= 1.0
    assert 0.0 < m["calibrated_fitness"] <= 1.0

def test_clamp_and_validate_enforces_poker_invariants():
    """Verify that _clamp_and_validate maintains positional hierarchy and value order."""
    trainer = StrategyTrainer(pool_size=24, seed=42)
    # Intentionally malformed params
    bad_dict = {
        "vpip": 0.50, # Out of bound (>0.38)
        "open_thresh_utg": 0.30, # Higher than BTN
        "open_thresh_btn": 0.20,
        "open_thresh_co": 0.25,
        "open_thresh_hj": 0.28,
        "value_threshold": 0.60,
        "thin_value_threshold": 0.65, # Inverted: thin > value!
        "wet_board_bet_size": 0.30,
        "dry_board_bet_size": 0.50, # Inverted: dry > wet!
    }
    # Populate missing keys
    base = asdict(StrategyParams())
    base.update(bad_dict)

    trainer._clamp_and_validate(base)

    # Invariants enforced
    assert base["vpip"] <= 0.38
    assert base["open_thresh_utg"] < base["open_thresh_hj"] < base["open_thresh_co"] < base["open_thresh_btn"]
    assert base["thin_value_threshold"] < base["value_threshold"]
    assert base["wet_board_bet_size"] > base["dry_board_bet_size"]

def test_checkpoint_save_and_resumption(tmp_path):
    """Verify checkpoint saving and automatic resumption from previous generations."""
    archive_dir = tmp_path / "archive"
    save_model = tmp_path / "champion.json"

    trainer = StrategyTrainer(pool_size=12, seed=123, workers=1)

    # Run 1 generation with 2 population candidates, 1 run per candidate
    champ, hist = trainer.fit(
        generations=1,
        population=2,
        runs_per_candidate=1,
        save=str(save_model),
        archive=str(archive_dir),
        final_race=1,
        resume=True,
    )

    gen1_file = archive_dir / "gen_001.json"
    assert gen1_file.exists()
    data1 = json.loads(gen1_file.read_text(encoding="utf-8"))
    assert data1["generation"] == 1
    assert "champion" in data1

    # Now resume for generation 2
    champ2, hist2 = trainer.fit(
        generations=1,
        population=2,
        runs_per_candidate=1,
        save=str(save_model),
        archive=str(archive_dir),
        final_race=1,
        resume=True,
    )

    gen2_file = archive_dir / "gen_002.json"
    assert gen2_file.exists()
    data2 = json.loads(gen2_file.read_text(encoding="utf-8"))
    assert data2["generation"] == 2

def test_safe_load_params_with_extraneous_keys():
    """Verify _load_params_safe cleanly filters unknown keys from legacy or external json."""
    corrupted = {
        "vpip": 0.24,
        "unknown_parameter_xyz": 1234,
        "legacy_score": "ignore_me",
    }
    p = _load_params_safe(corrupted)
    assert isinstance(p, StrategyParams)
    assert p.vpip == 0.24
    assert not hasattr(p, "unknown_parameter_xyz")
