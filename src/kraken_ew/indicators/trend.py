"""Trend engine: EMA 20/50/200, trend direction and strength."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pandas as pd


def add_emas(df: pd.DataFrame, periods: tuple[int, ...] = (20, 50, 200)) -> pd.DataFrame:
    """Return a copy of df with ema_<period> columns added."""
    out = df.copy()
    for p in periods:
        out[f"ema_{p}"] = out["close"].ewm(span=p, adjust=False).mean()
    return out


@dataclass
class TrendState:
    direction: Literal["up", "down", "sideways"]
    strength: float  # 0-100
    ema_fast: float
    ema_mid: float
    ema_slow: float


def trend_state(df: pd.DataFrame, periods: tuple[int, int, int] = (20, 50, 200)) -> TrendState:
    """Classify trend direction/strength from the latest bar's EMA stack.

    direction:
      - "up"   if ema_fast > ema_mid > ema_slow
      - "down" if ema_fast < ema_mid < ema_slow
      - "sideways" otherwise (mixed ordering)

    strength: 0-100, based on the % separation between fast and slow EMA
    relative to price, scaled so a 5% spread maps to 100.
    """
    fast_p, mid_p, slow_p = periods
    enriched = add_emas(df, periods)
    last = enriched.iloc[-1]
    fast, mid, slow = last[f"ema_{fast_p}"], last[f"ema_{mid_p}"], last[f"ema_{slow_p}"]

    if fast > mid > slow:
        direction = "up"
    elif fast < mid < slow:
        direction = "down"
    else:
        direction = "sideways"

    spread_pct = abs(fast - slow) / last["close"] * 100
    strength = min(100.0, spread_pct / 5.0 * 100)

    return TrendState(direction=direction, strength=strength, ema_fast=fast, ema_mid=mid, ema_slow=slow)


def trend_score(df: pd.DataFrame, periods: tuple[int, int, int] = (20, 50, 200)) -> float:
    """0-100 score for the "trend alignment" composite component.

    Returns `strength` when direction is up or down, and a low score (capped
    at 30) when sideways, since alignment is the point of this component.
    """
    state = trend_state(df, periods)
    if state.direction == "sideways":
        return min(30.0, state.strength)
    return state.strength
