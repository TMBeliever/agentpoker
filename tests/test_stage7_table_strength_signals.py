import pytest
from agentpoker.context import TableStrengthModel, OpponentStrengthSignal


def test_signal_split_fields_present():
    data = {
        "hands": 50,
        "archetype": "TAG",
        "vpip": 0.20,
        "pfr": 0.17,
        "af": 2.5,
        "threebet": 0.09,
        "bb_100": 15.0,
    }
    sig = TableStrengthModel.evaluate_opponent_signals(data)
    assert isinstance(sig, OpponentStrengthSignal)
    assert hasattr(sig, "behavioral_skill_signal")
    assert hasattr(sig, "performance_signal")
    assert hasattr(sig, "confidence")
    assert hasattr(sig, "posterior_strength")

    assert -1.0 <= sig.behavioral_skill_signal <= 1.0
    assert -1.0 <= sig.performance_signal <= 1.0
    assert 0.0 <= sig.confidence <= 1.0
    assert -1.0 <= sig.posterior_strength <= 1.0


def test_performance_alone_not_treated_as_strength():
    # A calling station / fish who got lucky over a small sample of 25 hands
    lucky_fish = {
        "hands": 25,
        "archetype": "station",
        "vpip": 0.55,
        "pfr": 0.08,
        "af": 0.5,
        "threebet": 0.02,
        "bb_100": 120.0,  # Extremely high short-term performance luck
    }
    sig = TableStrengthModel.evaluate_opponent_signals(lucky_fish)

    # Performance signal is positive due to high BB/100
    assert sig.performance_signal > 0.5

    # But behavioral skill signal must be strongly negative for station
    assert sig.behavioral_skill_signal < -0.4

    # Crucial Rule: Performance alone is NOT strength!
    # Posterior strength must remain negative despite positive performance
    assert sig.posterior_strength < 0.0


def test_zero_sample_confidence_regression():
    unobserved = {
        "hands": 0,
        "archetype": "shark",
        "bb_100": 50.0,
    }
    sig = TableStrengthModel.evaluate_opponent_signals(unobserved)
    assert sig.confidence == 0.0
    assert sig.posterior_strength == 0.0


def test_shark_strong_behavioral_and_high_posterior():
    tag_shark = {
        "hands": 100,
        "archetype": "TAG",
        "vpip": 0.21,
        "pfr": 0.18,
        "af": 2.4,
        "threebet": 0.09,
        "bb_100": 20.0,
    }
    sig = TableStrengthModel.evaluate_opponent_signals(tag_shark)
    assert sig.behavioral_skill_signal > 0.5
    assert sig.confidence > 0.8
    assert sig.posterior_strength > 0.4
