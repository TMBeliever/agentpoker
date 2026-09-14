"""Stage 4 Unit & Integration Test Suite: Self-Play Genetic Isolation & Quality-Diversity.

Verifies:
1. Mathematical properties of genome_distance (reflexivity, symmetry, boundedness).
2. Deterministic hashing with strategy_signature for identifying clones.
3. Anti-echo-chamber opponent sampling (_draw_pool strictly excludes exact clones and near-clones).
4. Pairwise diversity and non-clustering among drawn shadow clones.
5. Quality-Diversity (MAP-Elites / niche competition) Hall of Fame update and pruning.
6. End-to-end training integration with self-play and hall_diversity tracking.
"""
import json
import pytest
from dataclasses import replace

from agentpoker.strategy import StrategyParams
from agentpoker.training import (
    ARCHETYPES,
    StrategyTrainer,
    genome_distance,
    strategy_signature,
    hall_of_fame_diversity,
    update_hall_of_fame_qd,
)


def test_genome_distance_properties():
    """Verify mathematical distance axioms on strategy parameter spaces."""
    p_bal = ARCHETYPES["balanced"]
    p_nit = ARCHETYPES["nit"]
    p_man = ARCHETYPES["maniac"]

    # 1. Reflexivity: distance to self is 0.0
    assert pytest.approx(genome_distance(p_bal, p_bal), abs=1e-7) == 0.0
    assert pytest.approx(genome_distance(p_nit, p_nit), abs=1e-7) == 0.0

    # 2. Symmetry: dist(A, B) == dist(B, A)
    assert pytest.approx(genome_distance(p_bal, p_nit), abs=1e-7) == genome_distance(p_nit, p_bal)
    assert pytest.approx(genome_distance(p_nit, p_man), abs=1e-7) == genome_distance(p_man, p_nit)

    # 3. Positivity & Meaningful Separation
    d_nit_man = genome_distance(p_nit, p_man)
    assert 0.20 < d_nit_man < 1.0, f"Expected distinct archetypes to have distance > 0.20, got {d_nit_man}"

    # 4. Triangle-like consistency
    d_bal_nit = genome_distance(p_bal, p_nit)
    d_bal_man = genome_distance(p_bal, p_man)
    assert d_nit_man <= d_bal_nit + d_bal_man + 1e-6


def test_strategy_signature_exact_and_quasi_clones():
    """Verify deterministic signatures differentiate distinct strategies and match identical ones."""
    p1 = StrategyParams(vpip=0.25, attack=0.60)
    p1_clone = replace(p1)
    p2 = StrategyParams(vpip=0.35, attack=0.75)

    sig1 = strategy_signature(p1)
    sig1_clone = strategy_signature(p1_clone)
    sig2 = strategy_signature(p2)

    assert sig1 == sig1_clone, "Identical parameters must produce identical signature"
    assert sig1 != sig2, "Distinct parameters must produce distinct signature"
    assert len(sig1) == 16


def test_anti_echo_chamber_draw_pool_strictly_excludes_clones_and_near_clones():
    """Verify that _draw_pool strictly rejects exact clones and near-clones of focal candidate."""
    trainer = StrategyTrainer(seed=42, pool_size=12, workers=1)
    trainer.self_play = True
    trainer.shadow_clones = 3

    focal = StrategyParams(vpip=0.250, attack=0.600)
    exact_clone = replace(focal)
    near_clone = replace(focal, vpip=0.252)  # distance < 0.01

    assert genome_distance(focal, exact_clone) == 0.0
    assert genome_distance(focal, near_clone) < 0.02

    # Hall containing focal clone and near-clone alongside diverse archetypes
    hall = [
        (0.60, exact_clone),
        (0.58, near_clone),
        (0.55, ARCHETYPES["nit"]),
        (0.52, ARCHETYPES["lag"]),
        (0.50, ARCHETYPES["station"]),
    ]

    pool = trainer._draw_pool(
        population=[],
        hall=hall,
        seed=12345,
        profile_pool=[],
        exclude=focal,
        generation=5,
        min_genetic_distance=0.08,
    )

    focal_sig = strategy_signature(focal)
    shadows = pool[:trainer.shadow_clones]
    assert len(shadows) == trainer.shadow_clones
    for opp in shadows:
        # 1. No shadow clone may have the exact same signature
        assert strategy_signature(opp) != focal_sig, "Exact clone must not be drawn into opponent pool as shadow clone"
        # 2. Shadow clones must not be near-clones of focal candidate
        d = genome_distance(opp, focal)
        assert d > 0.07, f"Shadow clone {opp} is too close to focal (distance {d:.4f} <= 0.07)"


def test_mutual_separation_among_drawn_shadow_clones():
    """Verify that multiple shadow clones drawn into the same pool are mutually separated."""
    trainer = StrategyTrainer(seed=42, pool_size=20, workers=1)
    trainer.self_play = True
    trainer.shadow_clones = 3

    focal = StrategyParams(vpip=0.50, attack=0.50)
    # Hall with pairs of clones
    hall = [
        (0.70, ARCHETYPES["lag"]),
        (0.69, replace(ARCHETYPES["lag"], vpip=0.312)),  # near clone of lag
        (0.65, ARCHETYPES["nit"]),
        (0.64, replace(ARCHETYPES["nit"], vpip=0.142)),  # near clone of nit
        (0.60, ARCHETYPES["station"]),
    ]

    pool = trainer._draw_pool(
        population=[],
        hall=hall,
        seed=999,
        profile_pool=[],
        exclude=focal,
        min_genetic_distance=0.08,
        min_pairwise_distance=0.05,
    )

    # Inspect shadow clones in pool (the first shadow_clones elements)
    shadows = pool[:trainer.shadow_clones]
    assert len(shadows) >= 2
    for i in range(len(shadows)):
        for j in range(i + 1, len(shadows)):
            d = genome_distance(shadows[i], shadows[j])
            assert d >= 0.03, f"Shadow clones {i} and {j} are clustered too closely (distance {d:.4f})"


def test_quality_diversity_hall_of_fame_niche_competition_and_pruning():
    """Verify MAP-Elites niche competition: within-niche upgrade vs novel-niche expansion."""
    hall = []

    p_lag = ARCHETYPES["lag"]
    p_nit = ARCHETYPES["nit"]
    p_station = ARCHETYPES["station"]

    # 1. Insert 3 distinct archetypes -> creates 3 distinct niches
    hall = update_hall_of_fame_qd(hall, p_lag, fitness=0.50, max_hall_size=4, niche_radius=0.08)
    hall = update_hall_of_fame_qd(hall, p_nit, fitness=0.48, max_hall_size=4, niche_radius=0.08)
    hall = update_hall_of_fame_qd(hall, p_station, fitness=0.45, max_hall_size=4, niche_radius=0.08)
    assert len(hall) == 3

    # 2. Add an inferior near-clone of LAG (distance < 0.08, fitness 0.47 < 0.50)
    inferior_lag = replace(p_lag, vpip=p_lag.vpip + 0.01)
    assert genome_distance(p_lag, inferior_lag) < 0.05
    hall = update_hall_of_fame_qd(hall, inferior_lag, fitness=0.47, max_hall_size=4, niche_radius=0.08)
    assert len(hall) == 3
    # LAG niche member must still be the 0.50 original
    assert hall[0][0] == 0.50

    # 3. Add a superior near-clone of LAG (fitness 0.55 > 0.50)
    superior_lag = replace(p_lag, vpip=p_lag.vpip + 0.015)
    hall = update_hall_of_fame_qd(hall, superior_lag, fitness=0.55, max_hall_size=4, niche_radius=0.08)
    assert len(hall) == 3
    assert hall[0][0] == 0.55
    assert hall[0][1].vpip == superior_lag.vpip

    # 4. Add 2 novel branches (balanced and maniac) when max_hall_size=4 -> triggers diversity pruning
    p_bal = ARCHETYPES["balanced"]
    p_man = ARCHETYPES["maniac"]
    hall = update_hall_of_fame_qd(hall, p_bal, fitness=0.52, max_hall_size=4, niche_radius=0.08)
    hall = update_hall_of_fame_qd(hall, p_man, fitness=0.51, max_hall_size=4, niche_radius=0.08)
    assert len(hall) <= 4

    # 5. Verify Hall of Fame diversity is strictly positive and high
    div = hall_of_fame_diversity(hall)
    assert div > 0.15, f"Expected Hall of Fame diversity > 0.15, got {div:.4f}"


def test_end_to_end_training_with_self_play_and_qd_hall(tmp_path):
    """Verify that fit() logs and stores hall_diversity with self-play enabled."""
    save_file = tmp_path / "cand_stage4.json"
    archive_dir = tmp_path / "archive_stage4"

    trainer = StrategyTrainer(
        seed=202,
        pool_size=12,
        workers=1,
        self_play=True,
        shadow_clones=2,
        profile_share=0.0,
    )

    champ, history_dict = trainer.fit(
        generations=2,
        population=4,
        runs_per_candidate=1,
        final_race=1,
        save=str(save_file),
        archive=str(archive_dir),
        resume=False,
    )

    assert save_file.exists()

    # Check gen_001.json and gen_002.json for hall_diversity
    for g in (1, 2):
        gen_path = archive_dir / f"gen_{g:03d}.json"
        assert gen_path.exists()
        data = json.loads(gen_path.read_text(encoding="utf-8"))
        assert "hall_diversity" in data
        assert data["hall_diversity"] >= 0.0
        assert "population_diversity" in data
