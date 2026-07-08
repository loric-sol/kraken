"""Fibonacci engine: retracement/extension levels and confluence scoring."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from kraken_ew.waves.pivots import Pivot

DEFAULT_RETRACEMENT_RATIOS = (0.236, 0.382, 0.5, 0.618, 0.786)
DEFAULT_EXTENSION_RATIOS = (1.272, 1.618, 2.0, 2.618)


@dataclass
class FibLevel:
    ratio: float
    price: float
    kind: Literal["retracement", "extension"]


def retracement_levels(start: Pivot, end: Pivot, ratios: tuple[float, ...] = DEFAULT_RETRACEMENT_RATIOS) -> list[FibLevel]:
    """Retracement levels of the move from `start` to `end`, e.g. for an
    impulsive move up (start=low, end=high), a 0.618 retracement is a
    price 61.8% of the way back down from `end` toward `start`."""
    span = end.price - start.price
    return [FibLevel(ratio=r, price=end.price - span * r, kind="retracement") for r in ratios]


def extension_levels(start: Pivot, end: Pivot, retrace: Pivot, ratios: tuple[float, ...] = DEFAULT_EXTENSION_RATIOS) -> list[FibLevel]:
    """Extension levels projected from `retrace`, based on the size of the
    `start`->`end` move. E.g. a 1.618 extension projects 161.8% of the
    start->end move from `retrace`."""
    span = end.price - start.price
    return [FibLevel(ratio=r, price=retrace.price + span * r, kind="extension") for r in ratios]


def confluence_score(levels_sets: list[list[FibLevel]], target_price: float, tolerance_pct: float = 0.5) -> float:
    """0-100 confluence score: how many independent fib level sets have at
    least one level within `tolerance_pct` of `target_price`.

    A single matching set gives a moderate score; multiple independent sets
    clustering near the same price gives a high score (true confluence).
    """
    if not levels_sets:
        return 0.0

    tolerance = target_price * tolerance_pct / 100
    matches = 0
    for levels in levels_sets:
        if any(abs(level.price - target_price) <= tolerance for level in levels):
            matches += 1

    if matches == 0:
        return 0.0
    return min(100.0, matches / len(levels_sets) * 100)
