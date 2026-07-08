from kraken_ew.config import load_scoring_config
from kraken_ew.scoring.composite import compute_score


def test_compute_score_uptrend(uptrend_df):
    config = load_scoring_config()
    breakdown = compute_score(uptrend_df, "TESTUSD", config)
    assert 0 <= breakdown.total <= 100
    assert set(breakdown.components) == set(config.weights)
    assert set(breakdown.weighted) == set(config.weights)
    assert breakdown.direction in ("long", "short", "neutral")
    # weighted total should equal sum of weighted components
    assert abs(sum(breakdown.weighted.values()) - breakdown.total) < 1e-9


def test_compute_score_zigzag(zigzag_df):
    config = load_scoring_config()
    breakdown = compute_score(zigzag_df, "TESTUSD", config)
    assert 0 <= breakdown.total <= 100
    assert breakdown.metadata["num_pivots"] > 0
