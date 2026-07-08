from kraken_ew.waves.fibonacci import (
    FibLevel,
    confluence_score,
    extension_levels,
    retracement_levels,
)
from kraken_ew.waves.pivots import Pivot


def make_pivot(price, kind, idx=0):
    return Pivot(index=idx, timestamp=idx * 3600, price=price, kind=kind)


def test_retracement_levels_for_upmove():
    start = make_pivot(100, "low", 0)
    end = make_pivot(200, "high", 1)
    levels = retracement_levels(start, end, ratios=(0.5, 0.618))
    by_ratio = {l.ratio: l.price for l in levels}
    assert by_ratio[0.5] == 150
    assert abs(by_ratio[0.618] - 138.2) < 1e-6


def test_extension_levels_for_upmove():
    start = make_pivot(100, "low", 0)
    end = make_pivot(200, "high", 1)
    retrace = make_pivot(150, "low", 2)
    levels = extension_levels(start, end, retrace, ratios=(1.0, 1.618))
    by_ratio = {l.ratio: l.price for l in levels}
    assert by_ratio[1.0] == 250  # 150 + (200-100)*1.0
    assert abs(by_ratio[1.618] - (150 + 100 * 1.618)) < 1e-6


def test_confluence_score_full_match():
    levels = [FibLevel(ratio=0.618, price=150.0, kind="retracement")]
    score = confluence_score([levels, levels], target_price=150.0)
    assert score == 100.0


def test_confluence_score_no_match():
    levels = [FibLevel(ratio=0.618, price=150.0, kind="retracement")]
    score = confluence_score([levels], target_price=500.0)
    assert score == 0.0


def test_confluence_score_partial_match():
    near = [FibLevel(ratio=0.618, price=150.0, kind="retracement")]
    far = [FibLevel(ratio=0.618, price=500.0, kind="retracement")]
    score = confluence_score([near, far], target_price=150.0)
    assert 0 < score < 100
