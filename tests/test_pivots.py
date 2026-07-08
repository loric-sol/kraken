from kraken_ew.waves.pivots import fractal_pivots, zigzag_pivots


def test_zigzag_finds_alternating_pivots(zigzag_df):
    pivots = zigzag_pivots(zigzag_df, threshold_pct=5.0)
    assert len(pivots) >= 6
    for a, b in zip(pivots, pivots[1:]):
        assert a.kind != b.kind


def test_zigzag_no_pivots_in_flat_series(uptrend_df):
    # Small linear move with threshold larger than the whole move's % range
    pivots = zigzag_pivots(uptrend_df, threshold_pct=1000.0)
    assert len(pivots) <= 1


def test_fractal_pivots_basic(zigzag_df):
    pivots = fractal_pivots(zigzag_df, window=2)
    assert len(pivots) > 0
    for p in pivots:
        assert p.kind in ("high", "low")
