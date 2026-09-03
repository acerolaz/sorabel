from app.domain.confidence import classify_confidence


def test_score_above_high_threshold_is_high_confidence():
    assert classify_confidence(0.85) == "high"


def test_score_at_high_threshold_is_high_confidence():
    assert classify_confidence(0.7) == "high"


def test_score_in_hedge_band_is_low_confidence():
    assert classify_confidence(0.55) == "low"


def test_score_at_low_threshold_is_low_confidence():
    assert classify_confidence(0.4) == "low"


def test_score_below_low_threshold_is_refused():
    assert classify_confidence(0.1) == "refused"
