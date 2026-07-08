from kraken_ew.waves.patterns import match_corrective_abc, match_impulse
from kraken_ew.waves.pivots import Pivot


def make_pivot(price, kind, idx):
    return Pivot(index=idx, timestamp=idx * 3600, price=price, kind=kind)


def test_match_impulse_valid_uptrend():
    # Textbook 5-wave impulse up: wave3 longest, wave4 doesn't overlap wave1,
    # wave2/wave4 retrace different %s of their prior waves (alternation).
    pivots = [
        make_pivot(100, "low", 0),   # start
        make_pivot(110, "high", 1),  # wave1 (+10)
        make_pivot(106, "low", 2),   # wave2 (-4, 40% retrace)
        make_pivot(140, "high", 3),  # wave3 (+34, longest)
        make_pivot(128, "low", 4),   # wave4 (-12, ~35% retrace, stays above 110)
        make_pivot(150, "high", 5),  # wave5 (+22)
    ]
    result = match_impulse(pivots)
    assert result.label == "impulse_5"
    assert result.direction == "long"
    assert "wave3_is_shortest" not in result.rule_violations
    assert "wave4_overlaps_wave1" not in result.rule_violations
    assert result.confidence > 50


def test_match_impulse_wave3_shortest_penalized():
    pivots = [
        make_pivot(100, "low", 0),
        make_pivot(110, "high", 1),  # wave1 = 10
        make_pivot(106, "low", 2),
        make_pivot(108, "high", 3),  # wave3 = 2 (shortest)
        make_pivot(104, "low", 4),
        make_pivot(130, "high", 5),  # wave5 = 26
    ]
    result = match_impulse(pivots)
    assert "wave3_is_shortest" in result.rule_violations


def test_match_impulse_wave2_over_100pct_invalidates():
    pivots = [
        make_pivot(100, "low", 0),
        make_pivot(110, "high", 1),  # wave1
        make_pivot(95, "low", 2),    # wave2 retraces beyond start
        make_pivot(140, "high", 3),
        make_pivot(128, "low", 4),
        make_pivot(150, "high", 5),
    ]
    result = match_impulse(pivots)
    assert "wave2_retraces_beyond_wave1_start" in result.rule_violations


def test_match_corrective_abc_valid():
    pivots = [
        make_pivot(150, "high", 0),  # end of prior impulse
        make_pivot(120, "low", 1),   # A (-30)
        make_pivot(135, "high", 2),  # B retrace 50% of A
        make_pivot(101, "low", 3),   # C ~= A * 1.0 from B (120-19=101 -> wave_c=34, c/a ~1.13)
    ]
    result = match_corrective_abc(pivots)
    assert result.label == "corrective_abc"
    assert result.direction == "long"  # correction down -> expect reversal up


def test_match_corrective_abc_b_exceeds_start_penalized():
    pivots = [
        make_pivot(150, "high", 0),
        make_pivot(120, "low", 1),   # A
        make_pivot(155, "high", 2),  # B exceeds start (150)
        make_pivot(110, "low", 3),
    ]
    result = match_corrective_abc(pivots)
    assert "b_exceeds_correction_start" in result.rule_violations
