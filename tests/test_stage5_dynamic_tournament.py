import pytest
from dataclasses import replace
from agentpoker.config import TournamentConfig
from agentpoker.strategy import StrategyAgent, StrategyParams
from agentpoker.tournament import LeagueSimulator, SimAgent, snake_seeding
from agentpoker.training import ARCHETYPES, ArenaEvaluator, StrategyTrainer


def test_progressive_blinds_schedule():
    """Verify blind schedule escalation across preliminary, semifinal, and final table stages."""
    # Default: static 100/200
    cfg_static = TournamentConfig.official_120(progressive_blinds=False)
    for r in range(1, 11):
        assert cfg_static.get_blinds(r, stage="preliminary") == (100, 200)
    assert cfg_static.get_blinds(11, stage="semifinal") == (100, 200)
    assert cfg_static.get_blinds(12, stage="final") == (100, 200)

    # Progressive blinds enabled
    cfg_prog = TournamentConfig.official_120(progressive_blinds=True)
    # R1-R3: 100/200
    for r in (1, 2, 3):
        assert cfg_prog.get_blinds(r, stage="preliminary") == (100, 200)
    # R4-R7: 150/300
    for r in (4, 5, 6, 7):
        assert cfg_prog.get_blinds(r, stage="preliminary") == (150, 300)
    # R8-R10: 200/400
    for r in (8, 9, 10):
        assert cfg_prog.get_blinds(r, stage="preliminary") == (200, 400)
    # Semifinal (R11): 150/300
    assert cfg_prog.get_blinds(11, stage="semifinal") == (150, 300)
    # Final table (R12): 200/400
    assert cfg_prog.get_blinds(12, stage="final") == (200, 400)

    # Custom schedule
    custom_sched = [(50, 100), (75, 150), (100, 200)]
    cfg_custom = TournamentConfig(field_size=12, blind_schedule=custom_sched)
    assert cfg_custom.get_blinds(1) == (50, 100)
    assert cfg_custom.get_blinds(2) == (75, 150)
    assert cfg_custom.get_blinds(3) == (100, 200)


def test_snake_seeding_structure():
    """Verify snake seeding splits ranked seeds symmetrically across tables."""
    # 12 players into 2 tables
    players = [f"p{i}" for i in range(1, 13)]
    tables = snake_seeding(players, 2)
    assert len(tables) == 2
    # Table 0: 1, 4, 5, 8, 9, 12
    assert tables[0] == ["p1", "p4", "p5", "p8", "p9", "p12"]
    # Table 1: 2, 3, 6, 7, 10, 11
    assert tables[1] == ["p2", "p3", "p6", "p7", "p10", "p11"]

    # 18 players into 3 tables
    p18 = [f"p{i}" for i in range(1, 19)]
    t3 = snake_seeding(p18, 3)
    assert len(t3) == 3
    # Forward: 1->T0, 2->T1, 3->T2. Backward: 4->T2, 5->T1, 6->T0. Forward: 7->T0, 8->T1, 9->T2...
    assert t3[0] == ["p1", "p6", "p7", "p12", "p13", "p18"]
    assert t3[1] == ["p2", "p5", "p8", "p11", "p14", "p17"]
    assert t3[2] == ["p3", "p4", "p9", "p10", "p15", "p16"]


def test_semifinal_and_final_cold_start_context():
    """Verify that at hand 0 of semifinal and final tables, context provides valid seeded standings."""
    cfg = TournamentConfig(
        field_size=12,
        preliminary_rounds=1,
        hands_per_round=2,
        semifinal_hands=2,
        final_hands=2,
        progressive_blinds=True,
    )
    agents = [
        SimAgent(f"a_{i}", StrategyAgent(ARCHETYPES["balanced"], seed=42 + i, name=f"a_{i}"))
        for i in range(12)
    ]
    sim = LeagueSimulator(agents, seed=42, config=cfg)
    result = sim.run_event()

    assert "semifinal" in result
    assert len(result["semifinal"]) == 2
    assert "final" in result
    assert len(result["final"]) == 6

    # Verify that all final table standings have valid non-negative hands and ranked positions
    for i, s in enumerate(result["final"], 1):
        assert s.rank == i
        assert s.hands == 2
        assert s.bb100 is not None


def test_scale_adaptive_tournament_execution():
    """Verify scale adaptivity: field of 6 advances directly to final; field of 12 runs semifinal."""
    # 6 players: skips semifinal, top 6 form final table directly
    agents6 = [
        SimAgent(f"p_{i}", StrategyAgent(ARCHETYPES["balanced"], seed=100 + i, name=f"p_{i}"))
        for i in range(6)
    ]
    sim6 = LeagueSimulator(agents6, seed=100)
    res6 = sim6.run_event()
    assert res6["semifinal"] == []
    assert len(res6["final"]) == 6
    assert res6["final"][0].rank == 1

    # 12 players: runs 2-table semifinal then 1-table final
    agents12 = [
        SimAgent(f"p_{i}", StrategyAgent(ARCHETYPES["balanced"], seed=200 + i, name=f"p_{i}"))
        for i in range(12)
    ]
    sim12 = LeagueSimulator(agents12, seed=200)
    res12 = sim12.run_event()
    assert len(res12["semifinal"]) == 2
    assert len(res12["final"]) == 6


def test_progressive_blinds_engine_escalation():
    """Verify that during a tournament with progressive blinds, engine blinds change across rounds."""
    cfg = TournamentConfig(
        field_size=12,
        preliminary_rounds=5,
        hands_per_round=1,
        semifinal_hands=1,
        final_hands=1,
        progressive_blinds=True,
    )
    agents = [
        SimAgent(f"b_{i}", StrategyAgent(ARCHETYPES["balanced"], seed=300 + i, name=f"b_{i}"))
        for i in range(12)
    ]
    sim = LeagueSimulator(agents, seed=300, config=cfg)
    sim.run_event()
    # At end of final table, engine blinds should be 200/400
    assert sim.engine.sb == 200
    assert sim.engine.bb == 400


def test_trainer_progressive_blinds_integration():
    """Verify ArenaEvaluator and StrategyTrainer run seamlessly with progressive blinds."""
    cfg = TournamentConfig(
        field_size=12,
        preliminary_rounds=2,
        hands_per_round=2,
        semifinal_hands=2,
        final_hands=2,
        progressive_blinds=True,
    )
    evaluator = ArenaEvaluator(
        pool_size=12,
        seed=42,
        workers=1,
        tournament_config=cfg,
    )
    metrics = evaluator.evaluate(ARCHETYPES["balanced"], runs=2, verbose=False)
    assert "fitness" in metrics
    assert "prelim_bb100" in metrics
    assert "overall_bb100" in metrics
    assert metrics["fitness"] > 0.0

    trainer = StrategyTrainer(
        seed=42,
        pool_size=12,
        workers=1,
        tournament_config=cfg,
    )
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        champ, report = trainer.fit(
            generations=1,
            population=2,
            runs_per_candidate=1,
            final_race=1,
            save=f"{tmpdir}/candidate.json",
            archive=f"{tmpdir}/archive",
        )
        assert isinstance(champ, StrategyParams)
        assert "validation" in report
        assert "test" in report
