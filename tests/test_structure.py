from kraken_ew.indicators.structure import (
    detect_structure_break,
    label_structure,
    structure_score,
)
from kraken_ew.waves.pivots import Pivot


def make_pivot(price, kind, idx):
    return Pivot(index=idx, timestamp=idx * 3600, price=price, kind=kind)


def test_label_structure_uptrend():
    # alternating low/high/low/high with each pair higher than the last
    pivots = [
        make_pivot(100, "low", 0),
        make_pivot(110, "high", 1),
        make_pivot(105, "low", 2),
        make_pivot(120, "high", 3),
        make_pivot(112, "low", 4),
        make_pivot(130, "high", 5),
    ]
    events = label_structure(pivots)
    labels = [e.label for e in events]
    assert labels == ["none", "none", "HL", "HH", "HL", "HH"]


def test_detect_bos_up():
    pivots = [
        make_pivot(100, "low", 0),
        make_pivot(110, "high", 1),
        make_pivot(105, "low", 2),
        make_pivot(120, "high", 3),
        make_pivot(112, "low", 4),
        make_pivot(130, "high", 5),
    ]
    events = label_structure(pivots)
    brk = detect_structure_break(events)
    assert brk.kind == "BOS_up"


def test_structure_score_long_favorable():
    pivots = [
        make_pivot(100, "low", 0),
        make_pivot(110, "high", 1),
        make_pivot(105, "low", 2),
        make_pivot(120, "high", 3),
        make_pivot(112, "low", 4),
        make_pivot(130, "high", 5),
    ]
    score = structure_score(pivots, direction="long")
    assert score == 100.0
