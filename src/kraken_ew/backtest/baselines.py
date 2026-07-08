"""Baseline strategies for the falsification comparison: buy & hold,
EMA crossover, and a simple RSI momentum strategy. All long-only for
simplicity, matching the spec's baseline list."""

from __future__ import annotations

import pandas as pd

from kraken_ew.indicators.momentum import rsi
from kraken_ew.indicators.trend import add_emas


def buy_and_hold_signals(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Enter on the first bar, never exit."""
    entries = pd.Series(False, index=df.index)
    exits = pd.Series(False, index=df.index)
    entries.iloc[0] = True
    return entries, exits


def ema_crossover_signals(df: pd.DataFrame, fast: int = 20, slow: int = 50) -> tuple[pd.Series, pd.Series]:
    """Enter long when fast EMA crosses above slow EMA; exit when it crosses
    back below."""
    enriched = add_emas(df, periods=(fast, slow))
    fast_col, slow_col = f"ema_{fast}", f"ema_{slow}"
    above = enriched[fast_col] > enriched[slow_col]
    prev_above = above.shift(1).fillna(False).astype(bool)
    cross_up = above & ~prev_above
    cross_down = ~above & prev_above
    return cross_up, cross_down


def momentum_signals(df: pd.DataFrame, period: int = 14, level: float = 50.0) -> tuple[pd.Series, pd.Series]:
    """Enter long when RSI crosses above `level`; exit when it crosses back below."""
    r = rsi(df["close"], period)
    above = r > level
    prev_above = above.shift(1).fillna(False).astype(bool)
    cross_up = above & ~prev_above
    cross_down = ~above & prev_above
    return cross_up, cross_down
