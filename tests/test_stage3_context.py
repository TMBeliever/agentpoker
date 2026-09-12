import pytest
from agentpoker.context import (
    TournamentContext,
    build_context,
    build_preliminary_context,
    build_semifinal_context,
    build_final_context,
    synthetic_context,
    rank_from_bb100,
    boundary_bb100,
)
from agentpoker.strategy import StrategyAgent, StrategyParams


def test_tournament_context_dataclass():
    """G3.1: TournamentContext dataclass initializes and serializes cleanly."""
    ctx = TournamentContext(
        stage="preliminary",
        rank=5,
        bb100=35.0,
        hands_remaining=100,
        total_stage_hands=200,
        stage_progress=0.5,
        round_no=5,
        target_rank=12,
        cutoff_bb100=25.0,
        buffer_bb100=10.0,
        table_strength=0.25,
        rank12_bb100=28.0,
        rank13_bb100=25.0,
    )
    d = ctx.to_dict()
    assert d["stage"] == "preliminary"
    assert d["rank"] == 5
    assert d["bb100"] == 35.0
    assert d["hands_remaining"] == 100
    assert d["total_stage_hands"] == 200
    assert d["stage_progress"] == 0.5
    assert d["round_no"] == 5
    assert d["target_rank"] == 12
    assert d["cutoff_bb100"] == 25.0
    assert d["buffer_bb100"] == 10.0
    assert d["table_strength"] == 0.25


def test_stage_resolution_and_defaults():
    """G3.2: build_context automatically infers stage, target rank, and total hands."""
    # 1. Preliminary (round 1..10)
    p_ctx = build_context(rank=10, bb100=30.0, rank12_bb100=28.0, rank13_bb100=25.0, hands_remaining=150, round_no=3)
    assert p_ctx["stage"] == "preliminary"
    assert p_ctx["target_rank"] == 12
    assert p_ctx["total_stage_hands"] == 200
    assert p_ctx["stage_progress"] == pytest.approx(1.0 - (150 / 200))  # 0.25
    assert p_ctx["cutoff_bb100"] == 25.0  # hero rank 10 <= 12, so cutoff is rank13
    assert p_ctx["buffer_bb100"] == pytest.approx(5.0)

    # 2. Semifinal (round 11)
    sf_ctx = build_context(rank=2, bb100=40.0, rank3_bb100=20.0, rank4_bb100=15.0, hands_remaining=5, round_no=11)
    assert sf_ctx["stage"] == "semifinal"
    assert sf_ctx["target_rank"] == 3
    assert sf_ctx["total_stage_hands"] == 20
    assert sf_ctx["stage_progress"] == pytest.approx(1.0 - (5 / 20))  # 0.75
    assert sf_ctx["cutoff_bb100"] == 15.0  # hero rank 2 <= 3, cutoff is rank4
    assert sf_ctx["buffer_bb100"] == pytest.approx(25.0)

    # 3. Final (round 12)
    f_ctx = build_context(rank=1, bb100=60.0, leader_bb100=60.0, second_bb100=35.0, hands_remaining=10, round_no=12)
    assert f_ctx["stage"] == "final"
    assert f_ctx["target_rank"] == 1
    assert f_ctx["total_stage_hands"] == 30
    assert f_ctx["stage_progress"] == pytest.approx(1.0 - (10 / 30))  # ~0.667
    assert f_ctx["cutoff_bb100"] == 35.0  # hero rank 1, cutoff is second place
    assert f_ctx["buffer_bb100"] == pytest.approx(25.0)


def test_preliminary_cutoff_and_buffer_logic():
    """G3.3: Preliminary correctly tracks qualification vs elimination boundary."""
    # Agent outside Top 12 (Rank 18): target is Rank 12 (must surpass Rank 12)
    ctx_outside = build_context(
        rank=18, bb100=10.0, rank12_bb100=28.0, rank13_bb100=25.0, hands_remaining=100, round_no=5
    )
    assert ctx_outside["cutoff_bb100"] == 28.0
    assert ctx_outside["buffer_bb100"] == pytest.approx(-18.0)  # 18 BB behind qualification

    # Agent inside Top 12 (Rank 4): buffer is over Rank 13 (elimination threshold)
    ctx_inside = build_context(
        rank=4, bb100=50.0, rank12_bb100=28.0, rank13_bb100=25.0, hands_remaining=100, round_no=5
    )
    assert ctx_inside["cutoff_bb100"] == 25.0
    assert ctx_inside["buffer_bb100"] == pytest.approx(25.0)  # 25 BB cushion above elimination


def test_dedicated_stage_builders():
    """G3.4: Dedicated stage builders construct accurate context representations."""
    p = build_preliminary_context(rank=8, bb100=32.0, rank12_bb100=28.0, rank13_bb100=25.0, hands_remaining=80, round_no=6)
    assert p["stage"] == "preliminary"
    assert p["target_rank"] == 12
    assert p["total_stage_hands"] == 200

    sf = build_semifinal_context(rank=4, bb100=12.0, rank3_bb100=20.0, rank4_bb100=12.0, hands_remaining=10)
    assert sf["stage"] == "semifinal"
    assert sf["target_rank"] == 3
    assert sf["total_stage_hands"] == 20
    assert sf["cutoff_bb100"] == 20.0  # rank 4 > 3, must surpass rank 3
    assert sf["buffer_bb100"] == pytest.approx(-8.0)

    f = build_final_context(rank=2, bb100=40.0, leader_bb100=55.0, second_bb100=40.0, hands_remaining=15)
    assert f["stage"] == "final"
    assert f["target_rank"] == 1
    assert f["total_stage_hands"] == 30
    assert f["cutoff_bb100"] == 55.0  # rank 2, must surpass leader
    assert f["buffer_bb100"] == pytest.approx(-15.0)


def test_synthetic_context_stage_awareness():
    """G3.5: synthetic_context generates valid preliminary context when standings are absent."""
    syn = synthetic_context(bb100=30.0, hands_remaining=100, round_no=5)
    assert syn["stage"] == "preliminary"
    assert syn["rank"] is not None
    assert syn["target_rank"] == 12
    assert syn["total_stage_hands"] == 200
    assert syn["hands_remaining"] == 100
    assert syn["cutoff_bb100"] is not None


def test_strategy_pressure_stage_awareness():
    """G3.6: StrategyAgent._tournament_pressure adapts specifically to each stage."""
    agent = StrategyAgent(StrategyParams(safety=0.60, attack=0.70))

    # 1. Semifinal when safely advancing (rank 1, buffer > 15, late hands) -> pressure reduced
    ctx_sf_safe = build_semifinal_context(rank=1, bb100=50.0, rank3_bb100=25.0, rank4_bb100=10.0, hands_remaining=5)
    p_sf_safe = agent._tournament_pressure(ctx_sf_safe)
    assert p_sf_safe < 0.0  # safety shift engages

    # 2. Semifinal when facing elimination (rank 5, late hands) -> attack mode
    ctx_sf_danger = build_semifinal_context(rank=5, bb100=5.0, rank3_bb100=25.0, rank4_bb100=15.0, hands_remaining=5)
    p_sf_danger = agent._tournament_pressure(ctx_sf_danger)
    assert p_sf_danger > 0.5  # aggressive urgency

    # 3. Final when leading with comfortable cushion -> reduced pressure
    ctx_f_lead = build_final_context(rank=1, bb100=70.0, leader_bb100=70.0, second_bb100=30.0, hands_remaining=5)
    p_f_lead = agent._tournament_pressure(ctx_f_lead)
    assert p_f_lead < 0.0  # protect championship lead

    # 4. Final when trailing -> full championship attack
    ctx_f_trail = build_final_context(rank=3, bb100=20.0, leader_bb100=60.0, second_bb100=40.0, hands_remaining=5)
    p_f_trail = agent._tournament_pressure(ctx_f_trail)
    assert p_f_trail > 0.6  # maximum attack for 1st place
