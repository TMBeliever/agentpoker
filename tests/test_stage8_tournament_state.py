import pytest
import warnings
from unittest.mock import MagicMock
from agentpoker.context import context_from_standings, synthetic_context
from agentpoker.live import LiveRunner


def _make_sample_standings(n: int = 15):
    return [
        {"agentId": f"bot_{i}", "bb100": float(100 - i * 5)}
        for i in range(1, n + 1)
    ]


def test_real_standings_produces_real_context_source_and_full_confidence():
    rows = _make_sample_standings(15)
    with warnings.catch_warnings(record=True) as record:
        warnings.simplefilter("always")
        ctx = context_from_standings(rows, hero_id="bot_3", hands_remaining=150, round_no=3)
        assert len(record) == 0, "Real standings should not emit synthetic warnings"

    assert ctx is not None
    assert ctx["context_source"] == "real"
    assert ctx["exploit_confidence"] == 1.0
    assert ctx["rank"] == 3
    assert ctx["bb100"] == 85.0


def test_synthetic_context_fallback_tags_source_and_reduces_confidence():
    with pytest.warns(UserWarning, match="Using synthetic context"):
        ctx = synthetic_context(bb100=25.0, hands_remaining=100, round_no=5)

    assert ctx["context_source"] == "synthetic"
    assert ctx["exploit_confidence"] == 0.5
    assert ctx["bb100"] == 25.0


def test_live_runner_prefers_real_standings_and_falls_back_to_synthetic():
    mock_client = MagicMock()
    mock_client.cfg.competition_id = "test_comp"
    runner = LiveRunner(client=mock_client)

    # 1. When real standings are available
    runner._standings_rows = _make_sample_standings(15)
    ctx_real = runner._get_tournament_context(hero_id="bot_2")
    assert ctx_real["context_source"] == "real"
    assert ctx_real["exploit_confidence"] == 1.0

    # 2. When standings are empty, falls back to synthetic
    runner._standings_rows = []
    with pytest.warns(UserWarning, match="Using synthetic context"):
        ctx_synthetic = runner._get_tournament_context(hero_id="bot_2")
    assert ctx_synthetic["context_source"] == "synthetic"
    assert ctx_synthetic["exploit_confidence"] == 0.5
