import pytest
import warnings
import agentpoker.context_data as cd
from agentpoker.context import (
    synthetic_context,
    rank_from_bb100,
    boundary_bb100,
    RANK_LADDER,
    GOLDEN_LINE_BB100,
    FIELD_SIZE,
    QUALIFY_RANK,
)

def test_context_data_module_properties():
    """Verify formal context_data module constants and types."""
    assert cd.FIELD_SIZE == 120
    assert cd.QUALIFY_RANK == 12
    assert cd.GOLDEN_LINE_BB100 == 28.0
    assert isinstance(cd.RANK_LADDER, list)
    assert len(cd.RANK_LADDER) >= 10


def test_rank_ladder_monotonicity():
    """Rank must be monotone non-increasing as win rate increases (1st is best, 120th is worst)."""
    prev_bb, prev_rank = cd.RANK_LADDER[0]
    for bb, rank in cd.RANK_LADDER[1:]:
        assert bb > prev_bb, f"BB/100 not strictly ascending: {bb} <= {prev_bb}"
        assert rank <= prev_rank, f"Rank not monotone non-increasing: rank {rank} > {prev_rank} for bb {bb}"
        assert 1 <= rank <= 120, f"Rank {rank} out of valid [1, 120] range"
        prev_bb, prev_rank = bb, rank


def test_golden_line_and_qualification():
    """Golden line BB/100 corresponds exactly to the 12th place qualification cutoff."""
    r_at_golden = rank_from_bb100(cd.GOLDEN_LINE_BB100)
    assert r_at_golden == 12, f"Expected rank 12 at golden line {cd.GOLDEN_LINE_BB100}, got {r_at_golden}"

    b_at_12 = boundary_bb100(12)
    assert b_at_12 == cd.GOLDEN_LINE_BB100


def test_synthetic_context_warning():
    """synthetic_context must emit an explicit UserWarning so operations can detect missing server standings."""
    with pytest.warns(UserWarning, match="Using synthetic context because standings are unavailable"):
        ctx = synthetic_context(bb100=25.0, hands_remaining=100, round_no=5)
    
    assert ctx["stage"] == "preliminary"
    assert ctx["target_rank"] == 12
    assert ctx["total_stage_hands"] == 200
    assert ctx["bb100"] == 25.0
    assert ctx["rank"] is not None


def test_extreme_win_rates():
    """Extreme win rates must clamp cleanly without crashing or NaN."""
    assert rank_from_bb100(-9999.0) == 120
    assert rank_from_bb100(+9999.0) == 1
    assert rank_from_bb100(0.0) == 60
