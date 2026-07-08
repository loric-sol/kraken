"""Swing pivot detection: ZigZag (threshold-based) and Williams fractals."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pandas as pd


@dataclass
class Pivot:
    index: int  # positional index into the source DataFrame
    timestamp: int  # unix seconds
    price: float
    kind: Literal["high", "low"]


def zigzag_pivots(df: pd.DataFrame, threshold_pct: float = 5.0) -> list[Pivot]:
    """Detect alternating swing highs/lows where price reverses by at least
    `threshold_pct` from the last extreme.

    Classic ZigZag algorithm: track a running extreme in the current
    direction; when price reverses by >= threshold_pct from that extreme,
    confirm the extreme as a pivot and flip direction.
    """
    if len(df) < 2:
        return []

    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    ts = df["ts"].to_numpy() if "ts" in df.columns else range(len(df))

    pivots: list[Pivot] = []

    # direction is None until the first confirmed swing locks it in. While
    # None, track both a running high and a running low simultaneously and
    # check for a reversal off of *either* extreme.
    direction: Literal["up", "down"] | None = None
    last_extreme_idx = 0
    highest, highest_idx = highs[0], 0
    lowest, lowest_idx = lows[0], 0

    for i in range(1, len(df)):
        if direction in (None, "up"):
            if highs[i] > highest:
                highest, highest_idx = highs[i], i
            if highest_idx != last_extreme_idx and lows[i] <= highest * (1 - threshold_pct / 100):
                pivots.append(Pivot(index=highest_idx, timestamp=int(ts[highest_idx]), price=float(highest), kind="high"))
                direction = "down"
                last_extreme_idx = highest_idx
                lowest, lowest_idx = lows[i], i
                continue

        if direction in (None, "down"):
            if lows[i] < lowest:
                lowest, lowest_idx = lows[i], i
            if lowest_idx != last_extreme_idx and highs[i] >= lowest * (1 + threshold_pct / 100):
                pivots.append(Pivot(index=lowest_idx, timestamp=int(ts[lowest_idx]), price=float(lowest), kind="low"))
                direction = "up"
                last_extreme_idx = lowest_idx
                highest, highest_idx = highs[i], i
                continue

    # Append the final running extreme as a provisional (unconfirmed) pivot,
    # i.e. the swing currently in progress that hasn't reversed yet.
    if direction in (None, "up") and highest_idx != last_extreme_idx:
        pivots.append(Pivot(index=highest_idx, timestamp=int(ts[highest_idx]), price=float(highest), kind="high"))
    elif direction == "down" and lowest_idx != last_extreme_idx:
        pivots.append(Pivot(index=lowest_idx, timestamp=int(ts[lowest_idx]), price=float(lowest), kind="low"))

    return pivots


def fractal_pivots(df: pd.DataFrame, window: int = 2) -> list[Pivot]:
    """Williams-fractal style pivots: a bar is a high pivot if its high is
    the strict max over `window` bars on each side (and low pivot
    analogously). Used as a finer-grained secondary pivot source for
    confluence with ZigZag pivots."""
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    ts = df["ts"].to_numpy() if "ts" in df.columns else range(len(df))

    pivots: list[Pivot] = []
    n = len(df)
    for i in range(window, n - window):
        h_slice = highs[i - window : i + window + 1]
        l_slice = lows[i - window : i + window + 1]
        if highs[i] == h_slice.max() and (h_slice == highs[i]).sum() == 1:
            pivots.append(Pivot(index=i, timestamp=int(ts[i]), price=float(highs[i]), kind="high"))
        if lows[i] == l_slice.min() and (l_slice == lows[i]).sum() == 1:
            pivots.append(Pivot(index=i, timestamp=int(ts[i]), price=float(lows[i]), kind="low"))

    return pivots
